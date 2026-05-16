"""
Преглед на апликанти за оглас (само за директор).

Примери:
- „Покажи ми ги апликантите за хирург"
- „Кој се аплицирал за кардиолог?"
- „Аплицирани кандидати за анестезиолог"
- „Сите апликанти" (без позиција – ги враќа сите)
- „Апликанти за оглас 42" (по ID на оглас)

Користи табела `prijaveni_lekari`.
"""

from ai._kernel.prompt_loader import load_prompt
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.auth import require_direktor
from ai._kernel.db_helpers import as_dict, db_cursor
from ai._kernel.groq_client import ask_ai


def _izvlechi(prashanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prashanje}\"", system_prompt=load_prompt("direktor_aplikanti_oglas"))
    print(f"[aplikanti] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="aplikanti_oglas")


def _format_datum(d) -> str:
    if not d:
        return "—"
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y %H:%M")
    return str(d)[:16]


def odgovori_za_aplikanti(prashanje: str, lekar: dict | None) -> str:
    if err := require_direktor(lekar):
        return err

    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    pozicija = (podatoci.get("pozicija") or "").strip() or None
    id_oglas = podatoci.get("id_oglas")
    try:
        id_oglas = int(id_oglas) if id_oglas else None
    except (ValueError, TypeError):
        id_oglas = None

    try:
        with db_cursor() as (_, cur):
            sql = (
                "SELECT id, id_oglas, pozicija, ime_lekar, prezime_lekar, "
                "       broj_med_licenca, email, telefon, datum_prijava "
                "FROM prijaveni_lekari "
                "WHERE 1=1"
            )
            params: list = []

            if id_oglas:
                sql += " AND id_oglas = %s"
                params.append(id_oglas)
            elif pozicija:
                sql += " AND LOWER(TRIM(pozicija)) LIKE %s"
                params.append(f"%{pozicija.strip().lower()}%")

            sql += " ORDER BY datum_prijava DESC"
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
    except Exception as e:
        print(f"[aplikanti] DB greshka: {e}")
        return "Се случи грешка при вчитувањето на апликантите. Те молам обиди се повторно."

    if not rows:
        if id_oglas:
            return f"Нема апликанти за оглас со ID {id_oglas}."
        if pozicija:
            return f'Нема апликанти за позицијата „{pozicija}".'
        return "Нема апликанти во системот."

    naslov_filtri = []
    if id_oglas:
        naslov_filtri.append(f"оглас #{id_oglas}")
    if pozicija:
        naslov_filtri.append(f'„{pozicija}"')
    naslov_suffix = (" (" + ", ".join(naslov_filtri) + ")") if naslov_filtri else ""
    naslov = f"Апликанти ({len(rows)}){naslov_suffix}:"

    redovi = [naslov, ""]
    for raw in rows:
        r = as_dict(raw)
        ime = (r.get("ime_lekar") or "").strip()
        prezime = (r.get("prezime_lekar") or "").strip()
        polno = f"{ime} {prezime}".strip() or "—"
        poz = (r.get("pozicija") or "").strip() or "—"
        email = (r.get("email") or "").strip() or "—"
        tel = r.get("telefon") or "—"
        lic = r.get("broj_med_licenca") or "—"
        kogo = _format_datum(r.get("datum_prijava"))
        oglas_ref = r.get("id_oglas")
        oglas_str = f" | оглас #{oglas_ref}" if oglas_ref else ""

        red = (
            f"• {polno} – {poz}{oglas_str}\n"
            f"   Email: {email} | Тел: {tel} | Лиценца: {lic}\n"
            f"   Пријавен: {kogo}"
        )
        redovi.append(red)

    return "\n".join(redovi)
