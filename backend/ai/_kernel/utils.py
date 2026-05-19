"""Заеднички формати за AI handler-и (време, датум, …)."""

from typing import Any


def format_vreme(v: Any) -> str:
    """time / timedelta / string → HH:MM."""
    if v is None:
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    return str(v)[:5]
