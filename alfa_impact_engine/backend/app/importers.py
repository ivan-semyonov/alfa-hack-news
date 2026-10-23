"""Atomic schema-driven bank CSV import with explicit unknown payment semantics."""
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json

from .storage import encode, now


def flag(value):
    value = str(value or '').strip().lower()
    return True if value in ('1', 'true', 'да', 'yes') else False if value in ('0', 'false', 'нет', 'no') else None


def import_csv(store, tenant, request):
    digest = hashlib.sha256(request.content.encode('utf-8')).hexdigest()
    source_id = 'csv:' + digest[:24]
    previous = store.record(tenant, 'import', source_id)
    if previous and previous['status'] == 'IMPORTED':
        return {**previous, 'duplicate': True}
    try:
        dialect = csv.Sniffer().sniff(request.content[:8192], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(request.content.lstrip('\ufeff')), dialect=dialect)
    headers = {str(item).strip().upper() for item in reader.fieldnames or []}
    if len(headers) != len(reader.fieldnames or []):
        raise ValueError('В CSV повторяются заголовки колонок.')
    if {'PAYER', 'BENEFICIARY', 'PAY_AMT', 'PAY_CNT'} <= headers:
        kind = 'payments'
    elif {'SYNTHETIC_F', 'SYNTHETIC_U'} <= headers:
        kind = 'persons'
    elif {'SYNTHETIC_U', 'MAINOKVED_CODE', 'REGION'} <= headers:
        kind = 'companies'
    else:
        raise ValueError('Схема CSV не распознана. Нужны заголовки банковского набора компаний, платежей или связей.')
    prepared, errors, seen = [], [], set()
    for number, raw in enumerate(reader, 2):
        if number > 50_001:
            raise ValueError('Один импорт ограничен 50 000 строками. Разделите большой файл на части.')
        row = {str(key).strip().upper(): str(value or '').strip() for key, value in raw.items() if key is not None}
        try:
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError('INVALID_COLUMN_COUNT')
            keys = ['SYNTHETIC_U'] if kind == 'companies' else ['PAYER', 'BENEFICIARY'] if kind == 'payments' else ['SYNTHETIC_F', 'SYNTHETIC_U']
            if any(not row.get(key) or len(row[key]) > 100 or any(ord(c) < 32 for c in row[key]) for key in keys):
                raise ValueError('INVALID_IDENTIFIER')
            identity = tuple(row[key] for key in keys)
            if identity in seen:
                raise ValueError('DUPLICATE_IDENTIFIER')
            seen.add(identity)
            if kind == 'companies':
                company = {'id': row['SYNTHETIC_U'], 'name': row.get('NAME') or 'Организация ' + row['SYNTHETIC_U'],
                           'industry_code': row['MAINOKVED_CODE'] or None, 'industry_label': row.get('MAINOKVED_NAME') or None,
                           'region': row['REGION'] or None, 'bank_loan_mark': flag(row.get('CL_PRODUCT_LOA_MARK')),
                           'is_synthetic': request.is_synthetic, 'source_id': source_id, 'market_share': None,
                           'bank_fields': row, 'profile_gaps': ['Доля рынка неизвестна.', 'Кредитный признак не определяет долг и ставку.',
                                                               'Отрасль не доказывает процессы и поставщиков.']}
                prepared.append(company)
            elif kind == 'payments':
                amount = Decimal(row['PAY_AMT'].replace(' ', '').replace(',', '.'))
                count = int(row['PAY_CNT'])
                if not amount.is_finite() or amount < 0 or len(str(amount)) > 40 or count < 0 or count > 2_000_000_000:
                    raise ValueError('INVALID_PAYMENT_VALUE')
                if not store.company(tenant, row['PAYER']) or not store.company(tenant, row['BENEFICIARY']):
                    raise ValueError('MISSING_COMPANY_REFERENCE')
                prepared.append({'id': source_id + ':' + str(number), 'payer': row['PAYER'], 'beneficiary': row['BENEFICIARY'],
                                 'amount': str(amount), 'pay_count': count, 'period': request.payment_period,
                                 'unit': request.payment_unit, 'source_id': source_id})
            else:
                if not store.company(tenant, row['SYNTHETIC_U']):
                    raise ValueError('MISSING_COMPANY_REFERENCE')
                prepared.append({'person_id': row['SYNTHETIC_F'], 'company_id': row['SYNTHETIC_U'], 'source_id': source_id})
        except (ValueError, InvalidOperation, OverflowError) as exc:
            # Codes and row numbers only: never echo banking row values.
            message = str(exc) if str(exc) in ('INVALID_IDENTIFIER', 'DUPLICATE_IDENTIFIER', 'INVALID_PAYMENT_VALUE', 'MISSING_COMPANY_REFERENCE', 'INVALID_COLUMN_COUNT') else 'INVALID_VALUE'
            errors.append({'row': number, 'code': message})
            if len(errors) >= 100:
                break
    report = {'id': source_id, 'filename': request.filename, 'kind': kind, 'rows_valid': len(prepared), 'errors': errors,
              'status': 'REJECTED' if errors else 'IMPORTED', 'duplicate': False, 'at': now(),
              'warnings': ['Платёж — финансовое взаимодействие, не поставка. Период и единица неизвестны, если не указаны.'] if kind == 'payments' else []}
    if not errors:
        with store.transaction() as db:
            for row in prepared:
                if kind == 'companies':
                    db.execute('INSERT INTO companies(tenant,id,payload,created_at) VALUES(?,?,?,?) '
                               'ON CONFLICT(tenant,id) DO UPDATE SET payload=excluded.payload',
                               (tenant, row['id'], encode(row), now()))
                elif kind == 'payments':
                    db.execute('INSERT INTO payments(tenant,id,payer,beneficiary,amount,pay_count,source_id,period) VALUES(?,?,?,?,?,?,?,?) '
                               'ON CONFLICT(tenant,id) DO NOTHING',
                               (tenant, row['id'], row['payer'], row['beneficiary'], row['amount'], row['pay_count'], source_id,
                                encode({'period': row['period'], 'unit': row['unit']})))
                else:
                    key = hashlib.sha256((row['person_id'] + '/' + row['company_id']).encode()).hexdigest()
                    db.execute('INSERT INTO records(tenant,kind,id,payload,created_at) VALUES(?,?,?,?,?) '
                               'ON CONFLICT(tenant,kind,id) DO UPDATE SET payload=excluded.payload',
                               (tenant, 'person_link', key, encode(row), now()))
            db.execute('INSERT INTO records(tenant,kind,id,payload,created_at) VALUES(?,?,?,?,?) '
                       'ON CONFLICT(tenant,kind,id) DO UPDATE SET payload=excluded.payload',
                       (tenant, 'import', source_id, encode(report), now()))
    else:
        store.put_record(tenant, 'import', source_id, report)
    return report
