import json
import os
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "ai_system_prompts.json"


def get_prompts_path() -> Path:
    p = (os.getenv("AI_PROMPTS_FILE") or "").strip()
    if p:
        return Path(p).expanduser()
    return _DEFAULT


def load_ai_prompts() -> dict:
    path = get_prompts_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def get_section(key: str, subkey: str = "system") -> str:
    data = load_ai_prompts()
    block = data.get(key) or {}
    if isinstance(block, dict):
        return str(block.get(subkey) or "").strip()
    return str(block or "").strip()
