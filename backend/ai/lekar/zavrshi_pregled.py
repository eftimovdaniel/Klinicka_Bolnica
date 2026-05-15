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

from datetime import date, datetime

from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.auth import require_lekar
from ai._kernel.groq_client import ask_ai
from ai._kernel.prompt_helpers import today_prompt_line


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


def _izvlechi(prashanje: str) -> dict:
    full = f'{today_prompt_line()}\n\nПрашање: „{prashanje}"\nВрати JSON.'
    odgovor = ask_ai(full, system_prompt=PROMPT)
    print(f"[zavrshi_pregled] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="zavrshi_pregled")


def _najdi_termin(
    doctor_id: int,
    termin_id: int | None,
    ime_pacient: str | None,
    datum_str: str | None,
) -> list[dict]:
    """Враќа активни (закажани) термини на овој лекар."""
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
        " FROM Termin_pregled"
        " WHERE doctor_ID = %s AND status_pregled = 'закажан'"
    )
    params: list = [doctor_id]

    if datum_str:
        sql += " AND datum_pregled = %s"
        params.append(datum_str)

    if ime_pacient:
        delovi = [d for d in ime_pacient.strip().split() if d]
        if len(delovi) >= 2:
            sql += " AND LOWER(ime_pacient) LIKE %s AND LOWER(ime_pacient) LIKE %s"
            params.extend([f"%{delovi[0].lower()}%", f"%{delovi[-1].lower()}%"])
        else:
            sql += " AND LOWER(ime_pacient) LIKE %s"
            params.append(f"%{delovi[0].lower()}%")

    sql += " ORDER BY datum_pregled, vreme_pregled"
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _zavrshi(termin_id: int, dijagnoza: str | None, terapija: str | None) -> None:
    """Маркира преглед како завршен. Опционо запишува dx/tx."""
    conn = get_connection()
    cur = conn.cursor()
    sets = ["status_pregled = 'завршен'"]
    params: list = []
    if dijagnoza:
        sets.append("dijagnoza = %s")
        params.append(dijagnoza)
    if terapija:
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


def _fmt_dt(d, t) -> str:
    d_s = d.strftime("%d.%m.%Y") if hasattr(d, "strftime") else str(d)
    t_s = t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)[:5]
    return f"{d_s} {t_s}"


def _najdi_site_zakazani(doctor_id: int, datum_str: str | None) -> list[dict]:
    """Сите закажани прегледи на лекарот (опционо филтрирани по датум)."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    sql = (
        "SELECT termin_ID, ime_pacient, datum_pregled, vreme_pregled, status_pregled"
        " FROM Termin_pregled"
        " WHERE doctor_ID = %s AND status_pregled = 'закажан'"
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
            f"• ID {r['termin_ID']}: {r['ime_pacient']} ({_fmt_dt(r['datum_pregled'], r['vreme_pregled'])})"
        )
    return "\n".join(linii)


def odgovori_za_zavrshi(prashanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_lekar(lekar):
        return err

    doctor_id = lekar["doctor_ID"]

    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    termin_ids = podatoci.get("termin_ids") or []
    if isinstance(termin_ids, int):
        termin_ids = [termin_ids]
    # пробај да ги претвориш во int
    try:
        termin_ids = [int(x) for x in termin_ids if x is not None]
    except (TypeError, ValueError):
        termin_ids = []

    ime = (podatoci.get("ime_pacient") or "").strip()
    datum_str = podatoci.get("datum")
    site = bool(podatoci.get("site"))
    dijagnoza = (podatoci.get("dijagnoza") or "").strip() or None
    terapija = (podatoci.get("terapija") or "").strip() or None

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

    # СЛУЧАЈ 3: само име / датум (старо однесување)
    if not ime and not datum_str:
        return (
            'За да завршам преглед ми треба: пациент, ID или „сите".\n'
            'Примери:\n'
            '• „Заврши го прегледот на Петар Иванов"\n'
            '• „Заврши термин ID 42"\n'
            '• „Заврши термини 42, 43, 44"\n'
            '• „Заврши ги сите денешни прегледи"'
        )

    rows = _najdi_termin(doctor_id, None, ime, datum_str)
    if not rows:
        return "Не најдов соодветен закажан преглед кај тебе."

    if len(rows) > 1:
        lista = "\n".join(
            f"• ID {r['termin_ID']}: {r['ime_pacient']} — {_fmt_dt(r['datum_pregled'], r['vreme_pregled'])}"
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
        f"Кога: {_fmt_dt(t['datum_pregled'], t['vreme_pregled'])}"
        f"{extra}"
    )
