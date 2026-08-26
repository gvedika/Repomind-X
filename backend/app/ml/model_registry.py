from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime,timezone


class ModelRegistry:
    def __init__(self,root:Path=Path("artifacts/models")):
        self.root=root; self.root.mkdir(parents=True,exist_ok=True)
        self.index=self.root/"registry.json"
    def register(self,model_path:Path,model_name:str,metrics:dict)->dict:
        record={"model_name":model_name,"path":str(model_path),"metrics":metrics,"registered_at":datetime.now(timezone.utc).isoformat()}
        data=json.loads(self.index.read_text()) if self.index.exists() else []
        data.append(record); self.index.write_text(json.dumps(data,indent=2)); return record
