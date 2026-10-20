import copy,hashlib
from sqlalchemy.exc import IntegrityError
from app.knowledge.hybrid_models import LowConfidenceQuestion,AnswerEvidence
from app.knowledge.models import KnowledgeChunk


def number_evidence(rows):return [dict(row,number=i+1) for i,row in enumerate(rows)]


def head_tail(rows):return rows[::2]+list(reversed(rows[1::2]))


class AuditRepository:
    def __init__(self,db):self.db=db

    async def record_low(self,question,cid,tid,entry,reason_code,reason):
        if entry not in ('retrieval','generation','system_error'):raise ValueError('Unknown low confidence entry')
        key=hashlib.sha256((cid+'\0'+tid+'\0'+entry).encode()).hexdigest()
        try:
            async with self.db.sessions() as s,s.begin():
                if not await s.get(LowConfidenceQuestion,key):
                    s.add(LowConfidenceQuestion(id=key,question=question,conversation_id=cid,turn_id=tid,entry=entry,reason_code=reason_code,reason=reason))
        except IntegrityError:
            async with self.db.sessions() as s:
                if not await s.get(LowConfidenceQuestion,key):raise
        return key

    async def save_evidence(self,cid,tid,snapshots):
        async with self.db.sessions() as s,s.begin():
            row=await s.get(AnswerEvidence,tid)
            if row is not None:
                if row.conversation_id!=cid or row.snapshots!=snapshots:raise ValueError('Evidence numbering is immutable for a turn')
                return
            s.add(AnswerEvidence(turn_id=tid,conversation_id=cid,snapshots=copy.deepcopy(snapshots)))

    async def get_evidence(self,tid,number):
        async with self.db.sessions() as s:
            row=await s.get(AnswerEvidence,tid)
            if not row:return None
            item=next((copy.deepcopy(x) for x in row.snapshots if x['number']==number),None)
            if not item:return None
            live=await s.get(KnowledgeChunk,item['chunk_id'])
            item['source_status']='removed' if not live or not live.is_active else ('current' if live.content_hash==item['content_hash'] else 'updated')
            return item
