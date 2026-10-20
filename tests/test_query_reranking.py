import asyncio,json
import httpx
import pytest


def test_rewrite_preserves_model_numbers_and_negation():
    from app.knowledge.query import preserve_query,query_plan
    original='QC-M100不能放洗碗机吗，容量350ml？'
    assert preserve_query(original,'杯子可以放洗碗机吗')==original
    assert preserve_query(original,'QC-M100容量350ml是否不支持洗碗机')!=original
    plan=query_plan('邮费多少',{'normalized':'运费是多少','synonyms':['运费','配送费','运费','x'*100]})
    assert plan.synonyms==['运费','配送费']
    assert plan.original=='邮费多少'


def test_reranker_http_contract_rejects_bad_count_or_revision():
    from app.knowledge.reranking import Reranker
    async def run():
        def handler(request):
            body=json.loads(request.content)
            assert body['query']=='邮费多少' and body['passages']==['运费8元']
            return httpx.Response(200,json={'model':'BAAI/bge-reranker-v2-m3','revision':'fixed','scores':[.9]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await Reranker('http://local',revision='fixed',client=client).score('邮费多少',['运费8元'])==[.9]
            with pytest.raises(ValueError):await Reranker('http://local',revision='other',client=client).score('邮费多少',['运费8元'])
    asyncio.run(run())

def test_local_reranker_configuration_is_explicit():
    from app.config import Settings
    cfg=Settings(_env_file=None,llm_api_key='test',llm_model='test',reranker_revision='fixed',reranker_base_url='http://127.0.0.1:8002')
    assert cfg.reranker_revision=='fixed'

@pytest.mark.parametrize('original,changed',[
 ('容量350ml','容量1350ml'),
 ('容量不超过350ml','容量不低于350ml'),
 ('容量350ml','容量350L'),
 ('QC-M100不能机洗','QC-M100不能微波但可以机洗'),
])
def test_rewrite_rejects_changed_quantities_relations_and_negative_object(original,changed):
    from app.knowledge.query import preserve_query
    assert preserve_query(original,changed)==original


def test_rewrite_keeps_model_parameter_associations():
    from app.knowledge.query import preserve_query
    original='QC-M100容量350ml，QC-M200容量500ml'
    assert preserve_query(original,'QC-M100容量500ml，QC-M200容量350ml')==original


def test_domain_synonyms_normalize_before_dense_and_reranker_without_duplication():
    from app.knowledge.query import query_plan
    plan=query_plan('邮费是多少？',{'normalized':'邮费是多少？','synonyms':['配送费']})
    assert plan.original=='邮费是多少？' and plan.normalized=='运费是多少？'
    assert plan.synonyms==['配送费']
