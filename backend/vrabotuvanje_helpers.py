"""
Заеднички филтер за „активни" огласи во Vrabotuvanje.

Публично (сајт, AI чат): само огласи со важечки рок и статус активен.
Админ панелот може да ги гледа сите преку посебен endpoint.
"""
from typing import Any

# Публично: активен/валиден статус + рок за пријава не е поминат.
# Не се прикажуваат: завршен, истечен, или истечен datum_na_prijavuvanje.
SQL_AKTIVNI_OGLASI = """
    SELECT id_oglas, pozicija, oddel, datum_na_prijavuvanje, status_oglas
    FROM Vrabotuvanje
    WHERE LOWER(TRIM(COALESCE(status_oglas, ''))) NOT IN ('завршен', 'истечен', 'zavrshen', 'istecen')
      AND (
        status_oglas IS NULL
        OR TRIM(status_oglas) = ''
        OR LOWER(TRIM(status_oglas)) IN ('активен', 'aktiven', 'валиден', 'validen')
      )
      AND (datum_na_prijavuvanje IS NULL OR datum_na_prijavuvanje >= CURDATE())
    ORDER BY datum_na_prijavuvanje ASC
"""


def format_rok_datum(d: Any) -> str:
    if not d:
        return "—"
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y")
    return str(d)[:10]


def row_to_oglas_public(r: dict[str, Any]) -> dict[str, Any]:
    """Формат за GET /kariera и AI навигација."""
    return {
        "id_oglas": r.get("id_oglas"),
        "naslov": (r.get("pozicija") or "").strip(),
        "opis": (r.get("oddel") or "").strip(),
        "rok": format_rok_datum(r.get("datum_na_prijavuvanje")),
        "pozicija": (r.get("pozicija") or "").strip(),
        "oddel": (r.get("oddel") or "").strip(),
    }


def fetch_aktivni_oglasi_rows(cur) -> list[dict[str, Any]]:
    cur.execute(SQL_AKTIVNI_OGLASI)
    return list(cur.fetchall() or [])
