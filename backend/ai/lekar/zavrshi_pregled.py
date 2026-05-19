"""
Завршување преглед од лекар - UPDATE status_pregled = 'завршен'.

Достапно за СЕКОЈ најавен лекар (не само директор).

Примери:
- „Заврши го прегледот на Петар Иванов"
- „Заврши го утрешниот преглед на Иванов"
- „Заврши преглед ID 42"
- „Заврши го прегледот на Иванов со дијагноза: грип, терапија: парацетамол 3x"

Лекарот може да заврши САМО свои прегледи.
"""

import re
from datetime import date, datetime

from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.auth import require_lekar
from ai._kernel.groq_helpers import izvlechi_json_so_ai
from ai._kernel.prompt_helpers import today_prompt_line
from ai._kernel.transliteracija import transliterijaj
from ai._kernel.utils import format_datum_i_vreme

_RE_TERMIN_ID = re.compile(r"\bID\s*(\d+)\b", re.IGNORECASE | re.UNICODE)
_RE_ZAVRSI_ZATVORI = re.compile(
    r"\b(заврш\w*|zavrsh\w*|затвор\w*|zatvor\w*|затвот\w*)\b",
    re.IGNORECASE | re.UNICODE,
)
_RE_DX = re.compile(
    r"(?:дијагноза|dijagnoza)\s*:\s*(.+?)(?=\s+и\s+(?:терапија|terapija)|(?:терапија|terapija)\s*:|$)",
    re.IGNORECASE | re.UNICODE | re.DOTALL,
)
_RE_TX = re.compile(
    r"(?:терапија|terapija)\s*:\s*(.+)$",
    re.IGNORECASE | re.UNICODE | re.DOTALL,
)
_RE_DX_SO = re.compile(
    r"со\s+дијагноза\s*[:/]?\s*(.+?)(?=\s+и\s+терапија|\s*$)",
    re.IGNORECASE | re.UNICODE | re.DOTALL,
)
_RE_TX_SO = re.compile(
    r"(?:и\s+)?терапија\s*[:/]?\s*(.+?)\s*$",
    re.IGNORECASE | re.UNICODE | re.DOTALL,
)
_RE_PACIENT_POSLE_NA = re.compile(
    r"(?:термин(?:от)?|преглед(?:от)?)\s+на\s+"
    r"([A-Za-zА-Яа-яЁёІіЇїЈјЉљЊњЋћЏџ][\w\-']+(?:\s+[A-Za-zА-Яа-яЁёІіЇїЈјЉљЊњЋћЏџ][\w\-']+){0,2})"
    r"\s+(?:со|за|на\s)",
    re.IGNORECASE | re.UNICODE,
)


PROMPT = """
Ти си систем што извлекува податоци за завршување медицински прегледи.

Корисникот е лекар и сака да означи еден или повеќе прегледи како „завршени". Врати САМО JSON:
{"termin_ids": [42, 43] | null, "ime_pacient": "Име Презиме" | null,
 "datum": "YYYY-MM-DD" | null, "site": true | false,
 "dijagnoza": "текст" | null, "terapija": "текст" | null}

Правила:
- ако корисникот спомне „ID 42", „термин 42" → "termin_ids"=[42].
- ако спомне повеќе ID (пр. „1, 2, 3" или „42 и 43") → "termin_ids"=[1,2,3].
- ако спомне „сите", „сите мои", „сите денешни" → "site"=true.
- ако спомне име на пациент → "ime_pacient"=име+презиме.
- датум: „денес"=денешен, „утре"=денес+1, „вчера"=денес-1, „понеделник"... = најблиски тој ден.
- ако корисникот спомне „дијагноза: X" или „dx: X" → "dijagnoza"=X.
- ако корисникот спомне „терапија: Y" или „tx: Y" → "terapija"=Y.
- ако нема ништо јасно → сите вредности null/false.

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def prasanje_e_zavrshi_pregled(prasanje: str) -> bool:
    """Заврши/затвори преглед/термин — не info_lekar (пациент ≠ лекар)."""
    if not prasanje or not prasanje.strip():
        return False
    p = transliterijaj(prasanje).lower()
    ima_akcija = bool(_RE_ZAVRSI_ZATVORI.search(p))
    ima_termin = bool(
        re.search(r"\b(преглед|pregled|термин|termin)\b", p, re.UNICODE)
    )
    ima_dx_tx = bool(
        re.search(r"\b(дијагноз|dijagnoz|терап|terap)\b", p, re.UNICODE)
    )
    if ima_akcija and ima_termin:
        return True
    if ima_akcija and re.search(
        r"\bна\s+[a-zа-я]", p, re.UNICODE
    ):
        return True
    if _RE_DX.search(prasanje) and _RE_TX.search(prasanje):
        return True
    if ima_akcija and (_RE_DX.search(prasanje) or _RE_DX_SO.search(prasanje)):
        return True
    if ima_akcija and ima_dx_tx:
        return True
    return False


def _ocisti_dx_tx_vrednost(s: str | None) -> str | None:
    if not s:
        return None
    t = s.strip().strip(" ,").strip("/").strip()
    if not t or t in ("/", "—", "-", "…"):
        return None
    return t


def _izvlechi_dx_tx_lokalno(prasanje: str) -> tuple[str | None, str | None]:
    dx = tx = None
    m_dx = _RE_DX.search(prasanje)
    if m_dx:
        dx = _ocisti_dx_tx_vrednost(m_dx.group(1))
    m_tx = _RE_TX.search(prasanje)
    if m_tx:
        tx = _ocisti_dx_tx_vrednost(m_tx.group(1))
    if not dx:
        m = _RE_DX_SO.search(prasanje)
        if m:
            dx = _ocisti_dx_tx_vrednost(m.group(1))
    if not tx:
        m = _RE_TX_SO.search(prasanje)
        if m:
            tx = _ocisti_dx_tx_vrednost(m.group(1))
    return dx, tx


def _izvlechi_ime_pacient_lokalno(prasanje: str) -> str | None:
    """„терминот на Daniel Eftimov со …" → име на пациент."""
    m = _RE_PACIENT_POSLE_NA.search(prasanje)
    if m:
        return m.group(1).strip()
    for pat in (
        r"(?:преглед|pregled|термин|termin)(?:от)?\s+на\s+"
        r"([A-Za-zА-Яа-яЁёІіЇї][\w\-']+(?:\s+[A-Za-zА-Яа-яЁёІіЇї][\w\-']+){0,2})"
        r"\s+(?:со|за)",
        r"\bна\s+"
        r"([A-Za-zА-Яа-яЁёІіЇї][\w\-']+(?:\s+[A-Za-zА-Яа-яЁёІіЇї][\w\-']+){0,2})"
        r"\s+со\b",
    ):
        m = re.search(pat, prasanje, re.IGNORECASE | re.UNICODE)
        if m:
            ime = m.group(1).strip()
            if len(ime) >= 3:
                return ime
    return None


def _like_variants_ime(word: str) -> list[str]:
    """Латиница + кирилица за пребарување во ime_pacient."""
    w = (word or "").strip().lower()
    if len(w) < 2:
        return []
    out: set[str] = {w}
    cyr = transliterijaj(word).strip().lower()
    if cyr and cyr != w:
        out.add(cyr)
    return list(out)


def _sql_filter_ime_pacient(ime_pacient: str) -> tuple[str, list]:
    """
    (AND clause, params) — прво+последно име, латиница/кирилица, и обратен ред.
    """
    delovi = [d for d in ime_pacient.strip().split() if len(d) >= 2]
    if not delovi:
        return "", []

    if len(delovi) == 1:
        vars_ = _like_variants_ime(delovi[0])
        if not vars_:
            return "", []
        clause = " AND (" + " OR ".join(["LOWER(ime_pacient) LIKE %s"] * len(vars_)) + ")"
        return clause, [f"%{v}%" for v in vars_]

    first, last = delovi[0], delovi[-1]
    v_first = _like_variants_ime(first)
    v_last = _like_variants_ime(last)

    def _and_pair(va: list[str], vb: list[str]) -> tuple[str, list]:
        p: list = []
        parts: list[str] = []
        for a in va:
            parts.append("LOWER(ime_pacient) LIKE %s")
            p.append(f"%{a}%")
        for b in vb:
            parts.append("LOWER(ime_pacient) LIKE %s")
            p.append(f"%{b}%")
        return "(" + " AND ".join(parts) + ")", p

    fwd, p_fwd = _and_pair(v_first, v_last)
    rev, p_rev = _and_pair(v_last, v_first)
    return " AND (" + fwd + " OR " + rev + ")", p_fwd + p_rev


def _status_zakazan_sql() -> str:
    return (
        "COALESCE(NULLIF(TRIM(status_pregled), ''), 'закажан') = 'закажан'"
    )


def _termin_id_od_prasanje(prasanje: str) -> int | None:
    m = _RE_TERMIN_ID.search(prasanje or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _termin_ids_od_kontekst(kontekst: dict | None) -> list[int]:
    if not isinstance(kontekst, dict):
        return []
    raw = kontekst.get("last_raspored_termin_ids")
    if not isinstance(raw, list):
        return []
    ids: list[int] = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    return ids


def _izvlechi_lokalno(prasanje: str) -> dict:
    """Без Groq — regex + контекст (работи и при 429 / GROQ_DISABLED)."""
    from ai.pacient.moi_pregledi import datum_za_pregledi_od_prasanje

    p = transliterijaj(prasanje).lower()
    dx, tx = _izvlechi_dx_tx_lokalno(prasanje)
    podatoci: dict = {
        "termin_ids": None,
        "ime_pacient": _izvlechi_ime_pacient_lokalno(prasanje),
        "datum": None,
        "site": bool(
            _RE_ZAVRSI_ZATVORI.search(p)
            and any(x in p for x in ("сите", "site", "all", "комплетн"))
        ),
        "dijagnoza": dx,
        "terapija": tx,
    }
    tid = _termin_id_od_prasanje(prasanje)
    if tid is not None:
        podatoci["termin_ids"] = [tid]
    d = datum_za_pregledi_od_prasanje(prasanje)
    if d:
        podatoci["datum"] = d.isoformat()
    return podatoci


def _izvlechi(prasanje: str) -> dict:
    from ai._kernel.groq_helpers import groq_zadolzhitelen

    if msg := groq_zadolzhitelen():
        return {"_error": msg}

    full = f'{today_prompt_line()}\n\nПрашање: "{prasanje}"\nВрати JSON.'
    podatoci = izvlechi_json_so_ai(full, PROMPT, log_tag="zavrshi_pregled")
    if podatoci.get("_error"):
        return podatoci
    tid = _termin_id_od_prasanje(prasanje)
    if tid is not None and not podatoci.get("termin_ids"):
        podatoci["termin_ids"] = [tid]
    return podatoci


def _najdi_termin(
    doctor_id: int,
    termin_id: int | None,
    ime_pacient: str | None,
    datum_str: str | None,
    *,
    samo_zakazani: bool = True,
) -> list[dict]:
    """Термини на лекарот — по ID, име (лат/кир) или датум."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if termin_id:
        cur.execute(
            "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled, status_pregled"
            " FROM Termin_pregled WHERE termin_ID = %s AND doctor_ID = %s",
            (termin_id, doctor_id),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows

    sql = (
        "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled, status_pregled"
        " FROM Termin_pregled WHERE doctor_ID = %s"
    )
    params: list = [doctor_id]

    if samo_zakazani:
        sql += f" AND {_status_zakazan_sql()}"

    if datum_str:
        sql += " AND datum_pregled = %s"
        params.append(datum_str)

    if ime_pacient:
        clause, clause_params = _sql_filter_ime_pacient(ime_pacient)
        if clause:
            sql += clause
            params.extend(clause_params)
        if "@" in ime_pacient:
            sql += " AND LOWER(TRIM(email_pacient)) = LOWER(TRIM(%s))"
            params.append(ime_pacient.strip())

    sql += " ORDER BY datum_pregled, vreme_pregled"
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _poraka_ne_najden_termin(doctor_id: int, ime: str | None) -> str:
    """Помошна порака — слични имиња или погрешен статус."""
    base = "Не најдов соодветен закажан преглед кај тебе."
    if not ime:
        return (
            base
            + '\n\nПровери "Мој распоред" или наведи "Заврши термин ID …".'
        )

    site = _najdi_termin(doctor_id, None, ime, None, samo_zakazani=False)
    if not site:
        return (
            base
            + f'\n\nНемам термин за "{ime}" на твојот распоред.\n'
            'Провери правопис (латиница/кирилица) или ID од "Мој распоред".'
        )

    zakazani = [
        r
        for r in site
        if (r.get("status_pregled") or "закажан").strip() == "закажан"
    ]
    if zakazani:
        return base

    linii = [
        base,
        "",
        f'Имам преглед за "{ime}", но не е со статус "закажан":',
    ]
    for r in site[:5]:
        st = (r.get("status_pregled") or "—").strip()
        linii.append(
            f"• ID {r['termin_ID']}: {r['ime_pacient']} — "
            f"{format_datum_i_vreme(r['datum_pregled'], r['vreme_pregled'])} (статус: {st})"
        )
    linii.append(
        "\nАко сакате да го ажурирате, наведете ID или контактирајте админ."
    )
    return "\n".join(linii)


def _prazna_dx_tx(v: str | None) -> bool:
    if v is None:
        return True
    t = str(v).strip()
    return not t or t in ("/", "—", "-", "…", ".", "n/a", "N/A", "нема", "none")


def _zavrshi(termin_id: int, dijagnoza: str | None, terapija: str | None) -> None:
    """Маркира преглед како завршен. Опционо запишува dx/tx."""
    conn = get_connection()
    cur = conn.cursor()
    sets = ["status_pregled = 'завршен'"]
    params: list = []
    if dijagnoza and not _prazna_dx_tx(dijagnoza):
        sets.append("dijagnoza = %s")
        params.append(dijagnoza)
    if terapija and not _prazna_dx_tx(terapija):
        sets.append("terapija = %s")
        params.append(terapija)
    params.append(termin_id)
    cur.execute(
        f"UPDATE Termin_pregled SET {', '.join(sets)} WHERE termin_ID = %s",
        params,
    )
    conn.commit()
    cur.close()
    conn.close()


def _najdi_site_zakazani(doctor_id: int, datum_str: str | None) -> list[dict]:
    """Сите закажани прегледи на лекарот (опционо филтрирани по датум)."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    sql = (
        "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled, status_pregled"
        f" FROM Termin_pregled WHERE doctor_ID = %s AND {_status_zakazan_sql()}"
    )
    params: list = [doctor_id]
    if datum_str:
        sql += " AND datum_pregled = %s"
        params.append(datum_str)
    sql += " ORDER BY datum_pregled, vreme_pregled"
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _zavrshi_mnogu(rows: list[dict], dijagnoza: str | None, terapija: str | None) -> str:
    """Заврши повеќе прегледи и врати резиме."""
    if not rows:
        return "Нема закажани прегледи за завршување."

    uspesni = 0
    preskoknati = 0
    for r in rows:
        if r["status_pregled"] != "закажан":
            preskoknati += 1
            continue
        _zavrshi(r["termin_ID"], dijagnoza, terapija)
        uspesni += 1

    linii = [f"Завршени {uspesni} прегледи."]
    if preskoknati:
        linii.append(f'Прескокнати {preskoknati} (веќе немаа статус „закажан").')

    linii.append("")
    linii.append("Детали:")
    for r in rows:
        if r["status_pregled"] != "закажан":
            continue
        linii.append(
            f"• ID {r['termin_ID']}: {r['ime_pacient']} ({format_datum_i_vreme(r['datum_pregled'], r['vreme_pregled'])})"
        )
    return "\n".join(linii)


def odgovori_za_zavrshi(
    prasanje: str, lekar: dict | None, kontekst: dict | None = None
) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_lekar(lekar):
        return err

    doctor_id = lekar["doctor_ID"]

    termin_ids: list[int] = []
    tid = _termin_id_od_prasanje(prasanje)
    if tid is not None:
        termin_ids = [tid]

    podatoci = _izvlechi(prasanje)
    if podatoci.get("_error"):
        return str(podatoci["_error"])

    dijagnoza = (podatoci.get("dijagnoza") or "").strip() or None
    terapija = (podatoci.get("terapija") or "").strip() or None

    if termin_ids and (_prazna_dx_tx(dijagnoza) or _prazna_dx_tx(terapija)):
        parts = []
        if _prazna_dx_tx(dijagnoza):
            parts.append("дијагноза")
        if _prazna_dx_tx(terapija):
            parts.append("терапија")
        return (
            "За да го завршам прегледот, наведете вистинска "
            + " и ".join(parts)
            + ' (не само "/" или празно). Пример:\n'
            '"Затвори го прегледот со Дијагноза: Мигрена, и терапија: Аналгетик".'
        )

    if not termin_ids:
        ai_ids = podatoci.get("termin_ids") or []
        if isinstance(ai_ids, int):
            ai_ids = [ai_ids]
        try:
            termin_ids = [int(x) for x in ai_ids if x is not None]
        except (TypeError, ValueError):
            termin_ids = []

    if not termin_ids:
        ctx_ids = _termin_ids_od_kontekst(kontekst)
        if len(ctx_ids) == 1:
            termin_ids = ctx_ids

    ime = (podatoci.get("ime_pacient") or "").strip()
    datum_str = podatoci.get("datum")
    site = bool(podatoci.get("site"))

    # СЛУЧАЈ 1: „сите" / „сите денешни"
    if site:
        rows = _najdi_site_zakazani(doctor_id, datum_str)
        if not rows:
            kade = " за тој датум" if datum_str else ""
            return f"Немаш закажани прегледи{kade}."
        return _zavrshi_mnogu(rows, dijagnoza, terapija)

    # СЛУЧАЈ 2: листа на конкретни ID-а
    if termin_ids:
        rows = []
        nepostoekji: list[int] = []
        for tid in termin_ids:
            r = _najdi_termin(doctor_id, tid, None, None)
            if r:
                rows.extend(r)
            else:
                nepostoekji.append(tid)

        if not rows:
            return f"Не најдов твои термини со ID: {', '.join(str(x) for x in nepostoekji)}."

        # ако само еден - дај обичен формат
        if len(rows) == 1:
            t = rows[0]
            if t["status_pregled"] != "закажан":
                return f'Терминот ID {t["termin_ID"]} веќе има статус „{t["status_pregled"]}".'
            _zavrshi(t["termin_ID"], dijagnoza, terapija)
            msg = _format_uspeh(t, dijagnoza, terapija)
            if nepostoekji:
                msg += f"\n\nНе најдов: ID {', '.join(str(x) for x in nepostoekji)}"
            return msg

        # повеќе ID-а одеднаш
        msg = _zavrshi_mnogu(rows, dijagnoza, terapija)
        if nepostoekji:
            msg += f"\n\nНе најдов: ID {', '.join(str(x) for x in nepostoekji)}"
        return msg

    # Единствен закажан преглед денес (ако пишат само „затвори го терминот" + dx/tx)
    if (
        not termin_ids
        and not ime
        and not datum_str
        and not site
        and dijagnoza
        and terapija
    ):
        denes = date.today().isoformat()
        eden = _najdi_site_zakazani(doctor_id, denes)
        if len(eden) == 1:
            t = eden[0]
            _zavrshi(t["termin_ID"], dijagnoza, terapija)
            return _format_uspeh(t, dijagnoza, terapija)

    # СЛУЧАЈ 3: само име / датум (старо однесување)
    if not ime and not datum_str:
        return (
            'За да завршам преглед ми треба: пациент, ID, еден денешен термин, '
            'или прво „Прикажи ми термините" (па повтори со дијагноза/терапија).\n'
            'Примери:\n'
            '• „Затвори термин ID 42 со дијагноза: … и терапија: …"\n'
            '• „Заврши го прегледот на Петар Иванов со дијагноза: …"\n'
            '• „Заврши ги сите денешни прегледи"'
        )

    rows = _najdi_termin(doctor_id, None, ime, datum_str)
    if not rows:
        return _poraka_ne_najden_termin(doctor_id, ime or None)

    if len(rows) > 1:
        lista = "\n".join(
            f"• ID {r['termin_ID']}: {r['ime_pacient']} — {format_datum_i_vreme(r['datum_pregled'], r['vreme_pregled'])}"
            for r in rows[:6]
        )
        prv_id = rows[0]['termin_ID']
        site_id = ", ".join(str(r['termin_ID']) for r in rows[:6])
        return (
            "Најдов повеќе закажани прегледи. Може со ID или сите:\n" + lista
            + f'\n\nПример (еден): „Заврши термин ID {prv_id}".'
            + f'\nПример (повеќе): „Заврши термини {site_id}".'
            + '\nПример (сите): „Заврши ги сите".'
        )

    t = rows[0]
    _zavrshi(t["termin_ID"], dijagnoza, terapija)
    return _format_uspeh(t, dijagnoza, terapija)


def _format_uspeh(t: dict, dijagnoza: str | None, terapija: str | None) -> str:
    extra = ""
    if dijagnoza:
        extra += f"\nДијагноза: {dijagnoza}"
    if terapija:
        extra += f"\nТерапија: {terapija}"
    return (
        f"Прегледот е означен како завршен.\n\n"
        f"ID: {t['termin_ID']}\n"
        f"Пациент: {t['ime_pacient']}\n"
        f"Кога: {format_datum_i_vreme(t['datum_pregled'], t['vreme_pregled'])}"
        f"{extra}"
    )
