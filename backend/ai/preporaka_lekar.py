"""
Препорака на лекар според симптом.

Како работи:
1. Пациент опишува болка/симптом ("Имам болка во колено").
2. Gemini одредува која специјалност е најсоодветна.
3. Барање во Doctors табелата за лекари од таа специјалност.
4. Враќа листа на лекари за пациентот да избере.

ВАЖНО: Ова НЕ е дијагноза - само препорака кон кој лекар да оди.
"""

from database import get_connection
from ai.gemini_client import ask_gemini
from ai.prompts import SIMPTOM_PROMPT


def zimi_site_specialnosti() -> list[str]:
    """Враќа листа на сите специјалности што ги имаат лекарите."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT DISTINCT specialty
            FROM Doctors
            WHERE specialty IS NOT NULL AND specialty != ''
            ORDER BY specialty
        """)
        rezultati = cur.fetchall()
        cur.close()
        return [r["specialty"] for r in rezultati]
    except Exception as e:
        print(f"[preporaka_lekar] greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()


def najdi_lekari_po_specialnost(specialnost: str) -> list[dict]:
    """Враќа лекари од дадена специјалност."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT doctor_ID, name, surname, specialty
            FROM Doctors
            WHERE specialty = %s
            ORDER BY surname, name
        """, (specialnost,))
        rezultati = cur.fetchall()
        cur.close()
        return rezultati
    except Exception as e:
        print(f"[preporaka_lekar] greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()


def odgovori_za_preporaka(prashanje: str) -> str:
    """
    Главна точка - повикана од router-от.

    Параметри:
        prashanje - опис на симптом од корисник

    Враќа: текстуален одговор со препораки.
    """
    specialnosti = zimi_site_specialnosti()
    if not specialnosti:
        return "Не успеав да најдам специјалности во базата."

    # Прашај Gemini за препорака на специјалност
    lista_text = "\n".join([f"- {s}" for s in specialnosti])
    full_prompt = f"""
Достапни специјалности во болницата:
{lista_text}

Симптом/опис од пациент: „{prashanje}"

Која специјалност препорачуваш?
""".strip()

    odgovor = ask_gemini(full_prompt, system_prompt=SIMPTOM_PROMPT)
    odgovor_cist = odgovor.strip().upper()

    # Итна помош
    if "ИТНА" in odgovor_cist or "ИТНО" in odgovor_cist:
        return (
            'Симптомите што ги опишувате звучат сериозно. '
            'Ве молам веднаш контактирајте Итна помош:\n\n'
            'Телефон: 194\n'
            'Локација: Главна зграда, приземје, главен влез\n\n'
            'Не чекајте и не возете сами. Побарајте помош.'
        )

    # Општа пракса fallback - клиничка болница нема општи лекари
    if "ОПШТА" in odgovor_cist:
        return (
            'За општи здравствени проблеми посетете лекар во дом на здравјето '
            'или примарна здравствена установа. Тие можат да Ви дадат упат за '
            'специјалист во нашата клиничка болница ако е потребно.'
        )

    # Најди ја вистинската специјалност (case-insensitive match)
    izbrana = None
    for s in specialnosti:
        if s.upper() in odgovor.upper() or odgovor.strip().upper() in s.upper():
            izbrana = s
            break

    if not izbrana:
        return (
            f'Според вашиот опис, можеби би било најдобро да се консултирате '
            f'со општ лекар најпрво. Можете и да прашате конкретно: '
            f'„Кога е слободен д-р [презиме]?"'
        )

    lekari = najdi_lekari_po_specialnost(izbrana)

    if not lekari:
        return f"Препорачувам {izbrana}, но во моментов нема достапни лекари во таа специјалност."

    # Формирај одговор
    delovi = [f"Препорака: {izbrana}", "", "Лекари достапни во оваа специјалност:"]
    for lekar in lekari:
        delovi.append(f"- Д-р {lekar['name']} {lekar['surname']}")

    delovi.append("")
    delovi.append('За да видите слободни термини напишете: „Кога е слободен д-р [презиме]?"')
    delovi.append('Напомена: Ова е препорака, не дијагноза. За сериозни симптоми посетете лекар.')

    return "\n".join(delovi)
