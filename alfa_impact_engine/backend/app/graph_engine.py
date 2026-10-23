"""Evidence-aware, typed REVERSE dependency propagation.

Deliberately *does not* propagate via payment, ownership, RELATED_TO or co-location.
Nothing here estimates actual financial losses, probabilities or causality.
"""
import hashlib
import networkx as nx
from .models import GraphNode, GraphEdge, KnowledgeStatus, ImpactPath, Event

PROPAGATING_RELS = {'REQUIRES', 'DEPENDS_ON', 'CONTRIBUTES_TO'}
ALLOWED_SUCCESSORS = {'PROCESS', 'PRODUCT', 'KPI'}


class ExposureGraph:
    def __init__(self, nodes: list[GraphNode], edges: list[GraphEdge]):
        self.g = nx.DiGraph()
        for node in nodes:
            self.g.add_node(node.id, payload=node)
        for edge in edges:
            if edge.source_id not in self.g or edge.target_id not in self.g:
                raise ValueError(f'Edge {edge.id} references missing node')
            if self.g.has_edge(edge.source_id, edge.target_id):
                raise ValueError('Starter engine needs unique directed pairs; use MultiDiGraph later')
            self.g.add_edge(edge.source_id, edge.target_id, payload=edge)

    def company_subgraph(self, company_id: str):
        chosen = {node_id for node_id, info in self.g.nodes(data=True)
                  if info['payload'].company_id in (None, company_id)}
        g = self.g.subgraph(chosen)
        return {
            'nodes': [g.nodes[x]['payload'].model_dump(mode='json') for x in g.nodes],
            'edges': [g.edges[a, b]['payload'].model_dump(mode='json') for a, b in g.edges],
        }

    def find_impact_paths(self, event: Event, company_id: str, *, max_depth: int = 5,
                          max_paths: int = 10) -> list[ImpactPath]:
        results: list[ImpactPath] = []
        for target in event.target_node_ids:
            if target not in self.g:
                continue
            stack = [(target, [target], [])]
            while stack and len(results) < max_paths:
                current, node_ids, path_edges = stack.pop()
                if len(path_edges) >= max_depth:
                    continue
                for parent in self.g.predecessors(current):
                    if parent in node_ids:
                        continue
                    edge: GraphEdge = self.g.edges[parent, current]['payload']
                    parent_node: GraphNode = self.g.nodes[parent]['payload']
                    if edge.relation.value not in PROPAGATING_RELS:
                        continue
                    if parent_node.company_id != company_id:
                        continue  # never cross a company's own node boundary
                    if parent_node.type.value not in ALLOWED_SUCCESSORS:
                        continue
                    if edge.knowledge_status is KnowledgeStatus.REJECTED:
                        continue
                    candidate_nodes = node_ids + [parent]
                    candidate_edges = path_edges + [edge]
                    if parent_node.type.value == 'KPI':
                        statuses = [x.knowledge_status for x in candidate_edges]
                        if all(s is KnowledgeStatus.FACT for s in statuses):
                            grade = 'VERIFIED'
                        elif any(s in (KnowledgeStatus.TEMPLATE, KnowledgeStatus.HYPOTHESIS) for s in statuses):
                            grade = 'HYPOTHETICAL'
                        else:
                            grade = 'MIXED'
                        raw_id = event.id + '/' + company_id + '/' + '/'.join(candidate_nodes)
                        path_id = hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:16]
                        evidence_ids = sorted({ev for e in candidate_edges for ev in e.evidence_ids})
                        results.append(ImpactPath(
                            id=path_id, event_id=event.id, company_id=company_id,
                            node_ids=candidate_nodes,
                            edge_ids=[x.id for x in candidate_edges],
                            edge_statuses=statuses,
                            evidence_ids=evidence_ids,
                            path_status=grade,
                            impact_level='UNKNOWN',  # deliberately no numerical score
                        ))
                    else:
                        stack.append((parent, candidate_nodes, candidate_edges))
        return results
