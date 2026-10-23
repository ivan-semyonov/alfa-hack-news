"""Original, versioned industry templates; applicability is always conditional."""
import re
from .models import Company, Evidence, GraphNode, GraphEdge
from .graph_engine import ExposureGraph

VERSION = '1.0.0'
TARGET_ALIASES = [
    {'id': 'RESOURCE_X', 'label': 'Компонент X', 'pattern': r'\bкомпонент(?:а|у|ом|е)?\s+[xх](?!\w)', 'channels': ['SUPPLY'], 'kind': 'RESOURCE'},
    {'id': 'RESOURCE_COPPER', 'label': 'Медь', 'pattern': r'\bмед(?:ь|и|ью)\b', 'channels': ['SUPPLY'], 'kind': 'COMMODITY'},
    {'id': 'POWER', 'label': 'Электроснабжение', 'pattern': r'\b(?:электроэнерг\w*|электроснабжен\w*|электросет\w*)', 'channels': ['INFRASTRUCTURE'], 'kind': 'RESOURCE'},
    {'id': 'FINANCE_RATE', 'label': 'Ключевая ставка', 'pattern': r'\bключев\w*\s+ставк\w*', 'channels': ['FINANCE', 'MACRO'], 'kind': 'FINANCIAL_INSTRUMENT'},
    {'id': 'CONSUMER_DEMAND', 'label': 'Потребительский спрос', 'pattern': r'\b(?:спрос\w*|потреблен\w*)', 'channels': ['DEMAND'], 'kind': 'RESOURCE'},
    {'id': 'LABOR_MARKET', 'label': 'Рынок труда', 'pattern': r'\b(?:кадр\w*|работник\w*|зарплат\w*|рынок\s+труда)', 'channels': ['LABOR'], 'kind': 'RESOURCE'},
    {'id': 'SOFTWARE', 'label': 'Программное обеспечение', 'pattern': r'\b(?:программн\w*\s+обеспечен\w*|лицензи\w*\s+по|облачн\w*\s+сервис\w*)', 'channels': ['TECHNOLOGY'], 'kind': 'TECHNOLOGY'},
    {'id': 'FUEL', 'label': 'Топливо', 'pattern': r'\b(?:топлив\w*|нефт\w*|дизел\w*)', 'channels': ['SUPPLY'], 'kind': 'RESOURCE'},
]
TARGET_INDEX = {item['id']: item for item in TARGET_ALIASES}
TARGET_PATTERNS = [(item, re.compile(item['pattern'], re.I)) for item in TARGET_ALIASES]

TEMPLATES = [
    {'id': 'manufacturing', 'name': 'Промышленное производство', 'okved_prefixes': ['25', '26', '27', '28', '29'],
     'process': 'Производство и сборка', 'product': 'Готовая продукция', 'kpi': 'Выпуск продукции',
     'targets': ['RESOURCE_X', 'RESOURCE_COPPER', 'POWER', 'FUEL', 'LABOR_MARKET'], 'channels': ['SUPPLY', 'INFRASTRUCTURE', 'LABOR']},
    {'id': 'software', 'name': 'Разработка и сопровождение ПО', 'okved_prefixes': ['62', '63'],
     'process': 'Разработка и эксплуатация сервисов', 'product': 'Программные услуги', 'kpi': 'Непрерывность оказания услуг',
     'targets': ['POWER', 'SOFTWARE', 'LABOR_MARKET'], 'channels': ['INFRASTRUCTURE', 'TECHNOLOGY', 'LABOR']},
    {'id': 'trade', 'name': 'Оптовая и розничная торговля', 'okved_prefixes': ['46', '47'],
     'process': 'Продажи и управление запасами', 'product': 'Товарооборот', 'kpi': 'Объём реализации',
     'targets': ['CONSUMER_DEMAND', 'FUEL', 'LABOR_MARKET'], 'channels': ['DEMAND', 'SUPPLY', 'LABOR']},
]


def choose_template(company):
    code = str(company.get('industry_code') or '')
    return next((item for item in TEMPLATES if any(code.startswith(prefix) for prefix in item['okved_prefixes'])), None)


def build_graph(company):
    template = choose_template(company)
    cid = company['id']
    evidence = [Evidence(id='profile:' + cid, source_kind='COMPANY_PROFILE', source_reference=company.get('source_id', 'synthetic:company'),
                         statement='Профиль содержит отрасль и признаки компании; функциональные зависимости из него не следуют.',
                         is_synthetic=company.get('is_synthetic', False))]
    nodes = [GraphNode(id=cid + ':company', type='COMPANY', label=company['name'], company_id=cid,
                       knowledge_status='FACT', evidence_ids=[evidence[0].id])]
    edges = []
    if not template:
        return ExposureGraph(nodes, edges), evidence, None
    ev_id = 'template:' + template['id'] + ':' + VERSION
    evidence.append(Evidence(id=ev_id, source_kind='INDUSTRY_TEMPLATE', source_reference='templates:' + template['id'] + '@' + VERSION,
                             statement='Собственный отраслевой шаблон. Применимость к процессам этой компании не подтверждена.', is_synthetic=True))
    for suffix, kind, label in [('process', 'PROCESS', template['process']), ('product', 'PRODUCT', template['product']), ('kpi', 'KPI', template['kpi'])]:
        nodes.append(GraphNode(id=cid + ':' + suffix, type=kind, label=label, company_id=cid,
                               knowledge_status='TEMPLATE', evidence_ids=[ev_id]))
    def edge(key, source, target, relation='DEPENDS_ON'):
        edges.append(GraphEdge(id=cid + ':' + key, source_id=source, target_id=target, relation=relation,
                               knowledge_status='TEMPLATE', evidence_ids=[ev_id]))
    edge('product_process', cid + ':product', cid + ':process')
    edge('kpi_product', cid + ':kpi', cid + ':product')
    targets = list(template['targets'])
    if company.get('bank_loan_mark') is True:
        targets.append('FINANCE_RATE')
    for target in targets:
        item = TARGET_INDEX[target]
        nodes.append(GraphNode(id=target, type=item['kind'], label=item['label'], knowledge_status='TEMPLATE', evidence_ids=[ev_id]))
        if target == 'FINANCE_RATE':
            nodes.append(GraphNode(id=cid + ':finance', type='PROCESS', label='Проверка условий финансирования', company_id=cid,
                                   knowledge_status='HYPOTHESIS', evidence_ids=[ev_id]))
            nodes.append(GraphNode(id=cid + ':finance_kpi', type='KPI', label='Потенциальные финансовые расходы', company_id=cid,
                                   knowledge_status='HYPOTHESIS', evidence_ids=[ev_id]))
            edge('rate_dependency', cid + ':finance', target)
            edge('finance_kpi', cid + ':finance_kpi', cid + ':finance')
        else:
            edge('requires_' + target, cid + ':process', target, 'REQUIRES')
    return ExposureGraph(nodes, edges), evidence, template


def registry():
    return {'version': VERSION, 'templates': TEMPLATES, 'targets': TARGET_ALIASES,
            'warning': 'Каждая зависимость шаблона условна до подтверждения применимости.'}
