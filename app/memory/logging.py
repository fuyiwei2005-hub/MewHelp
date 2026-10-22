import json,logging
from datetime import datetime,UTC
from pathlib import Path
from logging.handlers import RotatingFileHandler
from app.config import ROOT

class ContextLogger:
    def __init__(self,path='log/app.log'):
        target=Path(path)
        if not target.is_absolute():target=ROOT/target
        target.parent.mkdir(parents=True,exist_ok=True)
        self.logger=logging.getLogger('memory.'+str(target.resolve()));self.logger.setLevel(logging.INFO);self.logger.propagate=False
        if not self.logger.handlers:
            handler=RotatingFileHandler(target,maxBytes=20_000_000,backupCount=10,encoding='utf-8');handler.setFormatter(logging.Formatter('%(message)s'));self.logger.addHandler(handler)
    def event(self,event,**data):self.logger.info(json.dumps(dict(time=datetime.now(UTC).isoformat(),event=event,**data),ensure_ascii=False,default=str))
