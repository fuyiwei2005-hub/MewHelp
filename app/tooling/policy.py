"""Permissions come exclusively from our local deployment configuration."""
import json
from pathlib import Path

class LocalPolicy:
    def __init__(self,path):self.path=Path(path)
    def load(self):
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError):return {}
    def access(self,spec):
        mode=self.load().get(spec.source+':'+spec.name)
        if mode=='write' and (spec.source,spec.name)!=('builtin','create_ticket'):return None
        return mode if mode in ('read','write') else None
