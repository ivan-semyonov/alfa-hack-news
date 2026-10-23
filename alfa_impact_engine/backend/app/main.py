"""Alpha skeleton: deterministic synthetic demonstration, not finished hackathon app."""
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from .fixtures import COMPANIES, NODES, EDGES, EVENTS
from .graph_engine import ExposureGraph
from .models import AnalysisRequest, AnalysisResponse, Company, Event
from .news_demo import analyze_news, normalize_news
from .news_extraction import ExtractionValidationError, extract_news
from .extraction_models import ExtractionResult
from .llm_provider import ProviderConfig, ProviderConfigurationError, ProviderUnavailable
from .product_models import NewsExtractionRequest, NewsAnalysisRequest, NewsAnalysisResponse, NormalizationResult
from .taxonomy import taxonomy_document

app = FastAPI(title='Alfa Impact Engine — grounded extraction proof', version='0.3.0',
              description='Synthetic graph; grounded source assertions via rules or an explicitly configured LLM adapter. No bank CSV or Alfa RAG.')
GRAPH = ExposureGraph(NODES, EDGES)
COMPANY_INDEX = {company.id: company for company in COMPANIES}
STATIC_INDEX = Path(__file__).resolve().parents[2] / 'frontend' / 'index.html'


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not echo news, keys, or malformed Unicode in validation responses.
    return JSONResponse(status_code=422, content={'detail': [
        {'loc': list(error['loc']), 'msg': error['msg'], 'type': error['type']}
        for error in exc.errors()
    ]})


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(STATIC_INDEX) if STATIC_INDEX.is_file() else {'docs': '/docs'}


@app.get('/api/health')
def health():
    try:
        provider_status = ProviderConfig.from_env().status()
    except ProviderConfigurationError:
        provider_status = {'enabled': False, 'configured': False, 'connection_verified': False,
                           'model': None, 'error': 'INVALID_CONFIGURATION'}
    return {'status': 'ok', 'phase': 'M0-grounded-extraction', 'data': 'synthetic-only',
            'llm_connected': False, 'normalization_mode': 'RULES_DEMO', 'schema_version': '0.3.0',
            'extraction': provider_status}


def extraction_operation(operation):
    try:
        return operation()
    except (ProviderUnavailable, ProviderConfigurationError) as exc:
        raise HTTPException(status_code=503, detail='Модель недоступна (' + exc.code + '). '
                            'Проверьте конфигурацию или явно выберите локальные правила.') from None
    except ExtractionValidationError:
        raise HTTPException(status_code=503, detail='Ответ модели не прошёл проверку структуры и цитат '
                            '(INVALID_MODEL_EXTRACTION). Выберите локальные правила или повторите позже.') from None


@app.get('/api/taxonomy')
def taxonomy():
    return taxonomy_document()


@app.get('/api/companies', response_model=list[Company])
def list_companies():
    return COMPANIES


@app.get('/api/companies/{company_id}', response_model=Company)
def get_company(company_id: str):
    if company_id not in COMPANY_INDEX:
        raise HTTPException(status_code=404, detail='Company not found')
    return COMPANY_INDEX[company_id]


@app.get('/api/companies/{company_id}/graph')
def get_graph(company_id: str):
    if company_id not in COMPANY_INDEX:
        raise HTTPException(status_code=404, detail='Company not found')
    return GRAPH.company_subgraph(company_id)


@app.get('/api/demo-events', response_model=list[Event])
def demo_events():
    return EVENTS


@app.post('/api/news/normalize', response_model=NormalizationResult)
def normalize_text(news: NewsExtractionRequest):
    return extraction_operation(lambda: normalize_news(news, extraction_mode=news.extraction_mode))


@app.post('/api/news/extract', response_model=ExtractionResult)
def extract_text(news: NewsExtractionRequest):
    return extraction_operation(lambda: extract_news(news, mode=news.extraction_mode)[1])


@app.post('/api/news/analyze', response_model=NewsAnalysisResponse)
def analyze_text(req: NewsAnalysisRequest):
    company = COMPANY_INDEX.get(req.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail='Company not found')
    return extraction_operation(lambda: analyze_news(req, company, GRAPH, extraction_mode=req.extraction_mode))


@app.post('/api/analyze', response_model=AnalysisResponse)
def analyze(req: AnalysisRequest):
    company = COMPANY_INDEX.get(req.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail='Company not found')
    paths = GRAPH.find_impact_paths(req.event, company.id)
    return AnalysisResponse(
        company=company, event=req.event, paths=paths,
        outcome='POTENTIAL_EXPOSURE' if paths else 'NO_CONFIRMED_PATH',
        facts_known=['Использована только синтетическая учебная модель.'],
        knowledge_gaps=(
            ['Маршрут построен на типовых/гипотетических зависимостях; нужна проверка реальных процессов.']
            if paths else ['Нет допустимого доказательного маршрута в текущем графе; это не доказательство отсутствия риска.']
        ),
    )
