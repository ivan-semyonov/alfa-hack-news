"""Opt-in structured chat/completions adapter with bounded, observable calls.

No provider is contacted at import or configuration time. Prices and API model
IDs must be supplied by the operator; display names are never translated here.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import ipaddress
import json
import logging
import os
from threading import Lock
from time import perf_counter
from typing import Any, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .ai_toolkit import validate_model

LOGGER = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 1_000_000
MAX_REQUEST_BYTES = 128_000


class ProviderConfigurationError(ValueError):
    code = 'INVALID_CONFIGURATION'

    def __init__(self, field_name: str):
        self.field_name = field_name
        super().__init__(f'Invalid LLM configuration field: {field_name}')


class ProviderUnavailable(RuntimeError):
    """Safe error code: never carries provider bodies, URLs or credentials."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f'LLM provider unavailable: {code}')


def _decimal(value: Any, field_name: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > Decimal('1000000000'):
            raise ValueError
        if positive and not result:
            raise ValueError
        return result
    except (ValueError, InvalidOperation):
        raise ProviderConfigurationError(field_name) from None


def _number(value: Any, field_name: str, low: float, high: float, *, integer=False):
    try:
        result = int(value) if integer else float(value)
        if isinstance(value, bool) or not low <= result <= high:
            raise ValueError
        if integer and str(result) != str(value).strip():
            raise ValueError
        return result
    except (TypeError, ValueError, OverflowError):
        raise ProviderConfigurationError(field_name) from None


def _base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        # Force port parsing; malformed ports otherwise survive urlsplit.
        if parsed.port is not None and parsed.port == 0:
            raise ValueError
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or '?' in value or '#' in value
                or any(character.isspace() or ord(character) < 32 for character in value)):
            raise ValueError
        if parsed.scheme == 'http':
            local = parsed.hostname.lower() == 'localhost'
            if not local:
                try:
                    local = ipaddress.ip_address(parsed.hostname).is_loopback
                except ValueError:
                    pass
            if not local:
                raise ValueError
        # Match the actual transport's parsing rules before any attempt is
        # reserved; InvalidURL errors can otherwise include configured text.
        httpx.URL(value)
        return value.rstrip('/')
    except (ValueError, TypeError, AttributeError, UnicodeError, httpx.InvalidURL):
        raise ProviderConfigurationError('LLM_BASE_URL') from None


@dataclass(frozen=True)
class ProviderConfig:
    enabled: bool = False
    base_url: str | None = None
    model: str | None = None
    api_model: str | None = None
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 20
    max_output_tokens: int = 1500
    max_calls_per_day: int = 50
    input_rub_per_1m: Decimal | None = None
    output_rub_per_1m: Decimal | None = None
    daily_budget_rub: Decimal = Decimal('500')

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ProviderConfigurationError('LLM_ENABLED')
        if self.base_url is not None:
            object.__setattr__(self, 'base_url', _base_url(self.base_url))
        if self.model is not None:
            try:
                validate_model(self.model)
            except ValueError:
                raise ProviderConfigurationError('LLM_MODEL') from None
        for field_name, value in (('LLM_API_MODEL', self.api_model), ('LLM_API_KEY', self.api_key)):
            if value is not None and (not isinstance(value, str) or not value.strip()
                                      or len(value) > 4096
                                      or any(ord(character) < 32 for character in value)):
                raise ProviderConfigurationError(field_name)
        if self.api_key is not None and any(not 33 <= ord(character) <= 126 for character in self.api_key):
            raise ProviderConfigurationError('LLM_API_KEY')
        object.__setattr__(self, 'timeout_seconds', _number(self.timeout_seconds, 'LLM_TIMEOUT_SECONDS', 1, 60))
        object.__setattr__(self, 'max_output_tokens', _number(self.max_output_tokens, 'LLM_MAX_OUTPUT_TOKENS', 128, 4000, integer=True))
        object.__setattr__(self, 'max_calls_per_day', _number(self.max_calls_per_day, 'LLM_MAX_CALLS_PER_DAY', 1, 1000, integer=True))
        for name, env_name in (('input_rub_per_1m', 'LLM_INPUT_RUB_PER_1M'),
                               ('output_rub_per_1m', 'LLM_OUTPUT_RUB_PER_1M')):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _decimal(value, env_name))
        object.__setattr__(self, 'daily_budget_rub', _decimal(self.daily_budget_rub, 'LLM_DAILY_BUDGET_RUB', positive=True))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None):
        values = os.environ if env is None else env
        enabled = values.get('LLM_ENABLED', 'false').strip().lower()
        if enabled not in ('true', 'false', '1', '0'):
            raise ProviderConfigurationError('LLM_ENABLED')

        def optional(name):
            return values.get(name) or None

        return cls(
            enabled=enabled in ('true', '1'), base_url=optional('LLM_BASE_URL'),
            model=optional('LLM_MODEL'), api_model=optional('LLM_API_MODEL'),
            api_key=optional('LLM_API_KEY'),
            timeout_seconds=values.get('LLM_TIMEOUT_SECONDS', '20'),
            max_output_tokens=values.get('LLM_MAX_OUTPUT_TOKENS', '1500'),
            max_calls_per_day=values.get('LLM_MAX_CALLS_PER_DAY', '50'),
            input_rub_per_1m=optional('LLM_INPUT_RUB_PER_1M'),
            output_rub_per_1m=optional('LLM_OUTPUT_RUB_PER_1M'),
            daily_budget_rub=values.get('LLM_DAILY_BUDGET_RUB', '500'),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_model and self.api_key)

    @property
    def priced(self) -> bool:
        return self.input_rub_per_1m is not None and self.output_rub_per_1m is not None

    def status(self) -> dict:
        return {'enabled': self.enabled, 'configured': self.configured,
                'model': self.model, 'protocol': 'chat-completions-json-schema',
                'connection_verified': False, 'prices_configured': self.priced,
                'budget_mode': 'ESTIMATED_PROCESS_LOCAL' if self.priced else 'MONEY_UNKNOWN',
                'max_calls_per_utc_day': self.max_calls_per_day}


@dataclass(frozen=True)
class ProviderResponse:
    content: str = field(repr=False)
    metadata: dict


def strict_json_schema(schema: dict) -> dict:
    """Copy a Pydantic-style schema into the strict closed-object form.

    Optional nullable fields stay nullable, but must be explicitly present in
    output. Defaults are not sent to the provider. This is a format normalizer,
    not a promise that an endpoint supports every remaining schema keyword.
    """
    if not isinstance(schema, dict):
        raise ValueError('JSON schema must be an object')
    result = deepcopy(schema)
    maps = ('properties', '$defs', 'definitions', 'patternProperties', 'dependentSchemas')
    arrays = ('allOf', 'anyOf', 'oneOf', 'prefixItems')
    singles = ('items', 'additionalItems', 'additionalProperties', 'unevaluatedProperties',
               'propertyNames', 'contains', 'not', 'if', 'then', 'else', 'contentSchema')

    def normalize(node):
        if not isinstance(node, dict):
            return
        node.pop('default', None)
        for keyword in maps:
            children = node.get(keyword)
            if isinstance(children, dict):
                for child in children.values():
                    normalize(child)
        for keyword in arrays:
            children = node.get(keyword)
            if isinstance(children, list):
                for child in children:
                    normalize(child)
        for keyword in singles:
            normalize(node.get(keyword))
        if 'properties' in node or node.get('type') == 'object':
            properties = node.setdefault('properties', {})
            if not isinstance(properties, dict):
                raise ValueError('Schema properties must be an object')
            node['required'] = list(properties)
            node['additionalProperties'] = False

    normalize(result)
    return result


@dataclass(frozen=True)
class _Reservation:
    day: str
    rub: Decimal | None


@dataclass
class _DailyUsage:
    calls: int = 0
    rub: Decimal = Decimal('0')


class UsageLedger:
    """Thread-safe estimated accounting for one process, indexed by UTC date."""

    def __init__(self):
        self._lock = Lock()
        self._days: dict[str, _DailyUsage] = {}

    def reserve(self, day: str, config: ProviderConfig, rub: Decimal | None) -> _Reservation:
        with self._lock:
            usage = self._days.setdefault(day, _DailyUsage())
            if usage.calls >= config.max_calls_per_day:
                raise ProviderUnavailable('DAILY_LIMIT')
            if rub is not None and usage.rub + rub > config.daily_budget_rub:
                raise ProviderUnavailable('BUDGET_EXCEEDED')
            usage.calls += 1
            if rub is not None:
                usage.rub += rub
        return _Reservation(day, rub)

    def settle(self, reservation: _Reservation, reported_cost: Decimal | None):
        if reservation.rub is not None and reported_cost is not None:
            with self._lock:
                self._days[reservation.day].rub += reported_cost - reservation.rub

    def snapshot(self, day: str) -> dict:
        with self._lock:
            usage = self._days.get(day, _DailyUsage())
            return {'utc_day': day, 'calls': usage.calls, 'estimated_charged_rub': float(usage.rub)}


_PROCESS_LEDGER = UsageLedger()


def _object_json(raw: str | bytes) -> dict:
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def no_constant(value):
        raise ValueError

    try:
        result = json.loads(raw, object_pairs_hook=no_duplicates, parse_constant=no_constant)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise ProviderUnavailable('INVALID_RESPONSE') from None


def _tokens(usage: dict, name: str) -> int | None:
    value = usage.get(name)
    if value is not None and (type(value) is not int or not 0 <= value <= 1_000_000_000):
        raise ProviderUnavailable('INVALID_RESPONSE')
    return value


class LLMProvider:
    def __init__(self, config: ProviderConfig, *, transport: httpx.BaseTransport | None = None,
                 ledger: UsageLedger | None = None):
        self.config = config
        self._transport = transport
        self._ledger = ledger if ledger is not None else _PROCESS_LEDGER

    def status(self) -> dict:
        return self.config.status()

    def _cost(self, prompt: int | None, completion: int | None) -> Decimal | None:
        if not self.config.priced or prompt is None or completion is None:
            return None
        return (Decimal(prompt) * self.config.input_rub_per_1m
                + Decimal(completion) * self.config.output_rub_per_1m) / Decimal('1000000')

    def extract(self, messages: list[dict], schema: dict) -> ProviderResponse:
        config = self.config
        if not config.enabled:
            raise ProviderUnavailable('DISABLED')
        if not config.configured:
            raise ProviderUnavailable('NOT_CONFIGURED')
        if not isinstance(messages, list) or not 1 <= len(messages) <= 20 or not isinstance(schema, dict):
            raise ProviderUnavailable('INVALID_REQUEST')
        for message in messages:
            if (not isinstance(message, dict) or set(message) != {'role', 'content'}
                    or message['role'] not in ('system', 'user', 'assistant')
                    or not isinstance(message['content'], str)):
                raise ProviderUnavailable('INVALID_REQUEST')
        try:
            payload = {'model': config.api_model, 'messages': messages,
                       'max_tokens': config.max_output_tokens,
                       'response_format': {'type': 'json_schema', 'json_schema': {
                           'name': 'structured_output', 'strict': True,
                           'schema': strict_json_schema(schema)}}}
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (TypeError, ValueError, RecursionError):
            raise ProviderUnavailable('INVALID_REQUEST') from None
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ProviderUnavailable('REQUEST_TOO_LARGE')
        # UTF-8 bytes plus a large framing allowance form a conservative estimate
        # for ordinary tokenizers; provider-specific hidden tokens are unknown.
        reserved_cost = self._cost(len(encoded) + 2048, config.max_output_tokens)
        day = datetime.now(timezone.utc).date().isoformat()
        reservation = self._ledger.reserve(day, config, reserved_cost)
        request_id = uuid4().hex
        started = perf_counter()

        def check_deadline():
            if perf_counter() - started > config.timeout_seconds:
                raise ProviderUnavailable('TIMEOUT')

        try:
            with httpx.Client(transport=self._transport, timeout=config.timeout_seconds,
                              follow_redirects=False, trust_env=False) as client:
                with client.stream('POST', config.base_url + '/chat/completions',
                                   headers={'Authorization': 'Bearer ' + config.api_key,
                                            'Content-Type': 'application/json',
                                            'Accept': 'application/json', 'Accept-Encoding': 'identity'},
                                   content=encoded) as response:
                    check_deadline()
                    if not 200 <= response.status_code < 300:
                        raise ProviderUnavailable('HTTP_ERROR')
                    if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                        raise ProviderUnavailable('INVALID_RESPONSE')
                    data = bytearray()
                    # MockTransport may supply a preloaded response. The same
                    # byte ceiling also applies to that test/local transport.
                    chunks = [response.content] if response.is_stream_consumed else response.iter_raw()
                    for chunk in chunks:
                        check_deadline()
                        if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise ProviderUnavailable('RESPONSE_TOO_LARGE')
                        data.extend(chunk)
                    check_deadline()
            check_deadline()
            body = _object_json(data)
            choices = body.get('choices')
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ProviderUnavailable('INVALID_RESPONSE')
            choice = choices[0]
            if choice.get('finish_reason') == 'length':
                raise ProviderUnavailable('TRUNCATED')
            if choice.get('finish_reason') == 'content_filter':
                raise ProviderUnavailable('REFUSED')
            if choice.get('finish_reason') != 'stop':
                raise ProviderUnavailable('INVALID_RESPONSE')
            message = choice.get('message')
            if not isinstance(message, dict):
                raise ProviderUnavailable('INVALID_RESPONSE')
            if message.get('refusal'):
                raise ProviderUnavailable('REFUSED')
            content = message.get('content')
            if not isinstance(content, str) or not content.strip():
                raise ProviderUnavailable('INVALID_RESPONSE')
            _object_json(content)
            usage = body.get('usage')
            if usage is None:
                usage = {}
            if not isinstance(usage, dict):
                raise ProviderUnavailable('INVALID_RESPONSE')
            prompt_tokens = _tokens(usage, 'prompt_tokens')
            completion_tokens = _tokens(usage, 'completion_tokens')
            cost = self._cost(prompt_tokens, completion_tokens)
            check_deadline()
            self._ledger.settle(reservation, cost)
            metadata = {
                'request_id': request_id, 'model': config.model,
                'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens,
                'duration_ms': round((perf_counter() - started) * 1000, 2),
                'estimated_cost_rub': float(cost) if cost is not None else None,
                'budget_mode': config.status()['budget_mode'],
                'utc_day': day,
            }
            LOGGER.info('llm_request_completed request_id=%s model=%s prompt_tokens=%s completion_tokens=%s duration_ms=%s estimated_cost_rub=%s',
                        request_id, config.model, prompt_tokens, completion_tokens,
                        metadata['duration_ms'], metadata['estimated_cost_rub'])
            return ProviderResponse(content=content, metadata=metadata)
        except (httpx.TimeoutException, TimeoutError):
            code = 'TIMEOUT'
        except httpx.HTTPError:
            code = 'NETWORK_ERROR'
        except ProviderUnavailable as exc:
            code = exc.code
        LOGGER.warning('llm_request_failed request_id=%s model=%s code=%s duration_ms=%s',
                       request_id, config.model, code, round((perf_counter() - started) * 1000, 2))
        raise ProviderUnavailable(code) from None
