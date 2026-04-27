import json
import os
from pathlib import Path
from typing import Any

def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def write_json_atomic(path: Path, data: dict[str, Any]):
    temp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp, path)
