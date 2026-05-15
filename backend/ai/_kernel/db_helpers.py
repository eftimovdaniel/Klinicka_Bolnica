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
