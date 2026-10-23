"""Encrypted tenant provider settings; no secret is ever returned to the UI."""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import os
import base64
import secrets
from pathlib import Path
from threading import RLock

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from .llm_provider import ProviderConfig, LLMProvider, ProviderUnavailable
from .storage import encode, now


@dataclass
class Reservation:
    day: str
    rub: Decimal | None


class DurableLedger:
    """Atomic shared-key usage accounting across server restarts/processes."""
    def __init__(self, store, api_key):
        self.store = store
        self.key = hashlib.sha256((api_key or 'disabled').encode()).hexdigest()

    def reserve(self, day, config, rub):
        key = self.key + ':' + day
        with self.store.transaction() as db:
            db.execute('INSERT INTO records(tenant,kind,id,payload,created_at) VALUES(?,?,?,?,?) ON CONFLICT(tenant,kind,id) DO NOTHING',
                       ('system', 'provider_usage', key, encode({'calls': 0, 'rub': '0'}), now()))
            db.execute('SELECT payload FROM records WHERE tenant=? AND kind=? AND id=?' + (' FOR UPDATE' if self.store.postgres else ''),
                       ('system', 'provider_usage', key))
            usage = json.loads(db.fetchone()['payload'])
            if usage['calls'] >= config.max_calls_per_day:
                raise ProviderUnavailable('DAILY_LIMIT')
            cost = Decimal(usage['rub'])
            if rub is not None and cost + rub > config.daily_budget_rub:
                raise ProviderUnavailable('BUDGET_EXCEEDED')
            db.execute('UPDATE records SET payload=? WHERE tenant=? AND kind=? AND id=?',
                       (encode({'calls': usage['calls'] + 1, 'rub': str(cost + (rub or 0))}), 'system', 'provider_usage', key))
        return Reservation(day, rub)

    def settle(self, reservation, reported_cost):
        if reservation.rub is None or reported_cost is None:
            return
        key = self.key + ':' + reservation.day
        with self.store.transaction() as db:
            db.execute('SELECT payload FROM records WHERE tenant=? AND kind=? AND id=?' + (' FOR UPDATE' if self.store.postgres else ''),
                       ('system', 'provider_usage', key))
            usage = json.loads(db.fetchone()['payload'])
            usage['rub'] = str(Decimal(usage['rub']) + reported_cost - reservation.rub)
            db.execute('UPDATE records SET payload=? WHERE tenant=? AND kind=? AND id=?',
                       (encode(usage), 'system', 'provider_usage', key))

    def snapshot(self, day):
        usage = self.store.record('system', 'provider_usage', self.key + ':' + day) or {'calls': 0, 'rub': '0'}
        return {'utc_day': day, 'calls': usage['calls'], 'estimated_charged_rub': float(usage['rub'])}


class Vault:
    """Portable authenticated encryption, independent of OS/user/device identity.

    DB contains versioned nonce+ciphertext+tag only. APP_SECRET_KEY or vault.key
    contains a separate 32-byte master key, urlsafe-base64 encoded.
    """
    def __init__(self, directory):
        self.directory = directory
        self._cipher = None
        self._lock = RLock()

    @property
    def cipher(self):
        with self._lock:
            if self._cipher is None:
                self._cipher = self._load()
            return self._cipher

    def _load(self):
        key = os.getenv('APP_SECRET_KEY')
        if key:
            return self._cipher_from_key(key.encode('ascii'))
        path = Path(self.directory) / 'vault.key'
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            stored = base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256))
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as output:
                    output.write(stored)
            except FileExistsError:
                pass
        return self._cipher_from_key(path.read_bytes().strip())

    @staticmethod
    def _cipher_from_key(encoded):
        try:
            key = base64.b64decode(encoded, altchars=b'-_', validate=True)
            if len(key) != 32:
                raise ValueError
            return AESGCM(key)
        except (ValueError, TypeError):
            raise ValueError('Мастер-ключ должен содержать 32 случайных байта в URL-safe Base64.') from None

    def seal(self, key, context=''):
        if not key:
            return None
        nonce = secrets.token_bytes(12)
        encrypted = self.cipher.encrypt(nonce, key.encode(), ('alfa-provider:v1:' + context).encode())
        return 'aesgcm:v1:' + base64.urlsafe_b64encode(nonce + encrypted).decode('ascii')

    def open(self, sealed, context=''):
        if not sealed:
            return None
        try:
            if not sealed.startswith('aesgcm:v1:'):
                raise ValueError
            value = base64.b64decode(sealed[10:], altchars=b'-_', validate=True)
            return self.cipher.decrypt(value[:12], value[12:], ('alfa-provider:v1:' + context).encode()).decode()
        except (InvalidTag, ValueError, UnicodeError):
            raise ValueError('Не удалось расшифровать ключ. Восстановите мастер-ключ или введите API-ключ заново.') from None


class ProviderSettings:
    def __init__(self, store, directory):
        self.store, self.vault = store, Vault(directory)
        self.lock = RLock()

    def config(self, tenant, *, decrypt=True):
        value = self.store.record(tenant, 'settings', 'provider')
        if not value:
            environment = dict(os.environ)
            environment.setdefault('LLM_TIMEOUT_SECONDS', '30')
            environment.setdefault('LLM_MAX_OUTPUT_TOKENS', '3000')
            return ProviderConfig.from_env(environment)
        return ProviderConfig(enabled=value['enabled'], base_url=value['base_url'] or None,
                              model=value['model'] or None, api_model=value['api_model'] or None,
                              api_key=self.vault.open(value.get('sealed_key'), tenant) if decrypt else None,
                              timeout_seconds=value['timeout_seconds'], max_output_tokens=value['max_output_tokens'],
                              max_calls_per_day=value['max_calls_per_day'],
                              input_rub_per_1m=value.get('input_rub_per_1m'), output_rub_per_1m=value.get('output_rub_per_1m'),
                              daily_budget_rub=value['daily_budget_rub'])

    def public(self, tenant):
        saved = self.store.record(tenant, 'settings', 'provider') or {}
        unavailable = False
        try:
            config = self.config(tenant)
        except ValueError:
            config = self.config(tenant, decrypt=False)
            unavailable = True
        return {**config.status(), 'base_url': config.base_url or '', 'api_model': config.api_model or '',
                'budget_mode': 'ESTIMATED_PERSISTENT_SHARED_KEY' if config.priced else 'MONEY_UNKNOWN',
                'has_api_key': bool(saved.get('sealed_key') or config.api_key), 'key_unavailable': unavailable,
                'response_format': saved.get('response_format', 'json_schema'),
                'timeout_seconds': config.timeout_seconds, 'max_output_tokens': config.max_output_tokens,
                'max_calls_per_day': config.max_calls_per_day,
                'input_rub_per_1m': str(config.input_rub_per_1m) if config.input_rub_per_1m is not None else None,
                'output_rub_per_1m': str(config.output_rub_per_1m) if config.output_rub_per_1m is not None else None,
                'daily_budget_rub': str(config.daily_budget_rub)}

    def save(self, tenant, request):
        with self.lock:
            old = self.store.record(tenant, 'settings', 'provider') or {}
            key = request.api_key or (None if request.clear_key else self.config(tenant).api_key)
            if old.get('base_url') and old['base_url'].rstrip('/') != request.base_url.rstrip('/') and key and not request.api_key:
                raise ValueError('При смене адреса API введите ключ повторно.')
            config = ProviderConfig(enabled=request.enabled, base_url=request.base_url or None,
                                    model=request.model or None, api_model=request.api_model or None, api_key=key,
                                    timeout_seconds=request.timeout_seconds, max_output_tokens=request.max_output_tokens,
                                    max_calls_per_day=request.max_calls_per_day, input_rub_per_1m=request.input_rub_per_1m,
                                    output_rub_per_1m=request.output_rub_per_1m, daily_budget_rub=request.daily_budget_rub)
            if config.enabled and not config.configured:
                raise ValueError('Для включения заполните адрес, разрешённую модель, технический ID и ключ.')
            value = request.model_dump(exclude={'api_key', 'clear_key'})
            value['base_url'] = config.base_url or ''
            value['sealed_key'] = self.vault.seal(key, tenant)
            self.store.put_record(tenant, 'settings', 'provider', value)
            return self.public(tenant)

    def provider(self, tenant):
        config = self.config(tenant)
        saved = self.store.record(tenant, 'settings', 'provider') or {}
        return LLMProvider(config, response_format=saved.get('response_format', 'json_schema'),
                           ledger=DurableLedger(self.store, config.api_key))
