"""Private local acceptance of an actual PDF; output stays under ignored .runtime."""
import argparse
import json
from pathlib import Path
from backend.app.research import ResearchService, DEMO_COMPANIES, DEMO_NEWS
from backend.app.product_contracts import AnalyzeInput

ROOT=Path(__file__).resolve().parents[1]


def verify(pdf):
    work=ROOT/'.runtime'/'pdf-acceptance'
    service=ResearchService(work/'db.sqlite',work/'materials',work)
    company=DEMO_COMPANIES[2]|{'id':'QA-TRADE','name':'Учебная торговая компания'}
    service.store.put_company('workspace',company)
    doc,_=service.materials.add('workspace',title=pdf.stem,kind='ALFA_REPORT',pdf=pdf.read_bytes(),filename=pdf.name)
    request=AnalyzeInput(company_id=company['id'],**DEMO_NEWS[2],is_synthetic=True)
    created,_=service.create_run('workspace',request)
    result=service.execute('workspace',created['id'])
    assert result['status']=='COMPLETED', result.get('error')
    assert result['citations'] and result['insight']['alfa_review']['status']=='REFINES'
    output={'status':result['status'],'run_id':result['id'],'document':doc,'citation_pages':[c['page'] for c in result['citations']],
            'review':result['insight']['alfa_review'],'self_check':result['self_check']}
    (work/'verification.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Actual PDF: '+str(doc['indexed_pages'])+' indexed pages; '+str(doc['chunk_count'])+' chunks; citations on pages '+str(output['citation_pages'])+'; '+result['status'])
    service.store.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pdf',required=True,type=Path)
    verify(parser.parse_args().pdf)
