"""Alfa Impact Engine workspace plus backwards compatible synthetic proof API."""
from pathlib import Path
import os
from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.trustedhost import TrustedHostMiddleware
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
from .product_api import router as product_router
from .product_api import principal, admin
from .app_config import get_service

app = FastAPI(title='Alfa Impact Engine', version='1.0.0',
              description='Authenticated research workspace. Legacy /api routes contain fixed synthetic fixtures only.')
app.include_router(product_router)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv('APP_ALLOWED_HOSTS', '127.0.0.1,localhost,[::1],testserver').split(','))
GRAPH = ExposureGraph(NODES, EDGES)
COMPANY_INDEX = {company.id: company for company in COMPANIES}
STATIC_INDEX = Path(__file__).resolve().parents[2] / 'frontend' / 'index.html'


@app.middleware('http')
async def boundaries(request, call_next):
    if request.method in ('POST', 'PUT', 'PATCH'):
        length = request.headers.get('content-length', '0')
        if not length.isdecimal() or int(length) > 16_000_000:
            return JSONResponse(status_code=413, content={'detail': 'Запрос превышает 16 МБ.'})
        # Read at most the bound even when Content-Length is absent or incorrect.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16_000_000:
                return JSONResponse(status_code=413, content={'detail': 'Запрос превышает 16 МБ.'})
        request._body = bytes(body)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api/v1'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not echo news, keys, or malformed Unicode in validation responses.
    return JSONResponse(status_code=422, content={'detail': [
        {'loc': list(error['loc']), 'msg': error['msg'], 'type': error['type']}
        for error in exc.errors()
    ]})


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(STATIC_INDEX.with_name('product.html'))


@app.get('/assets/{name}', include_in_schema=False)
def asset(name: str):
    if name not in ('product.js', 'product.css', 'legacy.js'):
        raise HTTPException(404)
    return FileResponse(STATIC_INDEX.with_name(name))


@app.get('/legacy', include_in_schema=False)
def legacy():
    return FileResponse(STATIC_INDEX)


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


def legacy_llm_guard(request, mode):
    if mode != 'LLM':
        return
    if not ProviderConfig.from_env().enabled:
        raise HTTPException(503, 'LLM DISABLED. Настройте модель в защищённой рабочей области.')
    user = principal(request, get_service(request))
    admin(user)


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
def normalize_text(news: NewsExtractionRequest, request: Request):
    legacy_llm_guard(request, news.extraction_mode)
    return extraction_operation(lambda: normalize_news(news, extraction_mode=news.extraction_mode))


@app.post('/api/news/extract', response_model=ExtractionResult)
def extract_text(news: NewsExtractionRequest, request: Request):
    legacy_llm_guard(request, news.extraction_mode)
    return extraction_operation(lambda: extract_news(news, mode=news.extraction_mode)[1])


@app.post('/api/news/analyze', response_model=NewsAnalysisResponse)
def analyze_text(req: NewsAnalysisRequest, request: Request):
    legacy_llm_guard(request, req.extraction_mode)
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
