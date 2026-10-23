"""Versioned contracts of the starter slice. Not an LLM output schema yet."""
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class KnowledgeStatus(str, Enum):
    FACT = 'FACT'
    TEMPLATE = 'TEMPLATE'
    INFERENCE = 'INFERENCE'
    HYPOTHESIS = 'HYPOTHESIS'
    REJECTED = 'REJECTED'


class NodeType(str, Enum):
    COMPANY = 'COMPANY'
    INDUSTRY = 'INDUSTRY'
    PROCESS = 'PROCESS'
    PRODUCT = 'PRODUCT'
    RESOURCE = 'RESOURCE'
    COMMODITY = 'COMMODITY'
    TECHNOLOGY = 'TECHNOLOGY'
    LOCATION = 'LOCATION'
    FINANCIAL_INSTRUMENT = 'FINANCIAL_INSTRUMENT'
    KPI = 'KPI'
    EVENT = 'EVENT'


class RelationType(str, Enum):
    OPERATES_IN = 'OPERATES_IN'
    OWNS_PROCESS = 'OWNS_PROCESS'
    PRODUCES = 'PRODUCES'
    REQUIRES = 'REQUIRES'
    DEPENDS_ON = 'DEPENDS_ON'
    USES = 'USES'
    HAS_PAYMENT_TO = 'HAS_PAYMENT_TO'
    LOCATED_IN = 'LOCATED_IN'
    HAS_FINANCIAL_PRODUCT = 'HAS_FINANCIAL_PRODUCT'
    PART_OF_GROUP = 'PART_OF_GROUP'
    CONTRIBUTES_TO = 'CONTRIBUTES_TO'
    AFFECTS = 'AFFECTS'
    RELATED_TO = 'RELATED_TO'


class ImpactChannel(str, Enum):
    SUPPLY = 'SUPPLY'
    DEMAND = 'DEMAND'
    FINANCE = 'FINANCE'
    REGULATION = 'REGULATION'
    TECHNOLOGY = 'TECHNOLOGY'
    LABOR = 'LABOR'
    INFRASTRUCTURE = 'INFRASTRUCTURE'
    COMPETITION = 'COMPETITION'
    GEOGRAPHY = 'GEOGRAPHY'
    MACRO = 'MACRO'
    OTHER = 'OTHER'


class Company(BaseModel):
    id: str = Field(min_length=1)
    name: str
    industry_code: str | None = None
    industry_label: str | None = None
    region: str | None = None
    bank_loan_mark: bool | None = None
    is_synthetic: bool = True


class Evidence(BaseModel):
    id: str
    source_kind: str
    source_reference: str
    statement: str
    is_synthetic: bool = True


class GraphNode(BaseModel):
    id: str
    type: NodeType
    label: str
    company_id: str | None = None
    knowledge_status: KnowledgeStatus = KnowledgeStatus.HYPOTHESIS
    evidence_ids: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    relation: RelationType
    knowledge_status: KnowledgeStatus
    evidence_ids: list[str] = Field(default_factory=list)
    dependency_strength: float | None = Field(default=None, ge=0, le=1)


class Event(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=3)
    summary: str = ''
    target_node_ids: list[str] = Field(default_factory=list)
    channels: list[ImpactChannel] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    is_synthetic: bool = True


class AnalysisRequest(BaseModel):
    company_id: str
    event: Event


class ImpactPath(BaseModel):
    id: str
    company_id: str
    event_id: str
    node_ids: list[str]
    edge_ids: list[str]
    edge_statuses: list[KnowledgeStatus]
    evidence_ids: list[str]
    path_status: str  # VERIFIED / MIXED / HYPOTHETICAL
    impact_level: str = 'UNKNOWN'
    disclaimer: str = 'Маршрут выявляет потенциальный канал, но не доказывает причинный эффект.'


class AnalysisResponse(BaseModel):
    schema_version: str = '0.1.0'
    company: Company
    event: Event
    paths: list[ImpactPath]
    outcome: str  # POTENTIAL_EXPOSURE / NO_CONFIRMED_PATH
    facts_known: list[str] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    warning: str = 'Демонстрация на полностью синтетических данных; это не финансовый прогноз.'
    model_config = ConfigDict(use_enum_values=True)
