"""
Оцени завршен преглед преку AI асистент.

Како работи:
1. Пациент пишува: „Оцена 5 за д-р Петров - беше одличен"
   или „Оценувам 4 за вчерашниот преглед, добар лекар"
2. AI извлекува: ocena (1-5), коментар, лекар/датум за идентификација на терминот
3. Бараме завршен ('завршен') термин на тој пациент што одговара
4. INSERT (или UPDATE) во Pregled_feedback - еден термин = еден ред (UNIQUE termin_ID)

Бара логиран пациент.
Се оценуваат САМО прегледи со status_pregled = 'завршен'.
"""

from ai._kernel.prompt_loader import load_prompt
import json
import re
from datetime import date
from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai
from ai.pacient.slobodni_termini import zimi_site_lekari


def izvlechi_ocena_podatoci(prashanje: str) -> dict:
    """Извлекува оцена, коментар, лекар и датум од пораката."""
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

Извлечи ocena, komentar, doctor_id и datum.
""".strip()

    odgovor = ask_ai(full_prompt, system_prompt=load_prompt("oceni_extract"))
    podatoci = parse_ai_json(odgovor, log_tag="oceni_pregled")
    ocena_raw = podatoci.get("ocena")
    try:
        ocena = int(ocena_raw) if ocena_raw is not None else None
    except (TypeError, ValueError):
        ocena = None
    return {
        "ocena": ocena,
        "komentar": (podatoci.get("komentar") or None),
        "doctor_id": podatoci.get("doctor_id"),
        "datum": podatoci.get("datum"),
    }


def najdi_zaversen_termin(pacient_email: str, doctor_id: int | None, datum: str | None) -> list[dict]:
    """
    Враќа завршени прегледи на пациентот што одговараат на филтрите.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        query = """
            SELECT t.termin_ID, t.datum_pregled, t.vreme_pregled,
                   t.ime_lekar, t.specijalnost_termin, t.doctor_ID,
                   pf.feedback_ID AS postoecka_ocena
            FROM Termin_pregled t
            LEFT JOIN Pregled_feedback pf ON pf.termin_ID = t.termin_ID
            WHERE LOWER(TRIM(t.email_pacient)) = LOWER(TRIM(%s))
              AND t.status_pregled = 'завршен'
        """
        params: list[object] = [pacient_email]

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
        print(f"[oceni_pregled] greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()


def vmetni_ili_azhuriraj_ocena(termin_id: int, ocena: int, komentar: str | None) -> bool:
    """
    INSERT во Pregled_feedback - ако веќе има оцена за тој термин, ажурира (UNIQUE termin_ID).
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO Pregled_feedback (termin_ID, ocena, komentar)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
              ocena = VALUES(ocena),
              komentar = VALUES(komentar),
              datum_na_ocena = CURRENT_TIMESTAMP
            """,
            (termin_id, ocena, komentar),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[oceni_pregled] insert greshka: {e}")
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


def odgovori_za_ocenuvanje(prashanje: str, pacient: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if not pacient or not pacient.get("email"):
        return (
            'За да оцениш преглед, прво најави се како пациент. '
            'Кликни „Најави се!" горе десно.'
        )

    izvleceno = izvlechi_ocena_podatoci(prashanje)
    ocena = izvleceno.get("ocena")
    komentar = izvleceno.get("komentar")
    doctor_id = izvleceno.get("doctor_id")
    datum_str = izvleceno.get("datum")

    if ocena is None or ocena < 1 or ocena > 5:
        return (
            'Не разбрав која оцена сакаш да дадеш. Кажи број од 1 до 5.\n'
            'Пример: „Оцена 5 за д-р Петров — беше одличен"'
        )

    termini = najdi_zaversen_termin(pacient["email"], doctor_id, datum_str)

    DENOVI = ["Понеделник", "Вторник", "Среда", "Четврток", "Петок", "Сабота", "Недела"]

    if not termini:
        return (
            'Не најдов завршен преглед што одговара. Оцена може да се остави '
            'само за прегледи со статус „завршен“. Биди поспецифичен — '
            'спомни го лекарот и/или датумот.'
        )

    if len(termini) > 1:
        delovi = ["Имаш повеќе завршени прегледи. Кој точно сакаш да го оцениш?", ""]
        for t in termini[:10]:
            datum = t["datum_pregled"]
            den_ime = DENOVI[datum.weekday()]
            vreme = format_vreme(t["vreme_pregled"])
            oznaka = " (веќе оценет)" if t.get("postoecka_ocena") else ""
            delovi.append(
                f"- {den_ime} {datum.strftime('%d.%m.%Y')} во {vreme} "
                f"кај Д-р {t['ime_lekar']} ({t['specijalnost_termin']}){oznaka}"
            )
        delovi.append("")
        delovi.append('Биди поточен: „Оцена 5 за прегледот кај д-р [презиме] на [датум]"')
        return "\n".join(delovi)

    # Точно еден термин
    t = termini[0]
    veke_imal_ocena = bool(t.get("postoecka_ocena"))

    if not vmetni_ili_azhuriraj_ocena(t["termin_ID"], ocena, komentar):
        return "Не успеа да ја зачувам оцената. Пробај пак."

    datum = t["datum_pregled"]
    den_ime = DENOVI[datum.weekday()]
    vreme = format_vreme(t["vreme_pregled"])

    naslov = "Оцената е ажурирана!" if veke_imal_ocena else "Благодариме за оцената!"
    zvezdi = "★" * ocena + "☆" * (5 - ocena)

    delovi = [
        naslov,
        "",
        f"Лекар: Д-р {t['ime_lekar']}",
        f"Специјалност: {t['specijalnost_termin']}",
        f"Датум: {den_ime}, {datum.strftime('%d.%m.%Y')} во {vreme}",
        f"Оцена: {zvezdi} ({ocena}/5)",
    ]
    if komentar:
        delovi.append(f"Коментар: {komentar}")

    return "\n".join(delovi)
