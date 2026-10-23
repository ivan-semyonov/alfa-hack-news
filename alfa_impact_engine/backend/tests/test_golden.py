import json
from pathlib import Path
from app.fixtures import COMPANIES, EDGES, EVENTS, NODES
from app.graph_engine import ExposureGraph


def test_seed_golden_cases():
    data = json.loads((Path(__file__).resolve().parents[2] / 'evaluation/golden_cases.json').read_text(encoding='utf-8'))
    assert len(data['cases']) >= 3
    companies = {c.id: c for c in COMPANIES}
    events = {e.id: e for e in EVENTS}
    graph = ExposureGraph(NODES, EDGES)
    for case in data['cases']:
        assert case['company_id'] in companies
        paths = graph.find_impact_paths(events[case['event_id']], case['company_id'])
        observed = 'POTENTIAL_EXPOSURE' if paths else 'NO_CONFIRMED_PATH'
        assert observed == case['expected_outcome'], case['id']
        if case['expected_path_status']:
            assert paths[0].path_status == case['expected_path_status'], case['id']
