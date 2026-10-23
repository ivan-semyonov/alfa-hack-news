
    'use strict';
    const $ = selector => document.querySelector(selector);
    const ui = {company: $('#company'), profile: $('#company-profile'), companyError: $('#company-error'), retry: $('#retry-companies'), form: $('#news-form'), headline: $('#news-headline'), text: $('#news-text'), url: $('#source-url'), synthetic: $('#synthetic-news'), mode: $('#extraction-mode'), llmOption: null, config: $('#extraction-config'), disclosure: $('#mode-disclosure'), modeLabel: $('#mode-label'), refreshProvider: $('#refresh-provider'), count: $('#news-count'), submit: $('#analyse'), submitLabel: $('#analyse-label'), error: $('#form-error'), output: $('#output'), card: $('#result-card'), tools: $('#result-tools'), resultId: $('#result-id')};
    // Hold the actual options instead of depending on parsed option IDs.
    const localModeOption = new Option('Локальные правила','RULES',true,true);
    ui.llmOption = new Option('Настроенная LLM · недоступно','LLM');
    ui.llmOption.id = 'llm-option'; ui.llmOption.disabled = true;
    ui.mode.replaceChildren(localModeOption,ui.llmOption);
    const state = {companies: new Map(), graphs: new Map(), loaded: false, busy: false, revision: 0, controller: null, lastResult: null, providerConfigured: false, providerModel: null, healthRevision: 0};
    const channels = {SUPPLY:'Поставки',DEMAND:'Спрос',FINANCE:'Финансирование',REGULATION:'Регулирование',TECHNOLOGY:'Технологии',LABOR:'Рынок труда',INFRASTRUCTURE:'Инфраструктура',COMPETITION:'Конкуренция',GEOGRAPHY:'География',MACRO:'Макроэкономика',OTHER:'Другая тема'};
    const knowledge = {FACT:'Факт в источнике',TEMPLATE:'Отраслевой шаблон',INFERENCE:'Алгоритмический вывод',HYPOTHESIS:'Гипотеза',UNVERIFIED:'Не проверено',REJECTED:'Опровергнуто'};
    const nodeTypes = {COMPANY:'Компания',INDUSTRY:'Отрасль',PROCESS:'Процесс',PRODUCT:'Продукт',RESOURCE:'Ресурс',COMMODITY:'Сырьё',TECHNOLOGY:'Технология',LOCATION:'Локация',FINANCIAL_INSTRUMENT:'Финансовый инструмент',KPI:'Показатель',EVENT:'Событие'};
    const relations = {REQUIRES:'зависимость от ресурса',DEPENDS_ON:'зависимость',CONTRIBUTES_TO:'вклад в показатель'};
    const pathStatuses = {VERIFIED:'Звенья подтверждены',MIXED:'Смешанная доказательность',HYPOTHETICAL:'Гипотетический маршрут'};
    const examples = {
      supply: {title:'Учебное ограничение поставок компонента X',text:'Вымышленная новость: поставки компонента X ограничены. Производителям, использующим этот компонент, потребуется проверить запасы и доступность альтернатив. Дата возобновления поставок неизвестна.'},
      unrelated: {title:'В городе открылась художественная выставка',text:'Вымышленная новость: в городском музее открылась выставка акварели. Посетителям доступны работы местных художников и экскурсии. Сведений о производстве и закупках компаний в сообщении нет.'},
      finance: {title:'Учебное повышение ключевой ставки',text:'Вымышленная новость: центральный банк повысил ключевую ставку. Банки пересматривают условия новых кредитов. Условия действующих договоров конкретных компаний и размер их долга не раскрыты.'},
      negated: {title:'Учебная проверка отрицания',text:'Поставщик не ограничил поставки компонента X. Сообщение о перебоях не подтверждено. Это вымышленная новость для проверки отрицания события.'},
      dated: {title:'Учебная новость с датой и количеством',text:'22 октября 2026 года поставщик ограничил поставки компонента X до 120 тонн в месяц. Вымышленное сообщение используется для проверки точных цитат, даты, единицы и периода.'}
    };
    function el(tag, className, value) {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (value !== undefined && value !== null) element.textContent = String(value);
      return element;
    }
    function badge(text, kind = 'gray') { return el('span', 'badge ' + kind, text); }
    function list(items, className = '') {
      const target = el('ul', className);
      for (const item of items || []) target.append(el('li', '', item));
      return target;
    }
    function section(title, number) {
      const root = el('section', 'section'), heading = el('div', 'section-title');
      heading.append(el('span', 'section-index', number), el('h3', '', title)); root.append(heading); return root;
    }
    function safeLink(value, label) {
      try {
        const parsed = new URL(value);
        if (!['http:', 'https:'].includes(parsed.protocol)) return el('span', '', value);
        const a = el('a', '', label || value); a.href = parsed.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
      } catch (_) { return el('span', '', value); }
    }
    function errorMessage(detail) {
      if (Array.isArray(detail)) return detail.map(item => {
        const location = Array.isArray(item.loc) ? item.loc.filter(x => x !== 'body').join('.') : '';
        return (location ? location + ': ' : '') + (item.msg || 'Некорректное значение');
      }).join('\n');
      return typeof detail === 'string' ? detail : 'Сервис не смог обработать запрос.';
    }
    async function requestJson(url, options = {}) {
      let response;
      try { response = await fetch(url, options); }
      catch (error) { if (error.name === 'AbortError') throw error; throw new Error('Нет соединения с сервером. Проверьте, что сервис запущен, и повторите запрос.'); }
      let data;
      try { data = await response.json(); }
      catch (_) { throw new Error('Сервер вернул ответ в неожиданном формате (HTTP ' + response.status + ').'); }
      if (!response.ok) {
        if (response.status === 503 || (response.status >= 500 && url === '/api/news/analyze' && ui.mode.value === 'LLM')) { const failure = new Error('Извлечение через LLM недоступно: запрос не завершён. Можно проверить настройку провайдера или явно выбрать локальные правила. Автоматическая замена режима не выполнялась.'); failure.status = 503; throw failure; }
        throw new Error(errorMessage(data.detail) + ' (HTTP ' + response.status + ')');
      }
      return data;
    }
    function modeDisclosure() {
      const external = ui.mode.value === 'LLM';
      ui.disclosure.classList.toggle('external',external);
      ui.disclosure.textContent = external ? 'При нажатии «Исследовать влияние» текст новости будет отправлен настроенному провайдеру для извлечения. Профиль компании не отправляется. Связь с провайдером пока не проверена.' + (!state.providerConfigured ? ' Выбранная LLM сейчас недоступна: обновите конфигурацию или выберите локальные правила.' : '') : 'Текст обрабатывается локально. Внешнему провайдеру ничего не отправляется.';
      ui.modeLabel.textContent = external ? 'Извлечение с LLM' : 'Локальное извлечение';
    }
    async function loadProviderConfiguration() {
      const revision = ++state.healthRevision;
      ui.refreshProvider.disabled = true;
      ui.config.textContent = 'Проверяем конфигурацию провайдера…';
      try {
        const health = await requestJson('/api/health');
        if (revision !== state.healthRevision) return;
        const provider = health.extraction || {};
        state.providerConfigured = provider.enabled === true && provider.configured === true;
        state.providerModel = typeof provider.model === 'string' ? provider.model : null;
        if (ui.llmOption) {
          ui.llmOption.disabled = !state.providerConfigured;
          ui.llmOption.textContent = state.providerConfigured ? 'Настроенная LLM' : 'Настроенная LLM · недоступно';
        }
        ui.config.textContent = state.providerConfigured ? 'Конфигурация LLM есть' + (state.providerModel ? ' · ' + state.providerModel : '') + '. Связь не проверена.' : 'LLM не включена или конфигурация неполна. Доступны локальные правила.';
      } catch (_) {
        if (revision !== state.healthRevision) return;
        state.providerConfigured = false;
        if (ui.llmOption) { ui.llmOption.disabled = true; ui.llmOption.textContent = 'Настроенная LLM · недоступно'; }
        ui.config.textContent = 'Конфигурацию провайдера проверить не удалось. Доступны локальные правила.';
      } finally { if (revision === state.healthRevision) { ui.refreshProvider.disabled = false; modeDisclosure(); controls(); } }
    }
    function controls() {
      ui.count.textContent = ui.text.value.length.toLocaleString('ru-RU') + ' / 20 000';
      ui.submit.disabled = !state.loaded || state.busy || ui.text.value.trim().length < 20 || (ui.mode.value === 'LLM' && !state.providerConfigured);
      ui.submitLabel.textContent = state.busy ? 'Исследуем зависимости…' : 'Исследовать влияние';
      ui.card.setAttribute('aria-busy', String(state.busy));
    }
    function emptyState(loading = false) {
      const empty = el('div', 'empty'), content = el('div', 'empty-content');
      if (loading) content.append(el('span', 'loading-marker'), el('h3', '', 'Извлекаем сведения и проверяем зависимости'), el('p', '', ui.mode.value === 'LLM' ? 'Текст отправлен настроенному провайдеру для извлечения. Затем учебный граф проверит допустимые маршруты для выбранной компании.' : 'Локально выделяем утверждения с цитатами, затем ищем допустимые маршруты в графе выбранной компании.'));
      else {
        const visual = el('div', 'empty-visual'); visual.setAttribute('aria-hidden', 'true');
        visual.append(el('span', 'visual-node', '≡'), el('span', 'visual-line'), el('span', 'visual-node middle', '↗'), el('span', 'visual-line'), el('span', 'visual-node', '⌑'));
        content.append(visual, el('h3', '', 'Начните с одного события'), el('p', '', 'Выберите компанию и вставьте новость. Здесь появится возможный маршрут воздействия с источниками, статусами связей и следующими шагами.'), el('p', 'empty-hint', 'Для первого запуска попробуйте «Поставки компонента X», а затем смените компанию.'));
      }
      empty.append(content); ui.output.replaceChildren(empty);
    }
    function invalidate() {
      state.revision += 1;
      if (state.controller) state.controller.abort();
      state.controller = null; state.busy = false; state.lastResult = null;
      ui.tools.hidden = true; ui.resultId.hidden = true; ui.error.hidden = true;
      $('#llm-unavailable')?.remove();
      emptyState(); controls();
    }
    function renderProfile(company) {
      ui.profile.replaceChildren();
      if (!company) { ui.profile.hidden = true; return; }
      const dl = el('dl');
      const rows = [['Идентификатор',company.id],['Отрасль',(company.industry_code ? company.industry_code + ' · ' : '') + (company.industry_label || 'Нет сведений')],['Регион',company.region || 'Нет сведений'],['Кредитный продукт',company.bank_loan_mark === true ? 'Учебный признак: есть' : company.bank_loan_mark === false ? 'Учебный признак: нет' : 'Нет сведений']];
      for (const [key,value] of rows) dl.append(el('dt','',key), el('dd','',value));
      ui.profile.append(dl, el('p','profile-note','Доля рынка, текущий долг и реальные поставщики неизвестны. Отраслевой шаблон требует подтверждения для конкретной компании.')); ui.profile.hidden = false;
    }
    async function fetchGraph(companyId) {
      if (state.graphs.has(companyId)) return state.graphs.get(companyId);
      try { const graph = await requestJson('/api/companies/' + encodeURIComponent(companyId) + '/graph'); state.graphs.set(companyId, graph); return graph; }
      catch (_) { return null; }
    }
    async function loadCompanies() {
      state.loaded = false; ui.company.disabled = true; ui.companyError.hidden = true; ui.retry.hidden = true; controls();
      try {
        const companies = await requestJson('/api/companies');
        if (!Array.isArray(companies) || companies.length === 0) throw new Error('В сервисе пока нет компаний для анализа.');
        state.companies = new Map(companies.map(company => [company.id,company])); ui.company.replaceChildren();
        for (const company of companies) ui.company.add(new Option(company.name,company.id));
        state.loaded = true; ui.company.disabled = false; renderProfile(state.companies.get(ui.company.value)); void fetchGraph(ui.company.value);
      } catch (error) {
        ui.company.replaceChildren(new Option('Компании недоступны','')); ui.companyError.textContent = error.message; ui.companyError.hidden = false; ui.retry.hidden = false; renderProfile(null);
      }
      controls();
    }
    function sourceRefs(ids, label = 'Источники') { return el('p','claim-meta',label + ': ' + (ids && ids.length ? ids.join(', ') : 'нужна проверка')); }
    function spanLocation(span) { return span ? span.source_id + ' [' + span.start + ':' + span.end + ']' : ''; }
    function renderProviderMetadata(extraction) {
      const metadata = extraction.provider_metadata;
      if (!metadata || typeof metadata !== 'object') return null;
      const parts = [], usage = metadata.usage && typeof metadata.usage === 'object' ? metadata.usage : metadata;
      if (typeof metadata.model === 'string' && metadata.model.length < 150) parts.push('Модель: ' + metadata.model);
      if (typeof metadata.protocol === 'string' && metadata.protocol.length < 50) parts.push('Протокол: ' + metadata.protocol);
      const input = usage.input_tokens ?? usage.prompt_tokens, output = usage.output_tokens ?? usage.completion_tokens;
      if (typeof input === 'number' && Number.isFinite(input) && input >= 0) parts.push('Вход: ' + input + ' токенов');
      if (typeof output === 'number' && Number.isFinite(output) && output >= 0) parts.push('Выход: ' + output + ' токенов');
      const duration = metadata.duration_ms ?? metadata.latency_ms;
      if (typeof duration === 'number' && Number.isFinite(duration) && duration >= 0) parts.push('Запрос: ' + Math.round(duration).toLocaleString('ru-RU') + ' мс');
      if (!parts.length) return null;
      const root = el('div','provider-meta'); for (const part of parts) root.append(el('span','',part)); return root;
    }
    function renderExtraction(extraction) {
      const root = section('Утверждения источника — требуют проверки','01'); root.id = 'source-assertions';
      if (!extraction) { root.append(el('p','extraction-note','Структурированное извлечение не получено. Сверьте исходный текст в источниках.')); return root; }
      const mode = extraction.mode === 'LLM' ? 'Извлечено с LLM' : 'Извлечено локальными правилами';
      root.append(badge(mode,'blue'), el('p','extraction-note','Цитата подтверждает, что формулировка есть в тексте. Достоверность сообщения, роль участников и смысл события ещё нужно проверить.'));
      const modalities = {ASSERTED:'В источнике утверждается',NEGATED:'В источнике отрицается',POSSIBLE:'Условное или возможное',UNKNOWN:'Модальность не установлена'};
      if (!extraction.assertions?.length) root.append(el('p','small muted','Отдельные утверждения не выделены. Нужен ручной разбор текста.'));
      for (const assertion of extraction.assertions || []) {
        const card = el('article','assertion-card'), top = el('div','assertion-top');
        top.append(badge(modalities[assertion.modality] || 'Модальность не установлена',assertion.modality === 'NEGATED' ? 'red' : 'caution'), el('span','small muted','Утверждение источника'));
        card.append(top,el('blockquote','assertion-quote',assertion.text.quote));
        const parts = [['actor','Участник'],['action','Действие'],['object','Объект']].filter(([key]) => assertion[key]);
        if (parts.length) {
          const dl = el('dl','assertion-parts');
          for (const [key,label] of parts) dl.append(el('dt','',label),el('dd','',assertion[key].quote)); card.append(dl);
        }
        card.append(el('p','span-location',spanLocation(assertion.text))); root.append(card);
      }
      const fields = el('div','extracted-fields'), dates = el('div','extracted-group'), quantities = el('div','extracted-group');
      dates.id = 'extracted-dates'; quantities.id = 'extracted-quantities';
      dates.append(el('h4','','Даты в тексте'));
      if (!extraction.dates?.length) dates.append(el('p','small muted','Даты не выделены.'));
      const dateRoles = {EVENT:'Событие по источнику',PUBLICATION:'Публикация по источнику',UNSPECIFIED:'Роль не установлена'};
      for (const item of extraction.dates || []) {
        const card = el('div','extracted-item'), dl = el('dl');
        card.append(el('blockquote','','«' + item.span.quote + '»'));
        dl.append(el('dt','','ISO-дата'),el('dd','',item.iso_date || 'Не определена по цитате'),el('dt','','Роль'),el('dd','',dateRoles[item.role] || 'Не установлена'));
        card.append(dl,el('p','span-location',spanLocation(item.span))); dates.append(card);
      }
      dates.append(el('p','small muted','Относительные даты не вычисляются из даты открытия страницы.'));
      quantities.append(el('h4','','Количество, единица и период'));
      if (!extraction.quantities?.length) quantities.append(el('p','small muted','Числовые величины не выделены.'));
      for (const item of extraction.quantities || []) {
        const card = el('div','extracted-item'), dl = el('dl'); card.append(el('blockquote','','«' + item.span.quote + '»'));
        dl.append(el('dt','','Число'),el('dd','',item.value.quote),el('dt','','Единица'),el('dd','',item.unit ? item.unit.quote : 'Не указана'),el('dt','','Период'),el('dd','',item.period ? item.period.quote : 'Не указан'));
        card.append(dl,el('p','span-location',spanLocation(item.span))); quantities.append(card);
      }
      fields.append(dates,quantities); root.append(fields);
      if (extraction.knowledge_gaps?.length) { const gaps = el('details','extraction-gaps'); gaps.append(el('summary','','Пробелы извлечения · ' + extraction.knowledge_gaps.length),list(extraction.knowledge_gaps)); root.append(gaps); }
      const metadata = renderProviderMetadata(extraction); if (metadata) root.append(metadata);
      return root;
    }
    function renderPath(path, graph) {
      const nodes = new Map((graph?.nodes || []).map(node => [node.id,node])), edges = new Map((graph?.edges || []).map(edge => [edge.id,edge]));
      const card = el('article','path-card'), top = el('div','path-top');
      top.append(el('strong','',pathStatuses[path.path_status] || path.path_status), badge('Значимость: неизвестна','gray')); card.append(top);
      const steps = el('div','path-steps');
      for (let index = 0; index < path.node_ids.length; index += 1) {
        const id = path.node_ids[index], node = nodes.get(id);
        if (index > 0) {
          const edgeId = path.edge_ids[index - 1], edge = edges.get(edgeId), status = path.edge_statuses[index - 1], line = el('div','path-edge');
          line.append(el('span','edge-arrow','↓'), el('span','',relations[edge?.relation] || 'Зависимость'), badge(knowledge[status] || status,'caution'));
          line.append(el('span','evidence-link','Основание: ' + ((edge?.evidence_ids || path.evidence_ids || []).join(', ') || 'не указано'))); steps.append(line);
        }
        const item = el('div','path-node'); item.append(el('span','',node?.label || id), el('span','node-kind',nodeTypes[node?.type] || 'Объект графа')); steps.append(item);
      }
      const foot = el('div','path-foot'); foot.append(el('p','',path.disclaimer || 'Потенциальный канал требует проверки.'), el('p','','Маршрут: ' + path.id)); card.append(steps,foot); return card;
    }
    function renderClaims(title, items, emptyText) {
      const box = el('div','claim-block'); box.append(el('h4','',title));
      if (!items?.length) { box.append(el('p','muted',emptyText)); return box; }
      for (const item of items) {
        const entry = el('div','claim-item'); entry.append(badge(knowledge[item.knowledge_status] || item.knowledge_status,'caution'), el('p','',item.statement));
        if (item.path_ids?.length) entry.append(sourceRefs(item.path_ids,'Маршруты'));
        if (item.source_ids?.length) entry.append(sourceRefs(item.source_ids)); box.append(entry);
      }
      return box;
    }
    function renderSources(data) {
      const details = el('details','source-details'); details.id = 'sources';
      const sources = data.insight.sources || []; details.append(el('summary','','Источники и совпадения в тексте · ' + sources.length));
      const body = el('div','source-body'), sourceDocument = data.normalization.source, news = el('article','source-item');
      news.append(badge(sourceDocument.is_synthetic ? 'ВЫМЫШЛЕННАЯ НОВОСТЬ' : 'ТЕКСТ ПОЛЬЗОВАТЕЛЯ','gray'), el('h4','',sourceDocument.title || 'Исходный текст новости'), el('p','source-ref',sourceDocument.id));
      if (sourceDocument.source_url) { const url = el('p','small'); url.append(safeLink(sourceDocument.source_url)); news.append(url); }
      news.append(el('pre','',sourceDocument.text));
      const matches = [...(data.normalization.target_matches || []).map(match => ({...match,kind:'Объект: ' + match.label})),...(data.normalization.channel_matches || []).map(match => ({...match,kind:'Тема: ' + (channels[match.channel] || match.channel)}))];
      if (matches.length) {
        news.append(el('h4','','Точные фрагменты, найденные при извлечении')); const matchesList = el('ul','match-list');
        for (const match of matches) matchesList.append(el('li','',match.kind + ' — «' + match.quote + '» [' + match.start + ':' + match.end + ']'));
        news.append(matchesList,el('p','small muted','Совпадение слов не подтверждает наступление события или причинный эффект.'));
      }
      body.append(news);
      for (const source of sources) {
        const entry = el('article','source-item'); entry.append(el('p','source-ref',source.id + ' · ' + source.source_kind + (source.is_synthetic ? ' · СИНТЕТИКА' : '')), el('h4','',source.statement), el('p','source-ref',source.source_reference)); body.append(entry);
      }
      details.append(body); return details;
    }
    function renderResult(data, graph) {
      const insight = data.insight, normalization = data.normalization, root = el('div','result-content'), status = el('div','status-row'), hasPath = insight.status === 'POTENTIAL_EXPOSURE';
      const extraction = normalization.extraction, usesModel = extraction?.mode === 'LLM' || normalization.mode === 'LLM_EXTRACT';
      status.append(badge(hasPath ? 'ПОТЕНЦИАЛЬНЫЙ КАНАЛ' : 'НУЖНЫ ДОПОЛНИТЕЛЬНЫЕ ДАННЫЕ',hasPath ? 'caution' : 'gray'), badge(usesModel ? 'ИЗВЛЕЧЕНИЕ: LLM' : 'ИЗВЛЕЧЕНИЕ: ПРАВИЛА','gray'),badge('ВЫВОД: ГРАФ И ШАБЛОН','gray'));
      root.append(status,el('h3','result-title',hasPath ? 'Есть маршрут, который стоит проверить' : 'Подтверждённый маршрут не найден'),el('p','result-lead',insight.why_for_company));
      const event = el('section','section'); event.append(el('h3','','Исходное сообщение'),el('div','fact-box',insight.what_happened));
      const tags = el('div','channels'); for (const channel of normalization.event.channels || []) tags.append(badge(channels[channel] || channel,'blue')); event.append(tags); root.append(event);
      root.append(renderExtraction(extraction));
      const paths = section('Как событие связано с компанией','02');
      if (insight.impact_paths.length) {
        paths.append(el('p','small muted','Направление ниже показывает возможное распространение воздействия. Каждое звено сохраняет исходный статус знания.'));
        for (const path of insight.impact_paths) paths.append(renderPath(path,graph));
      } else paths.append(el('p','small muted','В текущем учебном графе нет допустимого пути от объекта новости до показателя выбранной компании. Это не доказывает отсутствие риска.'));
      if (!graph) paths.append(el('p','small muted','Подписи графа временно недоступны; показаны идентификаторы из результата анализа.')); root.append(paths);
      const claims = section('Риски и возможности','03'), claimGrid = el('div','claims');
      claimGrid.append(renderClaims('Возможные риски',insight.risk_items,'Оснований для отдельной гипотезы риска недостаточно.'),renderClaims('Возможности',insight.opportunity_items,'Возможности по доступным данным не установлены.')); claims.append(claimGrid); root.append(claims);
      const bank = section('Позиция аналитиков Альфы','04'), bankBox = el('div','bank-card'), bankHeading = el('div','bank-heading');
      const bankStatuses = {NOT_FOUND:'Материал не найден',SUPPORTS:'Поддерживает вывод',REFINES:'Уточняет вывод',CONTRADICTS:'Противоречит выводу'};
      bankHeading.append(el('strong','','Отдельно от вывода системы'),badge(bankStatuses[insight.alfa_view.status] || insight.alfa_view.status,'gray')); bankBox.append(bankHeading,el('p','',insight.alfa_view.statement));
      if (insight.alfa_view.quote_ref) bankBox.append(el('p','source-ref',insight.alfa_view.quote_ref)); bank.append(bankBox); root.append(bank);
      const actions = section('Что проверить дальше','05'), actionList = el('ol','action-list');
      for (const [index,action] of insight.actions.entries()) {
        const item = el('li'), description = el('div'); description.append(el('p','',action.text));
        description.append(el('p','action-note',action.path_id ? 'Основание: маршрут ' + action.path_id : 'Пробел: ' + (action.data_gap || 'нужны сведения'))); item.append(el('span','action-number',index + 1),description); actionList.append(item);
      }
      actions.append(actionList); root.append(actions);
      const gaps = section('Что пока неизвестно','06'); gaps.append(list(insight.knowledge_gaps,'gap-list')); root.append(gaps,renderSources(data));
      const warnings = el('div','warning-list'); for (const warning of new Set([...(normalization.warnings || []),...(extraction?.warnings || [])])) warnings.append(el('p','',warning));
      if (data.analysis.warning) warnings.append(el('p','',data.analysis.warning));
      warnings.append(el('p','',usesModel ? 'LLM использовалась только для извлечения сведений из текста. Маршрут и объяснение построены по учебному графу и шаблону; риски не сгенерированы моделью. Поиск материалов Альфы и агентное планирование не запускались.' : 'Извлечение выполнено локальными правилами. Маршрут и объяснение построены по учебному графу и шаблону. LLM, поиск материалов Альфы и агентное планирование не запускались.'));
      root.append(warnings,el('p','export-status','')); root.querySelector('.export-status').id = 'export-status';
      ui.output.replaceChildren(root); ui.tools.hidden = false; ui.resultId.hidden = false; ui.resultId.textContent = insight.id; ui.resultId.title = insight.id;
    }
    ui.form.addEventListener('submit',async event => {
      event.preventDefault(); if (state.busy || !state.loaded || !ui.form.reportValidity()) return;
      if (ui.mode.value === 'LLM' && !state.providerConfigured) { ui.error.textContent = 'Выбранная LLM недоступна. Обновите конфигурацию или выберите локальные правила.'; ui.error.hidden = false; return; }
      if (ui.text.value.trim().length < 20) { ui.error.textContent = 'Добавьте не менее 20 символов текста новости.'; ui.error.hidden = false; return; }
      invalidate(); const revision = state.revision, companyId = ui.company.value;
      state.busy = true; const controller = new AbortController(); state.controller = controller; controls(); emptyState(true);
      const requestedMode = ui.mode.value;
      const body = {company_id:companyId,title:ui.headline.value,text:ui.text.value,source_url:ui.url.value.trim() || null,is_synthetic:ui.synthetic.checked,extraction_mode:requestedMode};
      try {
        const [data,graph] = await Promise.all([requestJson('/api/news/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal}),fetchGraph(companyId)]);
        if (revision !== state.revision) return;
        if (!data.insight || !data.normalization || !data.analysis || data.insight.company_id !== companyId) throw new Error('Ответ сервера не соответствует выбранной компании или контракту анализа.');
        if (data.normalization.extraction && data.normalization.extraction.mode !== requestedMode) throw new Error('Сервис вернул другой режим извлечения. Результат не показан: повторите запрос в выбранном режиме.');
        state.lastResult = data; renderResult(data,graph);
      } catch (error) {
        if (revision !== state.revision || error.name === 'AbortError') return;
        emptyState(); ui.error.textContent = error.message; ui.error.hidden = false;
        if (error.status === 503 && requestedMode === 'LLM') {
          const fallback = el('div','failure-note fallback-available'); fallback.id = 'llm-unavailable';
          fallback.append(el('p','','Текст сохранён в форме. Переход к локальным правилам выполняется только по вашему выбору.'));
          const chooseRules = el('button','quiet','Выбрать локальные правила'); chooseRules.type = 'button';
          chooseRules.addEventListener('click',() => {ui.mode.value = 'RULES';invalidate();modeDisclosure();ui.submit.focus();}); fallback.append(chooseRules); ui.error.after(fallback);
        }
      } finally { if (revision === state.revision) { state.busy = false; state.controller = null; controls(); } }
    });
    ui.company.addEventListener('change',() => {invalidate();renderProfile(state.companies.get(ui.company.value));void fetchGraph(ui.company.value);});
    ui.mode.addEventListener('change',() => {invalidate();modeDisclosure();});
    ui.refreshProvider.addEventListener('click',() => {void loadProviderConfiguration();});
    for (const input of [ui.headline,ui.text,ui.url,ui.synthetic]) input.addEventListener('input',() => {invalidate();});
    for (const button of document.querySelectorAll('[data-example]')) button.addEventListener('click',() => {
      invalidate(); const example = examples[button.dataset.example]; ui.headline.value = example.title; ui.text.value = example.text; ui.url.value = ''; ui.synthetic.checked = true; controls(); ui.text.focus();
    });
    ui.retry.addEventListener('click',() => {void loadCompanies();});
    $('#copy-json').addEventListener('click',async () => {
      if (!state.lastResult) return; const captured = state.lastResult;
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Буфер обмена недоступен. Используйте «Скачать JSON».');
        await navigator.clipboard.writeText(JSON.stringify(captured,null,2)); if (state.lastResult === captured) $('#export-status').textContent = 'JSON скопирован в буфер обмена.';
      } catch (error) { if (state.lastResult === captured) $('#export-status').textContent = error.message || 'Не удалось скопировать JSON. Используйте скачивание.'; }
    });
    $('#download-json').addEventListener('click',() => {
      if (!state.lastResult) return;
      const data = state.lastResult, blob = new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}), url = URL.createObjectURL(blob), a = el('a');
      a.href = url; a.download = 'impact-' + String(data.insight.company_id).replace(/[^a-zA-Z0-9_-]/g,'_') + '.json'; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url),1000); $('#export-status').textContent = 'JSON подготовлен для скачивания.';
    });
    emptyState(); controls(); modeDisclosure(); void loadCompanies(); void loadProviderConfiguration();
  