"""Text pipeline v0.3 and the compatible v0.2 deterministic insight contract."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from .models import AnalysisResponse, Event, Evidence, ImpactChannel, ImpactPath
from .extraction_models import ExtractionResult


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class NewsInput(Contract):
    title: str = Field(default='', max_length=240)
    text: str = Field(min_length=20, max_length=20_000)
    source_url: HttpUrl | None = None
    is_synthetic: bool = False

    @model_validator(mode='after')
    def nonblank(self):
        try:
            self.text.encode('utf-8')
            self.title.encode('utf-8')
        except UnicodeEncodeError:
            raise ValueError('Text and title must contain valid Unicode') from None
        if len(self.text.strip()) < 20:
            raise ValueError('News text must contain at least 20 non-padding characters')
        if self.title.strip() and len(self.title.strip()) < 3:
            raise ValueError('A supplied title must contain at least 3 characters')
        return self


class NewsAnalysisRequest(NewsInput):
    company_id: str = Field(min_length=1, max_length=100)
    extraction_mode: Literal['RULES', 'LLM'] = 'RULES'


class NewsExtractionRequest(NewsInput):
    extraction_mode: Literal['RULES', 'LLM'] = 'RULES'


class TextMatch(Contract):
    quote: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class TargetMatch(TextMatch):
    node_id: str
    label: str


class ChannelMatch(TextMatch):
    channel: ImpactChannel


class SourceDocument(Contract):
    id: str
    title: str
    text: str
    source_url: str | None = None
    is_synthetic: bool


class NormalizationResult(Contract):
    schema_version: Literal['0.3.0'] = '0.3.0'
    mode: Literal['RULES_DEMO', 'LLM_EXTRACT'] = 'RULES_DEMO'
    status: Literal['NORMALIZED', 'NEEDS_REVIEW']
    content_hash: str
    source: SourceDocument
    event: Event
    extraction: ExtractionResult
    target_matches: list[TargetMatch] = Field(default_factory=list)
    channel_matches: list[ChannelMatch] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class InsightItem(Contract):
    statement: str = Field(min_length=1, max_length=2000)
    knowledge_status: Literal['HYPOTHESIS', 'UNVERIFIED'] = 'HYPOTHESIS'
    path_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class AlfaView(Contract):
    status: Literal['SUPPORTS', 'REFINES', 'CONTRADICTS', 'NOT_FOUND']
    statement: str = Field(min_length=1, max_length=2000)
    quote_ref: str | None = None

    @model_validator(mode='after')
    def source_required(self):
        if self.status != 'NOT_FOUND' and not self.quote_ref:
            raise ValueError('A bank view requires a source quote reference')
        if self.status == 'NOT_FOUND' and self.quote_ref is not None:
            raise ValueError('NOT_FOUND must not carry an invented quote reference')
        return self


class SuggestedAction(Contract):
    text: str = Field(min_length=1, max_length=2000)
    path_id: str | None = None
    data_gap: str | None = None

    @model_validator(mode='after')
    def grounded_action(self):
        if not self.path_id and not self.data_gap:
            raise ValueError('Action must refer to a path or an explicit data gap')
        return self


class ProductInsight(Contract):
    schema_version: Literal['0.2.0'] = '0.2.0'
    id: str
    company_id: str
    event_id: str
    mode: Literal['RULES_DEMO'] = 'RULES_DEMO'
    status: Literal['POTENTIAL_EXPOSURE', 'NEEDS_MORE_DATA']
    what_happened: str
    why_for_company: str
    risk_items: list[InsightItem] = Field(default_factory=list)
    opportunity_items: list[InsightItem] = Field(default_factory=list)
    impact_paths: list[ImpactPath] = Field(default_factory=list)
    alfa_view: AlfaView
    actions: list[SuggestedAction]
    knowledge_gaps: list[str]
    sources: list[Evidence]
    agent_run_id: None = None


class NewsAnalysisResponse(Contract):
    schema_version: Literal['0.3.0'] = '0.3.0'
    normalization: NormalizationResult
    analysis: AnalysisResponse
    insight: ProductInsight
