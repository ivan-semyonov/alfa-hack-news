from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging

import httpx
import pytest

from app.llm_provider import (
    LLMProvider, MAX_RESPONSE_BYTES, ProviderConfig, ProviderConfigurationError,
    ProviderUnavailable, UsageLedger, strict_json_schema,
)

MESSAGES = [{'role': 'system', 'content': 'Return a JSON object.'},
            {'role': 'user', 'content': 'private-article-text'}]
SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
          'required': ['ok'], 'additionalProperties': False}


def config(**changes):
    values = {'enabled': True, 'base_url': 'https://provider.example/v1',
              'model': 'GLM-5.3-Flash', 'api_model': 'provider-technical-id',
              'api_key': 'secret-test-key'}
    return ProviderConfig(**(values | changes))


def envelope(**changes):
    return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{"ok":true}'}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10}} | changes


def provider(body=None, *, status=200, cfg=None, ledger=None, handler=None):
    if handler is None:
        handler = lambda request: httpx.Response(status, json=envelope() if body is None else body)
    return LLMProvider(cfg or config(), transport=httpx.MockTransport(handler), ledger=ledger or UsageLedger())


def unavailable(instance, expected):
    with pytest.raises(ProviderUnavailable) as error:
        instance.extract(MESSAGES, SCHEMA)
    assert error.value.code == expected
    return error.value


def test_default_is_disabled_and_status_never_claims_connection():
    cfg = ProviderConfig.from_env({})
    assert cfg.status()['enabled'] is False
    assert cfg.status()['configured'] is False
    assert cfg.status()['connection_verified'] is False
    unavailable(provider(cfg=cfg), 'DISABLED')


def test_api_model_must_be_explicit_and_not_guessed():
    cfg = config(api_model=None)
    assert cfg.configured is False
    unavailable(provider(cfg=cfg), 'NOT_CONFIGURED')


@pytest.mark.parametrize('field,value', [
    ('LLM_MODEL', 'unapproved-model'), ('LLM_ENABLED', 'maybe'),
    ('LLM_BASE_URL', 'http://provider.example/v1'),
    ('LLM_BASE_URL', 'https://secret@provider.example/v1'),
    ('LLM_BASE_URL', 'https://provider.example/v1?key=secret'),
    ('LLM_BASE_URL', 'https://provider.example/v1#secret'),
    ('LLM_BASE_URL', 'https://provider.example/v1?'),
    ('LLM_BASE_URL', 'https://provider.example/v1#'),
    ('LLM_BASE_URL', 'https://provider.example:bad/v1'),
    ('LLM_BASE_URL', 'https://provider.example:0/v1'),
    ('LLM_TIMEOUT_SECONDS', '0'), ('LLM_TIMEOUT_SECONDS', '61'),
    ('LLM_MAX_OUTPUT_TOKENS', '127'), ('LLM_MAX_OUTPUT_TOKENS', '4001'),
    ('LLM_DAILY_BUDGET_RUB', 'NaN'), ('LLM_DAILY_BUDGET_RUB', '0'),
    ('LLM_INPUT_RUB_PER_1M', '-1'), ('LLM_MAX_CALLS_PER_DAY', '0'),
    ('LLM_API_KEY', 'secret\nkey'),
])
def test_invalid_configuration_is_rejected_without_values(field, value):
    with pytest.raises(ProviderConfigurationError) as error:
        ProviderConfig.from_env({field: value})
    assert error.value.field_name == field
    assert value not in str(error.value)


@pytest.mark.parametrize('base', ['http://localhost:8080/v1', 'http://127.0.0.1:8080/v1', 'http://[::1]:8080/v1'])
def test_http_is_only_allowed_for_explicit_loopback(base):
    assert config(base_url=base).base_url == base


def test_success_sends_explicit_model_and_limits_and_returns_safe_usage(caplog):
    def handler(request):
        assert request.url == 'https://provider.example/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer secret-test-key'
        payload = json.loads(request.content)
        assert payload['model'] == 'provider-technical-id'
        assert payload['max_tokens'] == 1500
        assert payload['response_format']['json_schema']['schema'] == SCHEMA
        return httpx.Response(200, json=envelope())

    with caplog.at_level(logging.INFO, logger='app.llm_provider'):
        result = provider(handler=handler).extract(MESSAGES, SCHEMA)
    assert json.loads(result.content) == {'ok': True}
    assert result.metadata['prompt_tokens'] == 100
    assert result.metadata['completion_tokens'] == 10
    assert result.metadata['estimated_cost_rub'] is None
    assert result.metadata['budget_mode'] == 'MONEY_UNKNOWN'
    assert result.metadata['duration_ms'] >= 0
    for secret in ('secret-test-key', 'private-article-text', 'provider-technical-id'):
        assert secret not in caplog.text
        assert secret not in repr(result)
        assert secret not in json.dumps(config().status())
    assert 'secret-test-key' not in repr(config())


def test_missing_usage_is_explicitly_unknown():
    body = envelope()
    body.pop('usage')
    result = provider(body).extract(MESSAGES, SCHEMA)
    assert result.metadata['prompt_tokens'] is None
    assert result.metadata['completion_tokens'] is None
    assert result.metadata['estimated_cost_rub'] is None


@pytest.mark.parametrize('body,code', [
    ({'choices': []}, 'INVALID_RESPONSE'),
    (envelope(choices=[{'finish_reason': 'length', 'message': {'content': '{}'}}]), 'TRUNCATED'),
    (envelope(choices=[{'finish_reason': 'content_filter', 'message': {'content': '{}'}}]), 'REFUSED'),
    (envelope(choices=[{'finish_reason': 'stop', 'message': {'content': '{}', 'refusal': 'private-refusal'}}]), 'REFUSED'),
    (envelope(choices=[{'finish_reason': 'stop', 'message': {'content': [{'text': '{}'}]}}]), 'INVALID_RESPONSE'),
    (envelope(choices=[{'finish_reason': 'stop', 'message': {'content': 'not JSON secret-test-key'}}]), 'INVALID_RESPONSE'),
    (envelope(choices=[{'finish_reason': 'stop', 'message': {'content': '{"x":1,"x":2}'}}]), 'INVALID_RESPONSE'),
    (envelope(usage=[]), 'INVALID_RESPONSE'),
    (envelope(usage={'prompt_tokens': True}), 'INVALID_RESPONSE'),
])
def test_invalid_truncated_refused_responses_are_safe(body, code, caplog):
    with caplog.at_level(logging.WARNING, logger='app.llm_provider'):
        error = unavailable(provider(body), code)
    assert 'private-refusal' not in caplog.text
    assert 'secret-test-key' not in caplog.text
    assert 'secret-test-key' not in str(error)


def test_invalid_envelope_json_and_http_errors_do_not_expose_body():
    handler = lambda request: httpx.Response(200, content=b'private-response invalid-json')
    assert 'private-response' not in str(unavailable(provider(handler=handler), 'INVALID_RESPONSE'))
    handler = lambda request: httpx.Response(401, content=b'private-response secret-test-key')
    assert 'secret-test-key' not in str(unavailable(provider(handler=handler), 'HTTP_ERROR'))


def test_redirects_are_not_followed():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={'location': 'https://other.example/steal'})
    unavailable(provider(handler=handler), 'HTTP_ERROR')
    assert len(requests) == 1


@pytest.mark.parametrize('kind,code', [(httpx.ReadTimeout, 'TIMEOUT'), (httpx.ConnectError, 'NETWORK_ERROR')])
def test_transport_failures_are_safe_without_retries(kind, code):
    attempts = []
    def handler(request):
        attempts.append(request)
        raise kind('private-network-detail secret-test-key', request=request)
    error = unavailable(provider(handler=handler), code)
    assert len(attempts) == 1
    assert 'private-network-detail' not in str(error)


def test_response_byte_limit_for_preloaded_and_streamed_transport():
    raw = b'a' * (MAX_RESPONSE_BYTES + 1)
    for handler in (lambda request: httpx.Response(200, content=raw),
                    lambda request: httpx.Response(200, stream=httpx.ByteStream(raw))):
        unavailable(provider(handler=handler), 'RESPONSE_TOO_LARGE')


def test_request_limit_precedes_network():
    instance = provider(handler=lambda request: pytest.fail('Network must not be called'))
    with pytest.raises(ProviderUnavailable) as error:
        instance.extract([{'role': 'user', 'content': 'a' * 130_000}], SCHEMA)
    assert error.value.code == 'REQUEST_TOO_LARGE'


def test_call_ceiling_is_shared_by_instances_and_errors_consume_attempts():
    ledger = UsageLedger()
    first = provider(status=500, cfg=config(max_calls_per_day=1), ledger=ledger)
    unavailable(first, 'HTTP_ERROR')
    second = provider(cfg=config(max_calls_per_day=1), ledger=ledger)
    unavailable(second, 'DAILY_LIMIT')


def test_priced_reservation_settlement_and_budget_guard():
    ledger = UsageLedger()
    cfg = config(input_rub_per_1m=Decimal('100'), output_rub_per_1m=Decimal('200'), daily_budget_rub=Decimal('1'))
    result = provider(cfg=cfg, ledger=ledger).extract(MESSAGES, SCHEMA)
    assert result.metadata['estimated_cost_rub'] == pytest.approx(0.012)
    assert result.metadata['budget_mode'] == 'ESTIMATED_PROCESS_LOCAL'
    day = datetime.now(timezone.utc).date().isoformat()
    assert ledger.snapshot(day)['estimated_charged_rub'] == pytest.approx(0.012)
    tiny = config(input_rub_per_1m=Decimal('100'), output_rub_per_1m=Decimal('200'), daily_budget_rub=Decimal('0.001'))
    unavailable(provider(cfg=tiny, ledger=UsageLedger()), 'BUDGET_EXCEEDED')


def test_ledger_reservation_is_atomic_and_utc_days_are_separate():
    ledger = UsageLedger()
    cfg = config(max_calls_per_day=2)
    def reserve(_):
        try:
            ledger.reserve('2026-10-22', cfg, None)
            return True
        except ProviderUnavailable:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(20)))
    assert sum(results) == 2
    ledger.reserve('2026-10-23', cfg, None)
    assert ledger.snapshot('2026-10-23')['calls'] == 1


def test_actual_extraction_schema_is_closed_required_nullable_and_not_mutated():
    from app.extraction_models import ExtractionDraft
    original = ExtractionDraft.model_json_schema()
    strict = strict_json_schema(original)
    assert set(strict['required']) == set(strict['properties'])
    assertion = strict['$defs']['SourceAssertion']
    assert set(assertion['required']) == set(assertion['properties'])
    assert {'actor', 'action', 'object', 'modality', 'verification_status'} <= set(assertion['required'])
    assert {'type': 'null'} in assertion['properties']['actor']['anyOf']
    assert 'default' not in assertion['properties']['actor']
    assert original['$defs']['SourceAssertion']['properties']['actor']['default'] is None
    assert 'assertions' not in original['required']

    def check(node):
        if isinstance(node, dict):
            assert 'default' not in node
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['required']) == set(node['properties'])
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)
    check(strict)

    def handler(request):
        sent = json.loads(request.content)['response_format']['json_schema']
        assert sent['strict'] is True
        assert sent['schema'] == strict
        return httpx.Response(200, json=envelope())
    provider(handler=handler).extract(MESSAGES, original)


def test_strict_schema_keeps_a_property_named_default_and_const_objects():
    original = {'type': 'object', 'properties': {
        'default': {'type': 'string', 'default': 'value'},
        'constant': {'const': {'default': 'part of literal'}}}}
    strict = strict_json_schema(original)
    assert strict['properties']['default'] == {'type': 'string'}
    assert strict['properties']['constant']['const'] == {'default': 'part of literal'}
    assert strict['required'] == ['default', 'constant']


def test_elapsed_deadline_is_checked_after_headers(monkeypatch):
    import app.llm_provider as module
    clock = [0.0]
    monkeypatch.setattr(module, 'perf_counter', lambda: clock[0])
    def handler(request):
        clock[0] = 2.0
        return httpx.Response(200, json=envelope())
    unavailable(provider(cfg=config(timeout_seconds=1), handler=handler), 'TIMEOUT')


def test_elapsed_deadline_is_checked_when_empty_stream_finishes(monkeypatch):
    import app.llm_provider as module
    clock = [0.0]
    monkeypatch.setattr(module, 'perf_counter', lambda: clock[0])
    class SlowEmptyStream(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] = 2.0
            return iter(())
    handler = lambda request: httpx.Response(200, stream=SlowEmptyStream())
    unavailable(provider(cfg=config(timeout_seconds=1), handler=handler), 'TIMEOUT')
