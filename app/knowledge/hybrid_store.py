"""Milvus native dense/BM25 retrieval. Never substitutes application-side fusion."""
import asyncio,json
from pymilvus import MilvusClient,DataType,Function,FunctionType,AnnSearchRequest,RRFRanker

PRODUCT_CATEGORIES=('通用','陶瓷杯','保温杯','小家电')


def category_filter(category):
    if category is None:return ''
    if category not in PRODUCT_CATEGORIES:raise ValueError('Unknown product category')
    return 'product_category in '+json.dumps(list(dict.fromkeys([category,'通用'])),ensure_ascii=False)


class HybridStore:
    def __init__(self,uri,collection='knowledge_hybrid_v4'):
        self.client=MilvusClient(uri=uri,timeout=60);self.collection=collection

    async def initialize(self):
        def setup():
            if not self.client.has_collection(self.collection):
                schema=self.client.create_schema(auto_id=False,enable_dynamic_field=False)
                schema.add_field('chunk_id',DataType.VARCHAR,is_primary=True,max_length=64)
                schema.add_field('embedding',DataType.FLOAT_VECTOR,dim=1024)
                schema.add_field('text',DataType.VARCHAR,max_length=65535,enable_analyzer=True,analyzer_params={'type':'chinese'})
                schema.add_field('bm25_sparse',DataType.SPARSE_FLOAT_VECTOR)
                schema.add_field('content_hash',DataType.VARCHAR,max_length=64)
                schema.add_field('product_category',DataType.VARCHAR,max_length=64)
                schema.add_function(Function(name='text_bm25',input_field_names=['text'],output_field_names=['bm25_sparse'],function_type=FunctionType.BM25))
                index=self.client.prepare_index_params()
                index.add_index('embedding',index_type='AUTOINDEX',metric_type='COSINE')
                index.add_index('bm25_sparse',index_type='SPARSE_INVERTED_INDEX',metric_type='BM25')
                self.client.create_collection(self.collection,schema=schema,index_params=index,consistency_level='Strong')
            details=self.client.describe_collection(self.collection)
            fields={f['name']:f for f in details['fields']}
            if not {'chunk_id','embedding','text','bm25_sparse','content_hash','product_category'}<=fields.keys():raise ValueError('Hybrid schema mismatch')
            expected={'chunk_id':DataType.VARCHAR,'embedding':DataType.FLOAT_VECTOR,'text':DataType.VARCHAR,'bm25_sparse':DataType.SPARSE_FLOAT_VECTOR,'content_hash':DataType.VARCHAR,'product_category':DataType.VARCHAR}
            if any(fields[name].get('type')!=kind for name,kind in expected.items()):raise ValueError('Hybrid field type mismatch')
            if not fields['chunk_id'].get('is_primary'):raise ValueError('Hybrid primary key mismatch')
            if any(int(fields[name].get('params',{}).get('max_length',0))<size for name,size in {'chunk_id':64,'text':65535,'content_hash':64,'product_category':64}.items()):raise ValueError('Hybrid field capacity mismatch')
            if fields['embedding'].get('params',{}).get('dim') not in (1024,'1024'):raise ValueError('Dense dimension mismatch')
            functions=details.get('functions',[])
            if not any(f.get('name')=='text_bm25' and f.get('type')==FunctionType.BM25 and f.get('input_field_names')==['text'] and f.get('output_field_names')==['bm25_sparse'] for f in functions):raise ValueError('Missing native BM25 function')
            params=fields['text'].get('params',{})
            analyzer=params.get('analyzer_params',{})
            if isinstance(analyzer,str):analyzer=json.loads(analyzer)
            if analyzer.get('type')!='chinese':raise ValueError('Chinese analyzer required')
            if str(params.get('enable_analyzer','')).lower()!='true':raise ValueError('Text analyzer must be enabled')
            indexes={}
            for name in self.client.list_indexes(self.collection):
                item=self.client.describe_index(self.collection,name)
                indexes[item['field_name']]=item
            for field,metric,kind in [('embedding','COSINE','AUTOINDEX'),('bm25_sparse','BM25','SPARSE_INVERTED_INDEX')]:
                item=indexes.get(field,{})
                if item.get('metric_type')!=metric or item.get('index_type')!=kind:raise ValueError('Hybrid index metric/type mismatch')
            self.client.load_collection(self.collection)
        await asyncio.to_thread(setup)

    async def upsert(self,rows):
        if any(len(row['text'].encode('utf-8'))>65535 for row in rows):raise ValueError('Full text exceeds Milvus VARCHAR limit')
        result=await asyncio.to_thread(self.client.upsert,collection_name=self.collection,data=rows)
        return [str(id) for id in result['ids']]

    async def search(self,query,vector,category=None,strategy='hybrid',limit=100):
        expr=category_filter(category)
        options=dict(collection_name=self.collection,limit=limit,output_fields=['content_hash','product_category'],consistency_level='Strong')
        if strategy=='dense':
            result=await asyncio.to_thread(self.client.search,**options,data=[vector],anns_field='embedding',search_params={'metric_type':'COSINE'},filter=expr)
        elif strategy=='bm25':
            result=await asyncio.to_thread(self.client.search,**options,data=[query],anns_field='bm25_sparse',search_params={'metric_type':'BM25'},filter=expr)
        elif strategy in ('hybrid','hybrid_rerank'):
            reqs=[AnnSearchRequest(data=[vector],anns_field='embedding',param={'metric_type':'COSINE'},limit=50,expr=expr),AnnSearchRequest(data=[query],anns_field='bm25_sparse',param={'metric_type':'BM25'},limit=50,expr=expr)]
            result=await asyncio.to_thread(self.client.hybrid_search,**options,reqs=reqs,ranker=RRFRanker(k=60))
        else:raise ValueError('Unknown retrieval strategy')
        return result[0]

    async def delete(self,ids):
        if ids:await asyncio.to_thread(self.client.delete,collection_name=self.collection,ids=ids)

    async def drop_test_collection(self):
        if not self.collection.startswith('test_hybrid_'):raise ValueError('Only isolated test collections can be dropped')
        await asyncio.to_thread(self.client.drop_collection,self.collection)

    async def close(self):await asyncio.to_thread(self.client.close)
