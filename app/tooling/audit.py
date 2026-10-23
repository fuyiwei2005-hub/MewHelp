from sqlalchemy.dialects.mysql import insert
from .engine import digest
from .models import ToolAuditLog

class ToolAudit:
    def __init__(self,db):self.db=db
    async def upsert(self,row):
        key=digest([row['conversation_id'],row['tool_call_id'],row['source']])
        values=dict(row,id=key)
        stmt=insert(ToolAuditLog).values(**values)
        async with self.db.sessions() as s,s.begin():
            await s.execute(stmt.on_duplicate_key_update(**{k:v for k,v in values.items() if k!='id'}))
