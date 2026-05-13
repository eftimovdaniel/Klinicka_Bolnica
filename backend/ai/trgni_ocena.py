"""
Тргни (избриши) оцена за завршен преглед.

Како работи:
1. Пациент пишува: „Избриши ја оцената за вчерашниот преглед"
   или „Тргни ја оцената за д-р Петров"
2. AI извлекува: лекар (опционално) + датум (опционално)
3. Бараме завршени термини на тој пациент што имаат оцена и одговараат на филтрите
4. Ако има точно еден → DELETE од Pregled_feedback
5. Ако има повеќе → прашаме кој
6. Ако нема → грешка

Бара логиран пациент.
"""

import json
import re
from datetime import date
from database import get_connection
from ai.groq_client import ask_ai
from ai.slobodni_termini import zimi_site_lekari


TRGNI_EXTRACT_PROMPT = """
Ти си систем што извлекува податоци за бришење на оцена за медицински преглед.
Од прашањето извлечи:
- doctor_id: ID на лекарот (или null)
- datum: датум на прегледот во формат YYYY-MM-DD (или null)

ПРАВИЛА за датум:
- "денес" → денешен датум
- "вчера" → денешен - 1
- "понеделник", "среда"... → последниот таков ден во минатото
- "15.05" → во оваа година
- Ако не е специфицирано → null

Врати САМО JSON: {"doctor_id": число_или_null, "datum": "YYYY-MM-DD"_или_null}
""".strip()


def izvlechi_trgni_podatoci(prashanje: str) -> dict:
    """Користи AI (Groq) да извлече лекар + датум за бришење оцена."""
    site_lekari = zimi_site_lekari()

    lista_text = ""
    for lekar in site_lekari:
        spec = lekar.get("specialty") or "Општа пракса"
        lista_text += f"ID {lekar['doctor_ID']}: Д-р {lekar['name']} {lekar['surname']} - {spec}\n"

    denes = date.today().strftime("%Y-%m-%d")
    den_vo_nedela = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"][date.today().weekday()]

    full_prompt = f"""
Денес: {denes} ({den_vo_nedela})

Лекари:
{lista_text}

Корисник: „{prashanje}"

Извлечи doctor_id и datum.
""".strip()

    odgovor = ask_ai(full_prompt, system_prompt=TRGNI_EXTRACT_PROMPT)

    cist = re.sub(r"^```(?:json)?\s*", "", odgovor.strip())
    cist = re.sub(r"\s*```$", "", cist)

    try:
        podatoci = json.loads(cist)
        return {
            "doctor_id": podatoci.get("doctor_id"),
            "datum": podatoci.get("datum"),
        }
    except json.JSONDecodeError:
        return {"doctor_id": None, "datum": None}


def najdi_oceneti_termini(pacient_email: str, doctor_id: int | None, datum: str | None) -> list[dict]:
    """
    Враќа завршени прегледи на пациентот што ИМААТ оцена и одговараат на филтрите.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        query = """
            SELECT t.termin_ID, t.datum_pregled, t.vreme_pregled,
                   t.ime_lekar, t.specijalnost_termin, t.doctor_ID,
                   pf.feedback_ID, pf.ocena, pf.komentar
            FROM Termin_pregled t
            INNER JOIN Pregled_feedback pf ON pf.termin_ID = t.termin_ID
            WHERE LOWER(TRIM(t.email_pacient)) = LOWER(TRIM(%s))
              AND t.status_pregled = 'завршен'
        """
        params = [pacient_email]

        if doctor_id:
            query += " AND t.doctor_ID = %s"
            params.append(doctor_id)

        if datum:
            query += " AND t.datum_pregled = %s"
            params.append(datum)

        query += " ORDER BY t.datum_pregled DESC, t.vreme_pregled DESC"

        cur.execute(query, params)
        rezultati = cur.fetchall()
        cur.close()
        return rezultati

    except Exception as e:
        print(f"[trgni_ocena] greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()


def izbrisi_ocena(feedback_id: int) -> bool:
    """DELETE од Pregled_feedback."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM Pregled_feedback WHERE feedback_ID = %s",
            (feedback_id,),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[trgni_ocena] delete greshka: {e}")
        return False
    finally:
        if conn:
            conn.close()


def format_vreme(v) -> str:
    if v is None:
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    return str(v)[:5]


def odgovori_za_trgni_ocena(prashanje: str, pacient: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if not pacient or not pacient.get("email"):
        return (
            'За да избришеш оцена, прво најави се како пациент. '
            'Кликни „Најави се!" горе десно.'
        )

    izvleceno = izvlechi_trgni_podatoci(prashanje)
    doctor_id = izvleceno.get("doctor_id")
    datum_str = izvleceno.get("datum")

    termini = najdi_oceneti_termini(pacient["email"], doctor_id, datum_str)

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]

    if not termini:
        return (
            'Не најдов оценети прегледи што одговараат. Прашај „Кои се моите оценети прегледи?" '
            'или биди поспецифичен (лекар + датум).'
        )

    if len(termini) > 1:
        delovi = ["Имаш повеќе оценети прегледи. Кој точно сакаш да го избришеш?", ""]
        for t in termini[:10]:
            datum = t["datum_pregled"]
            den_ime = DENOVI[datum.weekday()]
            vreme = format_vreme(t["vreme_pregled"])
            ocena = t.get("ocena") or 0
            zvezdi = "★" * ocena + "☆" * (5 - ocena)
            delovi.append(
                f"- {den_ime} {datum.strftime('%d.%m.%Y')} во {vreme} "
                f"кај Д-р {t['ime_lekar']} - {zvezdi} ({ocena}/5)"
            )
        delovi.append("")
        delovi.append('Биди поточен: „Тргни ја оцената за прегледот кај д-р [презиме] на [датум]"')
        return "\n".join(delovi)

    # Точно еден термин
    t = termini[0]
    if not izbrisi_ocena(t["feedback_ID"]):
        return "Не успеа да ја избришам оцената. Пробај пак."

    datum = t["datum_pregled"]
    den_ime = DENOVI[datum.weekday()]
    vreme = format_vreme(t["vreme_pregled"])
    stara_ocena = t.get("ocena") or 0

    ime_lekar = t['ime_lekar']
    return (
        f"Оцената е избришана!\n\n"
        f"Лекар: Д-р {ime_lekar}\n"
        f"Специјалност: {t['specijalnost_termin']}\n"
        f"Датум: {den_ime}, {datum.strftime('%d.%m.%Y')} во {vreme}\n"
        f"Избришана оцена: {stara_ocena}/5\n\n"
        'Можеш повторно да оцениш ако сакаш: „Оцена [1-5] за прегледот кај д-р '
        + str(ime_lekar) + '".'
    )
