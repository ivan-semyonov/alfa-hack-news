# Alfa Impact Engine — Участник 1, версия 0.3

Пакет product/solution/AI: текст → цитируемые утверждения источника → даты/числа/объекты → условный маршрут → инсайт. Компании и граф синтетические. По умолчанию работают локальные правила; добавлен явно включаемый HTTP-адаптер разрешённой LLM с проверкой её цитат. **Реальный провайдер не настроен и не проверен; банковские CSV, Alfa RAG и агент пока не подключены.**

Главные документы: [`docs/TECH_SPEC.md`](docs/TECH_SPEC.md) и [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

Для вашей роли начните с [`docs/PARTICIPANT_1.md`](docs/PARTICIPANT_1.md); команды AI-утилит и формат доверенного контекста — в [`docs/AI_TOOLKIT.md`](docs/AI_TOOLKIT.md).

Новое в 0.3: [`docs/NEWS_EXTRACTION.md`](docs/NEWS_EXTRACTION.md), настройка адаптера [`docs/LLM_PROVIDER.md`](docs/LLM_PROVIDER.md), регрессия [`docs/EVALUATION.md`](docs/EVALUATION.md). Утверждение источника остаётся непроверенным; `NEEDS_REVIEW` сохраняется в обоих режимах. Инсайт и граф обрабатываются детерминированно даже при извлечении через LLM.

### Windows: запустить подготовленное окружение

```powershell
.\scripts\run.ps1
```

Открыть http://127.0.0.1:8000. Если политика PowerShell запрещает запуск скрипта, можно выполнить сервер напрямую:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Создание окружения на другой машине с Python 3.12+:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
```

`backend/requirements-lock.txt` фиксирует весь проверенный Python 3.12/Windows набор, включая транзитивные и тестовые зависимости; для повторения этого окружения используйте его вместо `requirements-dev.txt`.

### Запустить утилиты

```powershell
.\.venv\Scripts\python.exe -m scripts.ai_toolkit taxonomy
.\.venv\Scripts\python.exe -m scripts.ai_toolkit schemas --output-dir contracts
.\.venv\Scripts\python.exe -m scripts.extract_news schema --output contracts/extraction.schema.json
.\.venv\Scripts\python.exe -m scripts.extract_news extract --news data/synthetic/news_dated.txt --synthetic --output extraction.json
.\.venv\Scripts\python.exe -m scripts.news_demo --company DEMO-MFG --input data/synthetic/news_supply.txt --synthetic --output analysis.json
.\.venv\Scripts\python.exe -m scripts.evaluate_extraction
.\.venv\Scripts\python.exe -m pytest
```

JSON-пример: [`data/synthetic/analysis_sample.json`](data/synthetic/analysis_sample.json). Для сравнения компаний повторите `news_demo` с `DEMO-SVC`. HTTP-вход: `POST /api/news/analyze` с полями `company_id`, `text`, опциональными `title`, `source_url`, `is_synthetic`, `extraction_mode` (`RULES` по умолчанию). Отдельный `POST /api/news/extract` возвращает утверждения, даты и величины без графа. `source_url` — только метаданные, загрузки URL нет. Запрос `LLM` без настроенного провайдера возвращает 503; скрытой замены на правила нет.

## Быстрый запуск

### Docker (если установлен)

```bash
docker compose up --build
```

Открыть http://localhost:8000/ для интерактивной демонстрации и http://localhost:8000/docs для OpenAPI.

### Локально (Python 3.12+)

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\\Scripts\\activate
pip install -r backend/requirements-dev.txt
cd backend
uvicorn app.main:app --reload
```

### Тесты

Из корня проекта:

```bash
pytest
```

### Пример API (структурированное синтетическое событие)

```bash
curl http://localhost:8000/api/demo-events
curl -X POST http://localhost:8000/api/analyze \
 -H 'Content-Type: application/json' \
 -d '{"company_id":"DEMO-MFG","event":{"id":"SYNTH-EVENT-X","title":"Учебное ограничение поставок компонента X","target_node_ids":["RESOURCE_X"],"channels":["SUPPLY"],"source_ids":["synthetic_news_1"]}}'
```

Повторить с `company_id: DEMO-SVC` — различная персонализация. Известные `TEMPLATE/INFERENCE` рёбра в первом примере остаются **гипотезами**, а не фактами.

## CSV preflight

Если появятся предоставленные организаторами файлы:

```bash
python scripts/inspect_csv.py path/to/*.csv
```

Скрипт определит тип по заголовкам и покажет метаданные, не выводя строки с потенциально чувствительными данными. **Импорт в PostgreSQL — следующий этап.**

Опциональный PostgreSQL (пока API не подключён к БД):

```bash
docker compose --profile storage up -d postgres
```

Пароль в compose — только локальный демонстрационный; в реальных окружениях использовать secrets.

## Архитектура этой итерации

```text
Synthetic company + untrusted news text
              |
       /api/news/analyze (RULES_DEMO)
              |
    literal matches + candidate Event
              |
     NetworkX ExposureGraph
              |
 typed reverse-dependency traversal
              |
 candidate ImpactPath + cautious insight + source refs + gaps
```

Исходный `/api/analyze` для структурированного Event также сохранён. Следующие этапы: банковские данные → полноценное извлечение фактов → Alfa lexical RAG → разрешённая LLM → агентный planner → сохранённый контекст и диалог. Текущий текстовый proof эти этапы не заменяет.

## Compliance

Основной файл кейса не включён в этот архив. Разрешённый перечень LLM и обязательный комплект материалов перечислены в TECH_SPEC. Ни реальные идентификаторы, ни внешние API-ключи в репозиторий не добавлять.
