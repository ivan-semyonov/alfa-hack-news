"""The evaluation must accept the pack and also detect a wrong expectation."""
import copy

from scripts.evaluate_extraction import evaluate_case, evaluate_cases, load_cases, span_is_grounded


def test_developer_regression_pack_passes_in_rules_mode():
    cases = load_cases()
    report = evaluate_cases(cases)
    assert report['case_count'] >= 12
    assert report['failed'] == 0, report['cases']
    assert report['company_runs'] == report['case_count'] * 2
    assert report['structural_validity']['valid'] == report['company_runs']
    assert report['span_validity']['checked'] > 0
    assert report['span_validity']['valid'] == report['span_validity']['checked']


def test_evaluator_detects_an_intentionally_wrong_route_expectation():
    case = copy.deepcopy(load_cases()[0])
    case['expected_paths']['DEMO-MFG'] = False
    result = evaluate_case(case)
    assert result['passed'] is False
    assert 'DEMO-MFG:expected_path_false' in result['errors']


def test_span_audit_rejects_changed_quote_and_wrong_unicode_offset():
    source_text = '⚙️ Компонент Х'
    start = source_text.index('Компонент')
    span = {'source_id': 'news:example', 'start': start, 'end': len(source_text),
            'quote': source_text[start:]}
    assert span_is_grounded(span, source_id='news:example', text=source_text)
    altered = dict(span, quote='Выдуманный ресурс')
    assert not span_is_grounded(altered, source_id='news:example', text=source_text)
    assert not span_is_grounded(dict(span, start=start + 1), source_id='news:example', text=source_text)
    assert not span_is_grounded(span, source_id='news:other', text=source_text)
