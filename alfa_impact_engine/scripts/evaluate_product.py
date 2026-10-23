"""Offline 24-pair regression and analytic-context ablation. No external calls."""
import json
from pathlib import Path
import tempfile
from backend.app.product_contracts import AnalyzeInput
from backend.app.research import ResearchService, DEMO_COMPANIES, DEMO_NEWS

ROOT = Path(__file__).resolve().parents[1]


def evaluate():
    (ROOT/'.runtime').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='evaluation-',dir=ROOT/'.runtime') as work:
        path=Path(work)
        service=ResearchService(path/'db.sqlite',path/'materials',path/'runtime')
        expected=({0,1,3,4},{3,4,5},{1,2,4})
        cases=[]
        for company,indices in zip(DEMO_COMPANIES,expected):
            for index,news in enumerate(DEMO_NEWS):
                run,_=service.create_run('demo',AnalyzeInput(company_id=company['id'],is_synthetic=True,**news))
                result=service.execute('demo',run['id'])
                passed=(bool(result.get('paths'))==(index in indices) and result['status'] in ('COMPLETED','NEEDS_MORE_DATA')
                        and len(result['trace'])<=12 and all(p['company_id']==company['id'] for p in result.get('paths',[])))
                cases.append({'company_id':company['id'],'news_index':index,'title':news['title'],'expected_path':index in indices,
                              'actual_path':bool(result.get('paths')),'steps':len(result['trace']),'passed':passed})
        def analyze_demand():
            run,_=service.create_run('demo',AnalyzeInput(company_id='DEMO-TRADE',is_synthetic=True,**DEMO_NEWS[2]))
            return service.execute('demo',run['id'])
        before=analyze_demand()
        # Controlled test fixture of ALFA_REPORT type; not a bank-authored report.
        text='Тестовый сценарий аналитики. Потребительский спрос растёт, но в следующие месяцы ожидается охлаждение потребления и замедление спроса. Нужно проверить устойчивость спроса до изменения запасов.'
        doc,_=service.materials.add('demo',title='Тест абляции потребления',kind='ALFA_REPORT',text=text,published_at='2026-08-05')
        after=analyze_demand()
        exact=all(service.materials.get('demo',c['document_id'],full=True)['pages'][c['page']-1]['text'][c['start']:c['start']+len(c['quote'])]==c['quote'] for c in after['citations'])
        ablation={'fixture_is_controlled_test_not_bank_publication':True,'without_status':before['insight']['alfa_review']['status'],
                  'with_status':after['insight']['alfa_review']['status'],'risk_changed':before['insight']['risks']!=after['insight']['risks'],
                  'actions_changed':before['insight']['actions']!=after['insight']['actions'],'literal_citations_valid':exact}
        branches={step['tool'] for row in service.store.all('SELECT payload FROM runs WHERE tenant=?',('demo',)) for step in json.loads(row['payload'])['trace']}
        service.store.close()
        success=all(c['passed'] for c in cases) and ablation['risk_changed'] and ablation['actions_changed'] and exact and {'get_financial_context','get_payment_context'}<=branches
        return {'schema_version':'1.0.0','mode':'OFFLINE_RULE_REGRESSION','external_llm_tested':False,'passed':success,
                'cases_passed':sum(c['passed'] for c in cases),'cases_total':len(cases),'cases':cases,'rag_ablation':ablation,
                'warning':'Synthetic regression, not production accuracy, causal validity or real LLM quality.'}


if __name__=='__main__':
    result=evaluate()
    destination=ROOT/'evaluation/product_report.json'
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"Product regression: {result['cases_passed']}/{result['cases_total']}; RAG ablation: {result['passed']}")
    raise SystemExit(0 if result['passed'] else 1)
