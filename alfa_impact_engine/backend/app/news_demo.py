"""Grounded extraction plus a deterministic, conditional graph insight."""
from .fixtures import EVIDENCES
from .graph_engine import ExposureGraph
from .models import AnalysisResponse, Company, Event, Evidence
from .product_models import (
    AlfaView, ChannelMatch, InsightItem, NewsAnalysisResponse, NewsInput,
    NormalizationResult, ProductInsight, SourceDocument, SuggestedAction, TargetMatch,
)
from .news_extraction import eligible_targets, extract_news


def normalize_news(news: NewsInput, *, extraction_mode='RULES', provider=None) -> NormalizationResult:
    """Record literal spans and resolve only the one declared synthetic alias.

    The whole article stays untrusted source text. Words are hints for review,
    not proof of a fact, its direction, actuality, or a company's exposure.
    """
    source, extraction = extract_news(news, mode=extraction_mode, provider=provider)
    fingerprint = source.id.removeprefix('news:')
    matches = [ChannelMatch(channel=m.channel, quote=m.span.quote, start=m.span.start, end=m.span.end)
               for m in extraction.channel_evidence]
    targets = [TargetMatch(node_id=m.node_id, label='Условный компонент X', quote=m.span.quote,
                           start=m.span.start, end=m.span.end) for m in extraction.target_mentions]
    target_ids = eligible_targets(extraction, source)
    warnings = extraction.warnings + [
        'Полнота, достоверность, актуальность и направление эффекта требуют ручной проверки.',
        'Сопоставление с графом ограничено учебным компонентом X; прочие объекты не исследованы.',
    ]
    if not target_ids:
        warnings.append('Оснований для запуска учебного маршрута недостаточно; нужен разбор новости.')
    return NormalizationResult(
        mode='LLM_EXTRACT' if extraction_mode == 'LLM' else 'RULES_DEMO',
        status='NEEDS_REVIEW', content_hash=extraction.content_hash, source=source, extraction=extraction,
        event=Event(id=f'event:{fingerprint}', title=source.title,
                    summary='Извлечены утверждения источника; истинность и смысл события требуют проверки.',
                    target_node_ids=target_ids,
                    channels=extraction.channels, source_ids=[source.id], is_synthetic=news.is_synthetic),
        target_matches=targets, channel_matches=matches, warnings=warnings,
    )


def analyze_news(news: NewsInput, company: Company, graph: ExposureGraph, *, extraction_mode='RULES', provider=None) -> NewsAnalysisResponse:
    normalized = normalize_news(news, extraction_mode=extraction_mode, provider=provider)
    paths = graph.find_impact_paths(normalized.event, company.id)
    source_gap = 'Смысл, достоверность, дата и направление изменения из текста не проверены.'
    gaps = [
        source_gap,
        'Применимость отраслевого шаблона к фактическим процессам компании не подтверждена.',
        'Объёмы запасов, условия договоров и заменители компонента неизвестны.',
        'Материалы аналитиков Альфа-Банка не загружены.',
    ]
    if not paths:
        gaps.insert(0, 'В текущем учебном графе допустимый маршрут не найден; это не означает отсутствия риска.')
    gaps.extend(normalized.extraction.knowledge_gaps)
    analysis = AnalysisResponse(
        schema_version='0.3.0', company=company, event=normalized.event, paths=paths,
        outcome='POTENTIAL_EXPOSURE' if paths else 'NO_CONFIRMED_PATH',
        facts_known=['Использована синтетическая модель компании; текст получен как непроверенный источник.'],
        knowledge_gaps=gaps,
        warning='Учебный граф; извлечение ' + normalized.extraction.mode + '. Инсайт составлен по шаблону; маршрут условный.',
    )
    source_ids = set(normalized.event.source_ids)
    source_ids.update(ev for path in paths for ev in path.evidence_ids)
    evidence = [ev for ev in EVIDENCES if ev.id in source_ids]
    evidence.append(Evidence(id=normalized.source.id, source_kind='NEWS',
                             source_reference=normalized.source.source_url or f'input:{normalized.source.id}',
                             statement='Непроверенный текст новости, переданный пользователем.',
                             is_synthetic=news.is_synthetic))
    risks = []
    if paths:
        risks.append(InsightItem(
            statement='Если изменение поставок действительно затрагивает используемый компанией компонент, '
                      'следует проверить возможное влияние на сборку, продукцию и выпуск. '
                      'Наличие зависимости и знак эффекта пока не подтверждены.',
            path_ids=[p.id for p in paths], source_ids=sorted(source_ids),
        ))
    actions = [SuggestedAction(text='Проверить исходную публикацию, дату и смысл описанного изменения.',
                               data_gap=source_gap)]
    if paths:
        actions.append(SuggestedAction(text='Уточнить у ответственного за закупки, используется ли компонент X '
                                       'и затрагивает ли событие действующие поставки.', path_id=paths[0].id))
    else:
        actions.append(SuggestedAction(text='Уточнить затронутый ресурс или процесс и дополнить модель компании.',
                                       data_gap=gaps[0]))
    insight = ProductInsight(
        id=f'insight:{company.id}:{normalized.event.id.removeprefix("event:")}',
        company_id=company.id, event_id=normalized.event.id,
        status='POTENTIAL_EXPOSURE' if paths else 'NEEDS_MORE_DATA',
        what_happened='Из текста выделены непроверенные утверждения источника. Заголовок: ' + normalized.source.title,
        why_for_company=(
            'В учебном шаблоне компании есть условная зависимость от компонента X; '
            'в одном фрагменте источника найдены признаки возможного изменения поставок.' if paths else
            'Извлечённых утверждений и текущего графа недостаточно для установления канала воздействия на компанию.'
        ),
        risk_items=risks, opportunity_items=[], impact_paths=paths,
        alfa_view=AlfaView(status='NOT_FOUND', statement='Аналитика Альфа-Банка не подключена; позиция банка не установлена.'),
        actions=actions, knowledge_gaps=gaps, sources=evidence,
    )
    return NewsAnalysisResponse(normalization=normalized, analysis=analysis, insight=insight)
