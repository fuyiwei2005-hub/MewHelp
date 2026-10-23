"""Trusted registrations plus immutable per-turn tool descriptions."""
import copy,hashlib,importlib,json,re
from dataclasses import dataclass,replace
from jsonschema import Draft202012Validator

@dataclass(frozen=True)
class ToolSpec:
    name:str
    description:str
    parameters:dict
    source:str
    invoke:object
    project:object=None
    timeout:float|None=None
    def descriptor(self):
        return dict(name=self.name,description=self.description,parameters=copy.deepcopy(self.parameters),source=self.source)

def validate_spec(spec):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,63}',spec.name) or not spec.description.strip() or not spec.source or not callable(spec.invoke):
        raise ValueError('invalid_tool_metadata')
    if not isinstance(spec.parameters,dict) or spec.parameters.get('type')!='object':raise ValueError('object_schema_required')
    def references(value):
        if isinstance(value,dict):
            if '$ref' in value and not value['$ref'].startswith('#/'):raise ValueError('external_schema_reference')
            for item in value.values():references(item)
        elif isinstance(value,list):
            for item in value:references(item)
    references(spec.parameters)
    try:Draft202012Validator.check_schema(spec.parameters)
    except Exception as error:raise ValueError('invalid_tool_schema') from error

class Catalog:
    def __init__(self):self._tools={}
    def register(self,spec):
        validate_spec(spec)
        if spec.name in self._tools:raise ValueError('tool_name_collision:'+spec.name)
        self._tools[spec.name]=replace(spec,parameters=copy.deepcopy(spec.parameters))
    def replace_source(self,source,specs):
        next_tools={k:v for k,v in self._tools.items() if v.source!=source}
        for spec in specs:
            validate_spec(spec)
            if spec.source!=source or spec.name in next_tools:raise ValueError('tool_source_or_name_collision')
            next_tools[spec.name]=replace(spec,parameters=copy.deepcopy(spec.parameters))
        self._tools=next_tools
    def snapshot(self):return {k:replace(v,parameters=copy.deepcopy(v.parameters)) for k,v in sorted(self._tools.items())}
    @property
    def version(self):
        return hashlib.sha256(json.dumps([t.descriptor() for t in self.snapshot().values()],ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def load_plugins(catalog,modules):
    importlib.invalidate_caches()
    for name in modules:
        if not isinstance(name,str) or not name.startswith('app.tool_plugins.') or not re.fullmatch(r'[A-Za-z0-9_.]+',name):raise ValueError('untrusted_plugin_module')
        importlib.import_module(name).register(catalog)
