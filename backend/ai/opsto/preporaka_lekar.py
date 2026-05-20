# modul za preporaka na lekar spored simptom
# ovoj modul ne dava dijagnoza
# tuku samo preporacuva koj tip lekar/specijalnost e najsoodvetna

"""
Препорака на лекар според симптом.

Како работи:
1. Пациент опишува болка/симптом ("Имам болка во колено").
2. AI (Groq) одредува која специјалност е најсоодветна.
3. Барање во Doctors табелата за лекари од таа специјалност.
4. Враќа листа на лекари за пациентот да избере.

ВАЖНО: Ова НЕ е дијагноза - само препорака кон кој лекар да оди.
"""

from database import get_connection
from ai._kernel.groq_client import ask_ai
from ai._kernel.prompts import SIMPTOM_PROMPT


def zimi_site_specialnosti() -> list[str]:
    # funkcija koja gi zema site specijalnosti od bazata
    """Враќа листа на сите специјалности што ги имаат лекарите."""
    conn = None
    # conn e promenliva za konekcija — prvo None za bezbedno zatvoranje vo finally
    try:
        # try blok — ako nastane greska programata ne pada
        conn = get_connection()
        # se otvara konekcija so mysql baza
        cur = conn.cursor(dictionary=True)
        # dictionary=True — rezultatite se dict, na pr. {"specialty": "Kardiologija"}
        cur.execute("""
            SELECT DISTINCT specialty
            FROM Doctors
            WHERE specialty IS NOT NULL AND specialty != ''
            ORDER BY specialty
        """)
        # DISTINCT — samo unikatni specijalnosti; ORDER BY — azbucen red
        rezultati = cur.fetchall()
        # fetchall gi zema site redovi od query
        cur.close()
        # cursorot mora da se zatvori
        return [r["specialty"] for r in rezultati]
        # list comprehension — od sekoj dict samo specialty pole
    except Exception as e:
        # ako nastane bilo kakva greska pri rabota so baza
        print(f"[preporaka_lekar] greska: {e}")
        # debug poraka vo terminal
        return []
        # prazna lista namesto crash na aplikacijata
    finally:
        # finally sekogas se izvrshuva — dali ima greska ili ne
        if conn:
            conn.close()
            # zatvaranje na konekcijata — vazno za da nema otvoreni konekcii


def najdi_lekari_po_specialnost(specialnost: str) -> list[dict]:
    # funkcija koja gi bara site lekari od odredena specijalnost
    """Враќа лекари од дадена специјалност."""
    conn = None
    try:
        conn = get_connection()
        # povrzuvanje so baza
        cur = conn.cursor(dictionary=True)
        # rezultatite ke bidat dict objekti
        cur.execute("""
            SELECT doctor_ID, name, surname, specialty
            FROM Doctors
            WHERE specialty = %s
            ORDER BY surname, name
        """, (specialnost,))
        # WHERE specialty = %s — samo lekari od baranata specijalnost
        # %s e placeholder — zastita od SQL injection
        # ORDER BY surname, name — sortiranje po prezime pa ime
        rezultati = cur.fetchall()
        # zemanje na site rezultati
        cur.close()
        return rezultati
        # lista od dict — doctor_ID, name, surname, specialty
    except Exception as e:
        print(f"[preporaka_lekar] greska: {e}")
        return []
    finally:
        if conn:
            conn.close()
            # sekogas zatvori konekcija


def odgovori_za_preporaka(prasanje: str) -> str:
    # glavna funkcija koja ja povikuva routerot
    # korisnikot vnesuva simptom — funkcijata vraka preporaka
    """
    Главна точка - повикана од router-от.

    Параметри:
        prasanje - опис на симптом од корисник

    Враќа: текстуален одговор со препораки.
    """
    specialnosti = zimi_site_specialnosti()
    # se zemaat site dostapni specijalnosti od baza
    if not specialnosti:
        # ako listata e prazna ili nastanala greska
        return "Не успеав да најдам специјалности во базата."

    # prasaj ai za preporaka na specijalnost
    lista_text = "\n".join([f"- {s}" for s in specialnosti])
    # od site specijalnosti pravi tekst — primer: "- Kardiologija"
    # join gi spojuva vo eden string so \n
    full_prompt = f"""
Достапни специјалности во болницата:
{lista_text}

Симптом/опис од пациент: „{prasanje}"

Која специјалност препорачуваш?
""".strip()
    # finalen prompt: site specijalnosti + simptom + prasanje
    # strip() gi trga praznite mesta od pocetok i kraj

    odgovor = ask_ai(full_prompt, system_prompt=SIMPTOM_PROMPT)
    # se prakja promptot do ai modelot
    odgovor_cist = odgovor.strip().upper()
    # strip + upper — polesno sporedba bez razlika na mali/golemi bukvi

    # itna pomosh
    if "ИТНА" in odgovor_cist or "ИТНО" in odgovor_cist:
        # proverka dali ai procenil deka simptomot e seriozen
        return (
            'Симптомите што ги опишувате звучат сериозно. '
            'Ве молам веднаш контактирајте Итна помош:\n\n'
            'Телефон: 194\n'
            'Локација: Главна зграда, приземје, главен влез\n\n'
            'Не чекајте и не возете сами. Побарајте помош.'
        )
        # vo vakvi slucai ne se preporacuva lekar — direktno itna pomosh

    # opsta praksa fallback — klinicka bolnica nema opsti lekari
    if "ОПШТА" in odgovor_cist:
        # fallback ako ai preporaca opst lekar
        return (
            'За општи здравствени проблеми посетете лекар во дом на здравјето '
            'или примарна здравствена установа. Тие можат да Ви дадат упат за '
            'специјалист во нашата клиничка болница ако е потребно.'
        )
        # korisnikot se nasocuva vo dom na zdravje

    # najdi ja vistinskata specijalnost
    izbrana = None
    # promenliva za finalno izbranata specijalnost
    for s in specialnosti:
        # iteracija niz site specijalnosti
        if s.upper() in odgovor.upper() or odgovor.strip().upper() in s.upper():
            # case-insensitive proverka — dali ai odgovor sodrzi specialty
            izbrana = s
            # zacuvaj ja pronajdenata specijalnost
            break
            # stopiraj go loopot posle prv match

    if not izbrana:
        # ako ai vratil nesto nejasno ili nema sovpagjanje
        return (
            f'Според вашиот опис, можеби би било најдобро '
            f'да се консултирате со општ лекар најпрво. Можете и да прашате конкретно: '
            f'„Кога е слободен д-р [презиме]?"'
        )

    lekari = najdi_lekari_po_specialnost(izbrana)
    # se baraat lekari od taa specijalnost
    if not lekari:
        # ako nema lekari vo taa specijalnost
        return f"Препорачувам {izbrana}, но во моментов нема достапни лекари во таа специјалност."

    # formiraj odgovor
    delovi = [f"Препорака: {izbrana}", "", "Лекари достапни во оваа специјалност:"]
    # lista od tekstualni linii — podocna ke se spojuvaat
    for lekar in lekari:
        # iteracija niz site lekari
        delovi.append(f"- Д-р {lekar['name']} {lekar['surname']}")
        # dodavanje lekar vo odgovorot
    delovi.append("")
    # prazen red pred instrukcii
    delovi.append('За да видите слободни термини напишете: „Кога е слободен д-р [презиме]?"')
    delovi.append('Напомена: Ова е препорака, не дијагноза. За сериозни симптоми посетете лекар.')
    return "\n".join(delovi)
    # join gi spojuva site delovi vo eden string — \n megu liniite
