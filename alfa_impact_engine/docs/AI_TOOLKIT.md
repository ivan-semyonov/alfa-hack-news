# Утилиты Участника 1: AI-контракты и промпты

Версия 0.2.0. Этот пакет локально готовит промпты, экспортирует JSON Schema и проверяет структурированные ответы. Он не вызывает модель и не выполняет инструменты агента. Разрешённые идентификаторы моделей взяты из приложенного ТЗ §1.2; доступность endpoint и его технические model IDs ещё нужно согласовать.

Из корня проекта, после установки Python-зависимостей:

```powershell
.\.venv\Scripts\python.exe -m scripts.ai_toolkit taxonomy
.\.venv\Scripts\python.exe -m scripts.ai_toolkit schemas --output-dir contracts
.\.venv\Scripts\python.exe -m scripts.ai_toolkit prompt --task event --context data/synthetic/ai_examples/event_context.json --model "GLM-5.3-Flash" --output prompts/event.json
.\.venv\Scripts\python.exe -m scripts.ai_toolkit validate --task event --input data/synthetic/ai_examples/event_output.json --context data/synthetic/ai_examples/event_context.json
```

Команда `prompt` сохраняет транспортно-независимые `messages` с ролями `system` и `user`, точным именем модели и выходной схемой. Политика и схема находятся в `system`; новости, отчёты и другие данные кодируются JSON в `user`. Это граница для сборки промпта, а не гарантия защиты будущей модели от prompt injection. Не отправляйте реальный банковский контекст внешнему провайдеру до согласования доступа.

Задачи:

- `event`: контракт существующего `Event`; только разрешённые ID узлов/источников, минимум один источник, канал `OTHER` при неизвестной теме.
- `hypotheses`: до шести альтернатив; каждая имеет `HYPOTHESIS`, `UNVERIFIED` и список необходимых доказательств. Для версии без источников обязателен пробел данных.
- `insight`: текущий `ProductInsight`, с усиленной проверкой вложенных `ImpactPath` и `Evidence`. Режим контракта сейчас `RULES_DEMO`; результат ручной пробы модели остаётся черновиком и не становится запущенным агентом.

Контекст предоставляет приложение, а не автор новости. Он включает:

```json
{
  "company_id": "DEMO-MFG",
  "event_id": "event:example",
  "source_ids": ["source:article"],
  "target_node_ids": ["RESOURCE_X"],
  "paths": [],
  "evidence": [],
  "alfa_quote_refs": [],
  "news": {"text": "Недоверенный текст новости"}
}
```

`company_id` и `event_id` обязательны для гипотез и инсайта. Для `event` `event_id` можно заранее выдать приложением; если он задан, ответ обязан его сохранить. Если задан `is_synthetic`, ответ также должен его сохранить. `paths` содержит полные разрешённые пути; `evidence` — полные записи доказательств. Копирование пути с изменением `path_status`, статуса ребра, evidence ID или текста доказательства отклоняется. Ссылки рисков/возможностей и действий должны присутствовать в выходном инсайте. `data_gap` действия должен совпадать с элементом `knowledge_gaps`.

Без `alfa_quote_refs` допустим только `NOT_FOUND`. Непустой список разрешает лишь ссылки на заранее проверенные цитаты, а не проверяет соответствие утверждения цитате. Не формируйте этот реестр из ответа модели.

`validate` завершает процесс кодом 0 при успехе и 1 при ошибке; ошибки структуры не печатают входные значения. Проверяются JSON-структура, неизвестные поля, границы компании/события, допустимые ссылки и сохранение предоставленных путей/доказательств. Проверка не подтверждает истинность новости, семантическую обоснованность текста, чисел или цитат. Поля без ссылки допустимы у пунктов инсайта только с `UNVERIFIED`. Окончательный evidence audit остаётся задачей интеграции и QA.

Публичные Python-функции: `app.taxonomy.taxonomy_document()`, `app.ai_toolkit.output_schemas()`, `build_prompt(task, context, model)`, `validate_output(task, payload, context)`, `validate_model(model)`.
