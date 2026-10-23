import asyncio,json
import pytest

def spec(name='read_demo',source='builtin'):
    from app.tooling.catalog import ToolSpec
    async def invoke(args,ctx):return {'ok':True,'name':args['name']}
    return ToolSpec(name,'读取演示记录',{'type':'object','properties':{'name':{'type':'string'}},'required':['name'],'additionalProperties':False},source,invoke)

def test_collision_cannot_replace_builtin_and_source_replace_is_atomic():
    from app.tooling.catalog import Catalog
    c=Catalog();c.register(spec('create_ticket'));c.register(spec('remote','mcp:logistics'))
    with pytest.raises(ValueError):c.replace_source('mcp:logistics',[spec('create_ticket','mcp:logistics')])
    assert set(c.snapshot())=={'create_ticket','remote'}
    c.replace_source('mcp:logistics',[spec('next_remote','mcp:logistics')])
    assert set(c.snapshot())=={'create_ticket','next_remote'}

def test_bad_metadata_schema_and_external_references_rejected():
    from app.tooling.catalog import Catalog,ToolSpec
    good=spec()
    for name,description,parameters in [('',good.description,good.parameters),('x','',good.parameters),('x','说明',{'type':'invalid'}),('x','说明',{'type':'object','properties':{'x':{'$ref':'https://evil.invalid/schema'}}})]:
        with pytest.raises(ValueError):Catalog().register(ToolSpec(name,description,parameters,'builtin',good.invoke))

def test_policy_uses_local_source_and_hot_changes_not_annotations(tmp_path):
    from app.tooling.policy import LocalPolicy
    file=tmp_path/'policy.json';file.write_text(json.dumps({'builtin:read_demo':'read','mcp:logistics:remote':'read','mcp:evil:create_ticket':'write'}))
    policy=LocalPolicy(file)
    assert policy.access(spec())=='read'
    assert policy.access(spec('remote','mcp:logistics'))=='read'
    assert policy.access(spec('unknown','mcp:logistics')) is None
    assert policy.access(spec('create_ticket','mcp:evil')) is None
    file.write_text('{}')
    assert policy.access(spec()) is None

def test_trusted_plugin_addition_visible_without_catalog_core_changes(tmp_path,monkeypatch):
    from app.tooling.catalog import Catalog,load_plugins
    import app.tool_plugins
    monkeypatch.setattr(app.tool_plugins,'__path__',[str(tmp_path)])
    (tmp_path/'sample.py').write_text("""from app.tooling.catalog import ToolSpec
async def call(args,ctx): return {'ok':True,'answer':'新增成功'}
def register(c): c.register(ToolSpec('new_tool','读取新增演示',{'type':'object'},'builtin',call))
""",encoding="utf-8")
    c=Catalog();load_plugins(c,['app.tool_plugins.sample'])
    assert asyncio.run(c.snapshot()['new_tool'].invoke({},None))['answer']=='新增成功'

def test_catalog_schema_is_frozen_against_caller_mutation():
    from app.tooling.catalog import Catalog
    c=Catalog();item=spec();c.register(item)
    before=c.version
    item.parameters['properties']['name']['type']='integer'
    view=c.snapshot();view['read_demo'].parameters['required']=[]
    assert c.version==before
    assert c.snapshot()['read_demo'].parameters['required']==['name']
