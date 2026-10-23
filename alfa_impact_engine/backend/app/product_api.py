"""Authenticated, tenant-scoped product API. Legacy demo routes use no private state."""
import base64
import binascii
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field, HttpUrl

from .app_config import get_service
from .ai_toolkit import ALLOWED_MODELS
from .importers import import_csv
from .industry import build_graph, registry
from .llm_provider import ProviderConfigurationError, ProviderUnavailable
from .news_fetch import fetch_article
from .product_contracts import (Input, LoginInput, AnalyzeInput, QuestionInput, FeedbackInput,
                                CompanyInput, DocumentInput, CsvInput, ProviderInput)
from .provider_settings import DurableLedger
from .storage import identifier, now

router = APIRouter(prefix='/api/v1', tags=['workspace'])
S = Annotated[object, Depends(get_service)]


def same_origin(request):
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Недопустимый источник запроса.')
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403, 'Межсайтовый запрос запрещён.')


def principal(request: Request, service: S):
    user = service.access.principal(request.cookies.get('impact_session'))
    if not user:
        raise HTTPException(401, 'Войдите в рабочую область.')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        same_origin(request)
        import hmac
        if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), user['csrf']):
            raise HTTPException(403, 'Сессия изменилась. Обновите страницу и повторите действие.')
    return user


U = Annotated[dict, Depends(principal)]


def admin(user):
    if user['role'] != 'ADMIN':
        raise HTTPException(403, 'Действие доступно администратору рабочей области.')


def required(value, message='Объект не найден в рабочей области.'):
    if value is None:
        raise HTTPException(404, message)
    return value


class SetupInput(Input):
    password: str = Field(min_length=12, max_length=256)


class UrlInput(Input):
    url: HttpUrl


@router.get('/bootstrap')
def bootstrap(request: Request, service: S):
    host = request.client.host if request.client else ''
    return {'version': '1.0.0', 'setup_needed': service.access.setup_needed(), 'demo_enabled': service.demo,
            'local_setup': host in ('127.0.0.1', '::1', 'testclient'), 'models': list(ALLOWED_MODELS),
            'templates': registry()}


@router.post('/setup', status_code=201)
def setup(data: SetupInput, request: Request, service: S):
    same_origin(request)
    if not request.client or request.client.host not in ('127.0.0.1', '::1', 'testclient'):
        raise HTTPException(403, 'Первичная настройка доступна на локальном компьютере. Для сервера задайте APP_ADMIN_PASSWORD.')
    try:
        service.access.setup(data.password)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {'username': 'admin', 'message': 'Рабочая область создана. Войдите с выбранным паролем.'}


@router.post('/login')
def login(data: LoginInput, request: Request, response: Response, service: S):
    same_origin(request)
    try:
        token, user = service.access.login(data.username, data.password, request.client.host if request.client else 'local')
    except PermissionError as exc:
        raise HTTPException(401, str(exc)) from None
    response.set_cookie('impact_session', token, httponly=True, secure=request.url.scheme == 'https', samesite='strict', max_age=28800, path='/')
    if user['tenant'] == 'demo':
        service.ensure_demo_runs()
    return user


@router.get('/me')
def me(user: U):
    return user


@router.post('/logout')
def logout(request: Request, response: Response, user: U, service: S):
    service.access.logout(request.cookies.get('impact_session'))
    response.delete_cookie('impact_session', path='/')
    return {'ok': True}


@router.get('/companies')
def companies(user: U, service: S):
    return service.store.companies(user['tenant'])


@router.put('/companies')
def company_save(data: CompanyInput, user: U, service: S):
    admin(user)
    value = data.model_dump() | {'source_id': 'user:' + identifier('profile'), 'market_share': None}
    service.store.put_company(user['tenant'], value)
    return value


@router.get('/companies/{company_id}')
def company_detail(company_id: str, user: U, service: S):
    company = required(service.store.company(user['tenant'], company_id))
    graph, evidence, template = build_graph(company)
    return {'company': company, 'graph': graph.company_subgraph(company_id), 'evidence': [item.model_dump(mode='json') for item in evidence],
            'template': template, 'payments': service.payment_context(user['tenant'], company_id)}


@router.get('/feed/{company_id}')
def feed(company_id: str, user: U, service: S):
    required(service.store.company(user['tenant'], company_id))
    return service.feed(user['tenant'], company_id)


@router.get('/news')
def news(user: U, service: S):
    return [json.loads(row['payload']) for row in service.store.all('SELECT payload FROM news WHERE tenant=? ORDER BY created_at DESC LIMIT 200', (user['tenant'],))]


@router.post('/news/fetch')
def fetch(data: UrlInput, user: U):
    try:
        return fetch_article(str(data.url))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/analyses', status_code=202)
def analyze(data: AnalyzeInput, tasks: BackgroundTasks, user: U, service: S):
    tenant = user['tenant']
    required(service.store.company(tenant, data.company_id))
    # One in-flight analysis per workspace bounds concurrent OCR and paid calls.
    with service.lock:
        previous = service.store.record(tenant, 'idempotency', data.idempotency_key) if data.idempotency_key else None
        if service.store.one('SELECT id FROM runs WHERE tenant=? AND status=?', (tenant, 'RUNNING')) and not previous:
            raise HTTPException(409, 'Дождитесь текущего анализа.')
        if data.mode == 'LLM':
            if tenant == 'demo':
                raise HTTPException(403, 'Внешняя модель доступна в настроенной рабочей области.')
            try:
                if not service.settings.config(tenant).configured or not service.settings.config(tenant).enabled:
                    raise HTTPException(409, 'Сначала настройте и включите подключение к модели.')
            except ProviderConfigurationError:
                raise HTTPException(422, 'Недопустимые настройки модели.') from None
        try:
            run, created = service.create_run(tenant, data)
        except ValueError:
            raise HTTPException(409, 'Ключ повторного запроса уже использован для других данных.') from None
        if created:
            tasks.add_task(service.execute, tenant, run['id'])
        return {'id': run['id'], 'status': run['status'], 'created': created}


@router.get('/analyses/{run_id}')
def analysis(run_id: str, user: U, service: S):
    return required(service.store.run(user['tenant'], run_id))


@router.get('/analyses/{run_id}/export')
def analysis_export(run_id: str, user: U, service: S):
    run = required(service.store.run(user['tenant'], run_id))
    return JSONResponse(run, headers={'Content-Disposition': 'attachment; filename="impact-analysis.json"'})


@router.post('/analyses/{run_id}/questions')
def question(run_id: str, data: QuestionInput, user: U, service: S):
    try:
        return service.question(user['tenant'], run_id, data.question)
    except LookupError:
        raise HTTPException(404, 'Завершённый анализ не найден.') from None


@router.get('/analyses/{run_id}/questions')
def questions(run_id: str, user: U, service: S):
    required(service.store.run(user['tenant'], run_id))
    return service.store.records(user['tenant'], 'question:' + run_id)


@router.post('/analyses/{run_id}/feedback', status_code=201)
def feedback(run_id: str, data: FeedbackInput, user: U, service: S):
    run = required(service.store.run(user['tenant'], run_id))
    result = data.model_dump() | {'id': identifier('feedback'), 'run_id': run_id, 'company_id': run['company_id'], 'created_at': now()}
    service.store.put_record(user['tenant'], 'feedback', result['id'], result)
    return result


@router.get('/materials')
def materials(user: U, service: S):
    return {'documents': service.materials.list(user['tenant']), 'folder': str(service.materials.folder / user['tenant']),
            'last_sync': service.store.record(user['tenant'], 'materials_sync', 'last')}


@router.post('/materials', status_code=201)
def material_add(data: DocumentInput, user: U, service: S):
    admin(user)
    if bool(data.text) == bool(data.pdf_base64):
        raise HTTPException(422, 'Передайте текст или PDF.')
    try:
        pdf = base64.b64decode(data.pdf_base64, validate=True) if data.pdf_base64 else None
        doc, created = service.materials.add(user['tenant'], title=data.title, kind=data.kind, author=data.author,
                 published_at=data.published_at, source_url=data.source_url, text=data.text, pdf=pdf)
        return {'document': doc, 'created': created}
    except (ValueError, binascii.Error):
        raise HTTPException(422, 'Не удалось прочитать материал. Проверьте PDF, текст, лимит 10 МБ и доступность OCR.') from None


@router.post('/materials/sync')
def material_sync(user: U, service: S):
    admin(user)
    return service.materials.sync(user['tenant'])


@router.get('/materials/{doc_id}')
def material_detail(doc_id: str, user: U, service: S):
    doc = required(service.materials.get(user['tenant'], doc_id, full=True))
    return service.materials.public(doc) | {'pages': doc['pages'], 'has_pdf': bool(doc['original_path'])}


@router.get('/materials/{doc_id}/pdf')
def material_pdf(doc_id: str, user: U, service: S):
    doc = required(service.materials.get(user['tenant'], doc_id, full=True))
    path = Path(doc['original_path'] or '')
    if not doc['original_path'] or not path.is_file() or not path.resolve().is_relative_to(service.runtime.resolve() / 'documents' / user['tenant']):
        raise HTTPException(404, 'Оригинал PDF недоступен.')
    return FileResponse(path, media_type='application/pdf', filename='analytics.pdf', content_disposition_type='attachment')


@router.post('/imports')
def import_data(data: CsvInput, user: U, service: S):
    admin(user)
    try:
        return import_csv(service.store, user['tenant'], data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/imports')
def imports(user: U, service: S):
    admin(user)
    return service.store.records(user['tenant'], 'import')


@router.get('/settings/provider')
def settings(user: U, service: S):
    admin(user)
    try:
        result = service.settings.public(user['tenant'])
        day = datetime.now(timezone.utc).date().isoformat()
        if result['key_unavailable']:
            usage = {'utc_day': day, 'calls': None, 'estimated_charged_rub': None}
        else:
            config = service.settings.config(user['tenant'])
            usage = DurableLedger(service.store, config.api_key).snapshot(day)
        return result | {'usage': usage, 'models': list(ALLOWED_MODELS)}
    except (ValueError, ProviderConfigurationError):
        raise HTTPException(422, 'Не удалось открыть настройки. Проверьте переменные окружения и локальное хранилище ключа.') from None


@router.put('/settings/provider')
def settings_save(data: ProviderInput, user: U, service: S):
    admin(user)
    try:
        return service.settings.save(user['tenant'], data)
    except ProviderConfigurationError as exc:
        raise HTTPException(422, 'Некорректное поле конфигурации: ' + exc.field_name) from None
    except ValueError as exc:
        # Local validation strings never contain a key or provider response.
        raise HTTPException(422, str(exc)) from None


@router.post('/settings/provider/test')
def settings_test(user: U, service: S):
    admin(user)
    try:
        provider = service.settings.provider(user['tenant'])
        result = provider.extract([{'role': 'system', 'content': 'Верни только JSON {"ok":true}.'}, {'role': 'user', 'content': 'Проверка JSON подключения.'}],
            {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok'], 'additionalProperties': False})
        if json.loads(result.content) != {'ok': True}:
            raise ProviderUnavailable('INVALID_TEST_RESPONSE')
        return {'ok': True, 'metadata': result.metadata}
    except (ProviderUnavailable, ProviderConfigurationError) as exc:
        raise HTTPException(503, 'Проверка не пройдена: ' + exc.code) from None
    except (ValueError, TypeError):
        raise HTTPException(503, 'Ответ провайдера не прошёл проверку JSON.') from None


@router.get('/metrics')
def metrics(user: U, service: S):
    return service.metrics(user['tenant'])
