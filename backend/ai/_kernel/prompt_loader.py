"""
Вчитување на AI prompts од еден фајл: backend/data/agent_prompts.txt

Секција:
  @@@ chat_system @@@
  (текст на промптот)

Handler .py фајловите повикуваат load_prompt("chat_system").
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_BUNDLE_PATH = Path(__file__).resolve().parents[2] / "data" / "agent_prompts.txt"
_LEGACY_DIR = Path(__file__).resolve().parents[2] / "data" / "prompts"
_SECTION_RE = re.compile(r"^@@@\s*([a-zA-Z0-9_]+)\s*@@@\s*$", re.MULTILINE)


def _parse_bundle(text: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return parts
    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            parts[name] = body
    return parts


@lru_cache(maxsize=1)
def _all_prompts() -> dict[str, str]:
    if not _BUNDLE_PATH.is_file():
        raise FileNotFoundError(f"Нема bundle фајл: {_BUNDLE_PATH}")
    return _parse_bundle(_BUNDLE_PATH.read_text(encoding="utf-8"))


def load_prompt(name: str) -> str:
    """Враќа текст за дадена секција од agent_prompts.txt."""
    prompts = _all_prompts()
    if name in prompts:
        return prompts[name]
    # Фолбек: постар посебен .txt (ако постои)
    legacy = _LEGACY_DIR / f"{name}.txt"
    if legacy.is_file():
        return legacy.read_text(encoding="utf-8").strip()
    known = ", ".join(sorted(prompts.keys())[:8])
    raise KeyError(
        f"Prompt '{name}' не постои во {_BUNDLE_PATH.name}. "
        f"Додај секција: @@@ {name} @@@\n"
        f"Познати (првите): {known}…"
    )


def load_prompt_template(name: str, **kwargs: str) -> str:
    """Шаблон со {{placeholders}} — за {lista} во JSON користи двојни {{ }} во текстот."""
    return load_prompt(name).format(**kwargs)


def list_prompt_names() -> list[str]:
    """Имиња на сите секции во bundle-от."""
    return sorted(_all_prompts().keys())


def prompts_bundle_path() -> Path:
    return _BUNDLE_PATH


def reload_prompts() -> None:
    """По уредување на agent_prompts.txt во развој (рестартирај или повикај reload)."""
    _all_prompts.cache_clear()
