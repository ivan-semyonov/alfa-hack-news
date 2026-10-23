"""Public inputs of the complete research workspace, schema 1.0.0."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from .product_models import NewsInput


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @field_validator('*', mode='before')
    @classmethod
    def valid_unicode(cls, value):
        if isinstance(value, str):
            try:
                value.encode('utf-8')
            except UnicodeError:
                raise ValueError('Недопустимый Unicode.') from None
        return value


class LoginInput(Input):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class AnalyzeInput(NewsInput):
    company_id: str = Field(min_length=1, max_length=100)
    mode: Literal['RULES', 'LLM'] = 'RULES'
    role: Literal['EXECUTIVE', 'CEO', 'CFO', 'TREASURER'] = 'EXECUTIVE'
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)

    @field_validator('company_id', 'idempotency_key')
    @classmethod
    def safe_identifier(cls, value):
        if value is not None:
            try:
                value.encode('utf-8')
            except UnicodeError:
                raise ValueError('Недопустимый идентификатор.') from None
            if any(ord(c) < 32 for c in value):
                raise ValueError('Недопустимый идентификатор.')
        return value


class QuestionInput(Input):
    question: str = Field(min_length=3, max_length=2000)


class FeedbackInput(Input):
    category: Literal['USEFUL', 'NOT_RELEVANT', 'WRONG_CLAIM', 'MISSING_DATA']
    note: str = Field(default='', max_length=2000)


class CompanyInput(Input):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    industry_code: str | None = Field(default=None, max_length=30)
    industry_label: str | None = Field(default=None, max_length=300)
    region: str | None = Field(default=None, max_length=200)
    bank_loan_mark: bool | None = None
    is_synthetic: bool = False


class DocumentInput(Input):
    title: str = Field(min_length=3, max_length=240)
    kind: Literal['ALFA_REPORT', 'PUBLIC', 'SYNTHETIC'] = 'ALFA_REPORT'
    published_at: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$')
    author: str = Field(default='', max_length=200)
    source_url: HttpUrl | None = None
    text: str | None = Field(default=None, min_length=20, max_length=1_000_000)
    pdf_base64: str | None = Field(default=None, max_length=14_000_000)

    @field_validator('published_at')
    @classmethod
    def valid_date(cls, value):
        if value:
            from datetime import date
            date.fromisoformat(value)
        return value


class CsvInput(Input):
    filename: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=5_000_000)
    is_synthetic: bool = False
    payment_period: str | None = Field(default=None, max_length=100)
    payment_unit: str | None = Field(default=None, max_length=50)


class ProviderInput(Input):
    enabled: bool = False
    base_url: str = Field(default='', max_length=2048)
    model: str = Field(default='', max_length=100)
    api_model: str = Field(default='', max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_key: bool = False
    response_format: Literal['json_schema', 'json_object'] = 'json_schema'
    timeout_seconds: float = Field(default=30, ge=1, le=60)
    max_output_tokens: int = Field(default=3000, ge=128, le=4000)
    max_calls_per_day: int = Field(default=50, ge=1, le=1000)
    input_rub_per_1m: str | None = Field(default=None, max_length=30)
    output_rub_per_1m: str | None = Field(default=None, max_length=30)
    daily_budget_rub: str = Field(default='500', max_length=30)
