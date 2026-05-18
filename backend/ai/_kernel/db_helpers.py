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


_prijava_pk_col: str | None = None


def prijaveni_pk_column() -> str:
    """
    PK колона на prijaveni_lekari: `id_prijava` (постоечки DB) или `id` (schema.sql).
    """
    global _prijava_pk_col
    if _prijava_pk_col:
        return _prijava_pk_col
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SHOW COLUMNS FROM prijaveni_lekari")
        fields = [
            (r.get("Field") or r.get("field") or "")
            for r in (cur.fetchall() or [])
        ]
        cur.close()
        lower = {f.lower(): f for f in fields if f}
        if "id_prijava" in lower:
            _prijava_pk_col = lower["id_prijava"]
        elif "id" in lower:
            _prijava_pk_col = lower["id"]
        else:
            _prijava_pk_col = "id_prijava"
    except Exception as e:
        print(f"[db_helpers] prijaveni_pk_column: {e!r}")
        _prijava_pk_col = "id_prijava"
    finally:
        if conn:
            conn.close()
    return _prijava_pk_col


def prijaveni_select_sql(*, full: bool = False) -> str:
    """SELECT со `id` alias за унифициран dict (и со id_prijava во live DB)."""
    pk = prijaveni_pk_column()
    id_col = f"{pk} AS id" if pk.lower() != "id" else "id"
    cols = (
        f"{id_col}, pozicija, datum_prijava, id_oglas, email, "
        "ime_lekar, prezime_lekar"
    )
    if full:
        cols += ", broj_med_licenca, telefon"
    return f"SELECT {cols} FROM prijaveni_lekari"


def prijaveni_order_desc() -> str:
    pk = prijaveni_pk_column()
    return f" ORDER BY datum_prijava DESC, {pk} DESC"


def prijaveni_row_id(row: dict[str, Any]) -> int:
    for key in ("id", "id_prijava", "ID"):
        val = row.get(key)
        if val is not None:
            return int(val)
    raise ValueError(f"Нема PK во ред: {row!r}")
