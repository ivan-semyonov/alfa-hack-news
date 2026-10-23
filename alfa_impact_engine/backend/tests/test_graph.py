from app.fixtures import NODES, EDGES, EVENTS
from app.graph_engine import ExposureGraph
from app.models import GraphEdge, GraphNode, Event


def test_mfg_hypothetical_impact_path():
    paths = ExposureGraph(NODES, EDGES).find_impact_paths(EVENTS[0], 'DEMO-MFG')
    assert len(paths) == 1
    assert paths[0].node_ids == ['RESOURCE_X', 'MFG_PROC', 'MFG_PRODUCT', 'MFG_KPI']
    assert paths[0].path_status == 'HYPOTHETICAL'
    assert paths[0].impact_level == 'UNKNOWN'


def test_other_company_no_path_on_same_news():
    assert ExposureGraph(NODES, EDGES).find_impact_paths(EVENTS[0], 'DEMO-SVC') == []


def test_unknown_news_target_no_path_not_zero_risk():
    assert ExposureGraph(NODES, EDGES).find_impact_paths(EVENTS[1], 'DEMO-MFG') == []


def test_payment_edges_do_not_imply_supplier_dependency():
    graph = ExposureGraph(NODES, EDGES)
    assert 'e_payment' not in {e for p in graph.find_impact_paths(EVENTS[0], 'DEMO-MFG') for e in p.edge_ids}


def test_no_propagation_across_related_to_edges():
    extra_node = GraphNode(id='NEW_PROC', type='PROCESS', label='Unrelated', company_id='DEMO-MFG')
    extra_kpi = GraphNode(id='NEW_KPI', type='KPI', label='Unrelated KPI', company_id='DEMO-MFG')
    edges = EDGES + [
        GraphEdge(id='unrelated', source_id='NEW_PROC', target_id='RESOURCE_X', relation='RELATED_TO', knowledge_status='FACT'),
        GraphEdge(id='unrelated_dep', source_id='NEW_KPI', target_id='NEW_PROC', relation='DEPENDS_ON', knowledge_status='FACT'),
    ]
    paths = ExposureGraph(NODES + [extra_node, extra_kpi], edges).find_impact_paths(EVENTS[0], 'DEMO-MFG')
    assert all('NEW_KPI' not in p.node_ids for p in paths)


def test_limit_steps_and_paths():
    g = ExposureGraph(NODES, EDGES)
    assert not g.find_impact_paths(EVENTS[0], 'DEMO-MFG', max_depth=2)
    assert len(g.find_impact_paths(EVENTS[0], 'DEMO-MFG', max_paths=1)) <= 1
