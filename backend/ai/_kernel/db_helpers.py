"""Безбедно работење со MySQL во AI модули."""

from contextlib import contextmanager
from typing import Any, Iterator, cast

from database import get_connection


@contextmanager
def db_cursor(*, dictionary: bool = True, commit: bool = False) -> Iterator[tuple[Any, Any]]:
    """
    Контекст: (conn, cur). При грешка → rollback.
    commit=True само кога handler-от не прави сопствен commit.
    """
    conn = get_connection()
    cur = conn.cursor(dictionary=dictionary)
    try:
        yield conn, cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def as_dict(row: object) -> dict[str, Any]:
    """Ред од cursor(dictionary=True) → dict за Pylance и .get()."""
    return cast(dict[str, Any], row)


def fetch_one(cur: Any) -> dict[str, Any] | None:
    """fetchone() → dict или None (dictionary курсор)."""
    row = cur.fetchone()
    return as_dict(row) if row else None


def fetch_all(cur: Any) -> list[dict[str, Any]]:
    """fetchall() → листа dict (dictionary курсор)."""
    rows = cur.fetchall() or []
    return [as_dict(r) for r in rows]


def normalize_int(value: Any) -> int | None:
    """AI/JSON вредност → int или None."""
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def ai_error_text(podatoci: dict[str, Any]) -> str | None:
    """Ако parse_ai_json вратил _error, врати текст; инаку None."""
    err = podatoci.get("_error")
    if err is None:
        return None
    return str(err).strip() or "Привремена грешка од AI."
