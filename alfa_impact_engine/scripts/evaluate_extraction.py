"""Network-free regression evaluation of grounded extraction and demo routes."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.extraction_models import ExtractionResult
from app.fixtures import COMPANIES, EDGES, NODES
from app.graph_engine import ExposureGraph
from app.news_demo import analyze_news
from app.product_models import NewsInput

DEFAULT_CASES = Path(__file__).resolve().parents[1] / 'evaluation' / 'extraction_cases.json'
COMPANY_INDEX = {company.id: company for company in COMPANIES}
GRAPH = ExposureGraph(NODES, EDGES)
LIMITATIONS = [
    'Developer-curated synthetic regression fixtures; not an independently expert-labeled golden set.',
    'RULES mode only; no provider, LLM quality, citation semantics or general news recall measured.',
    'Exact spans establish literal provenance, not the truth of a source assertion or a causal effect.',
]


def iter_source_spans(value: Any) -> Iterable[dict]:
    """Visit each returned SourceSpan, including nested assertion fields."""
    if isinstance(value, dict):
        if {'source_id', 'start', 'end', 'quote'} <= value.keys():
            yield value
        for child in value.values():
            yield from iter_source_spans(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_source_spans(child)


def span_is_grounded(span: dict, *, source_id: str, text: str) -> bool:
    """Independently audit identity, bounds and a literal source slice."""
    start, end, quote = span.get('start'), span.get('end'), span.get('quote')
    return (
        span.get('source_id') == source_id
        and type(start) is int and type(end) is int
        and 0 <= start < end <= len(text)
        and isinstance(quote, str)
        and text[start:end] == quote
    )


def _quote(field: dict | None) -> str | None:
    return field.get('quote') if isinstance(field, dict) else None


def _matches_quantity(actual: dict, expected: dict) -> bool:
    return all(_quote(actual.get(key)) == value for key, value in expected.items())


def evaluate_case(case: dict) -> dict:
    """Evaluate one text for every explicitly listed company in the fixture."""
    errors = []
    runs = []
    structure_checked = structure_valid = spans_checked = spans_valid = 0
    text = case['text']
    for company_id, expected_path in case['expected_paths'].items():
        structure_checked += 1
        run = {'company_id': company_id, 'path_exists': None}
        runs.append(run)
        try:
            company = COMPANY_INDEX[company_id]
            news = NewsInput(text=text, is_synthetic=True)
            response = analyze_news(news, company, GRAPH, extraction_mode='RULES')
            result = response.model_dump(mode='json')
            normalized, analysis, insight = result['normalization'], result['analysis'], result['insight']
            extraction = normalized['extraction']
            ExtractionResult.model_validate(extraction)
            structure_valid += 1
        except Exception as exc:
            errors.append(f'{company_id}:analysis_error:{type(exc).__name__}')
            continue
        source = normalized['source']
        if source['text'] != text:
            errors.append(f'{company_id}:source_text_changed')
        if extraction['source_id'] != source['id']:
            errors.append(f'{company_id}:extraction_source_mismatch')
        if extraction['content_hash'] != hashlib.sha256(text.encode('utf-8')).hexdigest():
            errors.append(f'{company_id}:content_hash_mismatch')
        if extraction['mode'] != 'RULES' or extraction['review_status'] != 'NEEDS_REVIEW':
            errors.append(f'{company_id}:unexpected_extraction_mode_or_review_status')
        if analysis['company']['id'] != company_id or insight['company_id'] != company_id:
            errors.append(f'{company_id}:company_scope_changed')
        if insight['alfa_view']['status'] != 'NOT_FOUND':
            errors.append(f'{company_id}:bank_view_without_corpus')
        path_exists = bool(analysis['paths'])
        run['path_exists'] = path_exists
        if path_exists is not expected_path:
            errors.append(f'{company_id}:expected_path_{str(expected_path).lower()}')
        if bool(insight['impact_paths']) != path_exists:
            errors.append(f'{company_id}:insight_path_mismatch')
        for path in analysis['paths']:
            if path['company_id'] != company_id or path['event_id'] != normalized['event']['id']:
                errors.append(f'{company_id}:path_scope_changed')
            if path['path_status'] != 'HYPOTHETICAL' or path['impact_level'] != 'UNKNOWN':
                errors.append(f'{company_id}:demo_path_evidence_promoted')
        if not set(case.get('required_channels', [])) <= set(extraction['channels']):
            errors.append(f'{company_id}:missing_required_channel')
        modalities = {assertion['modality'] for assertion in extraction['assertions']}
        if not extraction['assertions']:
            errors.append(f'{company_id}:missing_source_assertions')
        if not set(case.get('required_modalities', [])) <= modalities:
            errors.append(f'{company_id}:missing_required_modality')
        if any(item['verification_status'] != 'SOURCE_ASSERTION' for item in extraction['assertions']):
            errors.append(f'{company_id}:assertion_promoted_to_verified_fact')
        for expected in case.get('expected_dates', []):
            if not any(_quote(item['span']) == expected['quote'] and item['iso_date'] == expected['iso_date']
                       for item in extraction['dates']):
                errors.append(f'{company_id}:missing_expected_date')
        for expected in case.get('expected_quantities', []):
            if not any(_matches_quantity(item, expected) for item in extraction['quantities']):
                errors.append(f'{company_id}:missing_expected_quantity')
        for span in iter_source_spans(extraction):
            spans_checked += 1
            if span_is_grounded(span, source_id=source['id'], text=text):
                spans_valid += 1
            else:
                errors.append(f'{company_id}:ungrounded_source_span')
    return {'id': case['id'], 'passed': not errors, 'runs': runs, 'errors': errors,
            'structure_checked': structure_checked, 'structure_valid': structure_valid,
            'spans_checked': spans_checked, 'spans_valid': spans_valid}


def evaluate_cases(cases: list[dict]) -> dict:
    if not cases or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Cases must be nonempty and have unique IDs')
    for case in cases:
        if not isinstance(case.get('text'), str) or not isinstance(case.get('expected_paths'), dict):
            raise ValueError('Each case requires text and an expected_paths object')
        if not case['expected_paths'] or any(type(value) is not bool for value in case['expected_paths'].values()):
            raise ValueError('Each expected_paths entry must be a boolean')
    results = [evaluate_case(case) for case in cases]
    passed = sum(result['passed'] for result in results)
    return {
        'schema_version': '0.3.0', 'evaluation_kind': 'DEVELOPER_CURATED_REGRESSION', 'mode': 'RULES',
        'case_count': len(results), 'company_runs': sum(len(result['runs']) for result in results),
        'passed': passed, 'failed': len(results) - passed,
        'structural_validity': {'checked': sum(result['structure_checked'] for result in results),
                                'valid': sum(result['structure_valid'] for result in results)},
        'span_validity': {'checked': sum(result['spans_checked'] for result in results),
                          'valid': sum(result['spans_valid'] for result in results)},
        'cases': [{'id': result['id'], 'passed': result['passed'], 'runs': result['runs'], 'errors': result['errors']}
                  for result in results],
        'limitations': LIMITATIONS,
    }


def load_cases(path: Path = DEFAULT_CASES) -> list[dict]:
    if path.stat().st_size > 1_000_000:
        raise ValueError('Evaluation fixture exceeds the 1 MB limit')
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(document, dict) or document.get('evaluation_kind') != 'DEVELOPER_CURATED_REGRESSION':
        raise ValueError('Expected a developer-curated regression fixture document')
    cases = document.get('cases')
    if not isinstance(cases, list):
        raise ValueError('Fixture cases must be a list')
    return cases


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=DEFAULT_CASES)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate_cases(load_cases(args.cases))
        serialized = json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding='utf-8')
        else:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
            print(serialized, end='')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Error types are enough for diagnostics; avoid dumping source data.
        print(json.dumps({'valid': False, 'error': type(exc).__name__}), file=sys.stderr)
        return 2
    return 1 if report['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
