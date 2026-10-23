"""Grounded source assertions; a quoted assertion is not an established fact."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ImpactChannel


class ExtractionContract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SourceSpan(ExtractionContract):
    source_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=4000)

    @model_validator(mode='after')
    def bounds(self):
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError('Span bounds must match the quoted character count')
        return self


class SourceAssertion(ExtractionContract):
    id: str = Field(min_length=1, max_length=100)
    text: SourceSpan
    actor: SourceSpan | None = None
    action: SourceSpan | None = None
    object: SourceSpan | None = None
    modality: Literal['ASSERTED', 'NEGATED', 'POSSIBLE', 'UNKNOWN'] = 'UNKNOWN'
    verification_status: Literal['SOURCE_ASSERTION'] = 'SOURCE_ASSERTION'


class DateMention(ExtractionContract):
    span: SourceSpan
    iso_date: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$')
    role: Literal['EVENT', 'PUBLICATION', 'UNSPECIFIED'] = 'UNSPECIFIED'


class QuantityMention(ExtractionContract):
    span: SourceSpan
    value: SourceSpan
    unit: SourceSpan | None = None
    period: SourceSpan | None = None


class TargetMention(ExtractionContract):
    node_id: str = Field(min_length=1, max_length=100)
    span: SourceSpan
    assertion_id: str = Field(min_length=1, max_length=100)


class ChannelEvidence(ExtractionContract):
    channel: ImpactChannel
    span: SourceSpan


class ExtractionDraft(ExtractionContract):
    assertions: list[SourceAssertion] = Field(default_factory=list, max_length=12)
    dates: list[DateMention] = Field(default_factory=list, max_length=20)
    quantities: list[QuantityMention] = Field(default_factory=list, max_length=20)
    target_mentions: list[TargetMention] = Field(default_factory=list, max_length=20)
    channels: list[ImpactChannel] = Field(min_length=1, max_length=11)
    channel_evidence: list[ChannelEvidence] = Field(default_factory=list, max_length=22)
    knowledge_gaps: list[str] = Field(default_factory=list, max_length=20)


class ExtractionResult(ExtractionDraft):
    schema_version: Literal['0.3.0'] = '0.3.0'
    mode: Literal['RULES', 'LLM']
    review_status: Literal['NEEDS_REVIEW'] = 'NEEDS_REVIEW'
    source_id: str
    content_hash: str
    warnings: list[str] = Field(default_factory=list)
    provider_metadata: dict | None = None
