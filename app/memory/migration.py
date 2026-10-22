"""Additive, explicitly versioned migration; old messages are never deleted."""
from sqlalchemy import inspect,text

async def migrate(db):
    async with db.engine.connect() as conn:
        acquired=(await conn.execute(text("SELECT GET_LOCK('support_ch07_schema',30)"))).scalar()
        if acquired!=1:raise RuntimeError('schema migration busy')
        try:
            await conn.commit()
            for table,fields in {
                'conversations':{'summary_upto_msg_id':'INT NOT NULL DEFAULT 0','layer1_from_msg_id':'INT NULL','context_version':'INT NOT NULL DEFAULT 0'},
                'messages':{'message_key':'VARCHAR(128) NULL'},
            }.items():
                columns=await conn.run_sync(lambda c:{x['name'] for x in inspect(c).get_columns(table)})
                for name,ddl in fields.items():
                    if name not in columns:await conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
            indexes=await conn.run_sync(lambda c:{x['name'] for x in inspect(c).get_indexes('messages')})
            if 'uq_memory_message' not in indexes:await conn.execute(text('CREATE UNIQUE INDEX uq_memory_message ON messages(conversation_id,message_key)'))
            await conn.execute(text("UPDATE messages SET message_key=CONCAT('legacy:',id) WHERE message_key IS NULL"))
            await conn.commit()
        finally:
            await conn.execute(text("SELECT RELEASE_LOCK('support_ch07_schema')"));await conn.commit()
