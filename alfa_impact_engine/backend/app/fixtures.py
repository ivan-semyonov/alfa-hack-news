"""Two fictional companies and a deliberately limited graph. No bank data."""
from .models import Company, Evidence, GraphNode, GraphEdge, Event

COMPANIES = [
    Company(id='DEMO-MFG', name='Демо: завод электродвигателей', industry_code='27.11',
            industry_label='Производство электродвигателей (пример)', region='Учебный регион', bank_loan_mark=True),
    Company(id='DEMO-SVC', name='Демо: сервисная компания', industry_code='62.01',
            industry_label='Разработка программного обеспечения (пример)', region='Учебный регион', bank_loan_mark=False),
]
EVIDENCES = [
    Evidence(id='ev_template_01', source_kind='INDUSTRY_TEMPLATE', source_reference='synthetic:manufacturing-v0',
             statement='Типовой учебный процесс может использовать компонент X.'),
    Evidence(id='ev_demo_02', source_kind='USER_CONFIRMATION', source_reference='synthetic:test-confirmation',
             statement='Иллюстративное подтверждение процесса в выдуманной компании.'),
    Evidence(id='ev_payment_01', source_kind='BANK_PAYMENT', source_reference='synthetic:payment-row',
             statement='Учебный платёж DEMO-MFG → DEMO-SVC, не доказательство поставки.'),
]
NODES = [
    GraphNode(id='RESOURCE_X', type='RESOURCE', label='Условный компонент X',
              knowledge_status='TEMPLATE', evidence_ids=['ev_template_01']),
    GraphNode(id='MFG_PROC', type='PROCESS', label='Сборка электродвигателей', company_id='DEMO-MFG',
              knowledge_status='TEMPLATE', evidence_ids=['ev_template_01']),
    GraphNode(id='MFG_PRODUCT', type='PRODUCT', label='Электродвигатель', company_id='DEMO-MFG',
              knowledge_status='TEMPLATE', evidence_ids=['ev_template_01']),
    GraphNode(id='MFG_KPI', type='KPI', label='Выпуск готовой продукции', company_id='DEMO-MFG',
              knowledge_status='INFERENCE', evidence_ids=['ev_template_01']),
    GraphNode(id='SVC_PROC', type='PROCESS', label='Разработка ПО', company_id='DEMO-SVC',
              knowledge_status='TEMPLATE', evidence_ids=['ev_template_01']),
    GraphNode(id='SVC_KPI', type='KPI', label='Объём услуг', company_id='DEMO-SVC',
              knowledge_status='TEMPLATE', evidence_ids=['ev_template_01']),
    GraphNode(id='MFG_COMPANY', type='COMPANY', label='Учебная компания MFG', company_id='DEMO-MFG',
              knowledge_status='FACT', evidence_ids=['ev_demo_02']),
    GraphNode(id='SVC_COMPANY', type='COMPANY', label='Учебная компания SVC', company_id='DEMO-SVC',
              knowledge_status='FACT', evidence_ids=['ev_demo_02']),
]
EDGES = [
    GraphEdge(id='e_requires_x', source_id='MFG_PROC', target_id='RESOURCE_X',
              relation='REQUIRES', knowledge_status='TEMPLATE', evidence_ids=['ev_template_01']),
    GraphEdge(id='e_product_process', source_id='MFG_PRODUCT', target_id='MFG_PROC',
              relation='DEPENDS_ON', knowledge_status='TEMPLATE', evidence_ids=['ev_template_01']),
    GraphEdge(id='e_kpi_product', source_id='MFG_KPI', target_id='MFG_PRODUCT',
              relation='DEPENDS_ON', knowledge_status='INFERENCE', evidence_ids=['ev_template_01']),
    GraphEdge(id='e_service_kpi', source_id='SVC_KPI', target_id='SVC_PROC',
              relation='DEPENDS_ON', knowledge_status='TEMPLATE', evidence_ids=['ev_template_01']),
    GraphEdge(id='e_mfg_owns', source_id='MFG_COMPANY', target_id='MFG_PROC',
              relation='OWNS_PROCESS', knowledge_status='FACT', evidence_ids=['ev_demo_02']),
    GraphEdge(id='e_svc_owns', source_id='SVC_COMPANY', target_id='SVC_PROC',
              relation='OWNS_PROCESS', knowledge_status='FACT', evidence_ids=['ev_demo_02']),
    GraphEdge(id='e_payment', source_id='MFG_COMPANY', target_id='SVC_COMPANY',
              relation='HAS_PAYMENT_TO', knowledge_status='FACT', evidence_ids=['ev_payment_01']),
]
EVENTS = [
    Event(id='SYNTH-EVENT-X', title='Учебное ограничение поставок компонента X',
          summary='Вымышленный сценарий для тестирования распространения воздействия.',
          target_node_ids=['RESOURCE_X'], channels=['SUPPLY'], source_ids=['synthetic_news_1']),
    Event(id='SYNTH-EVENT-Q', title='Учебное событие без известной зависимости',
          summary='Проверка корректного отказа при недостаточных данных.',
          target_node_ids=['NONEXISTENT_RESOURCE'], channels=['SUPPLY'], source_ids=['synthetic_news_2']),
]
