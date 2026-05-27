from ai._kernel.prompt_loader import load_prompt  # vcituvanje AI prompt od agent_prompts.txt
from ai._kernel.ai_json import parse_ai_json  # AI odgovor -> JSON dict
from ai._kernel.auth import require_direktor  # samo direktor ima pristap
from ai._kernel.db_helpers import as_dict, db_cursor, prijaveni_select_sql  # pomos za MySQL kursor
from ai._kernel.groq_client import ask_ai  # povik kon Groq API
from ai._kernel.utils import format_datum_vreme

def _izvlechi(prasanje: str) -> dict:  # izvleci pozicija ili id_oglas od prasanjeto
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=load_prompt("direktor_aplikanti_oglas"))  # AI analiza, se praka baranje do ai so soodvetniot promtp
    return parse_ai_json(odgovor, log_tag="aplikanti_oglas")  # dict ili _error

def odgovori_za_aplikanti(prasanje: str, lekar: dict | None) -> str:  # glaven handler (intent aplikanti_oglas)
    if err := require_direktor(lekar):  # proveri uloga direktor
        return err  # odbien pristap
    podatoci = _izvlechi(prasanje)  # {pozicija, id_oglas} od AI
    if podatoci.get("_error"):  # Groq limit ili los JSON
        return podatoci["_error"]  # prikazi ja sisitemskata greska

    pozicija = (podatoci.get("pozicija") or "").strip() or None  # filter po pozicija (opcionalno)
    id_oglas = podatoci.get("id_oglas")  # filter po broj na oglas (opcionalno)
    try:  # pretvori id vo int
        id_oglas = int(id_oglas) if id_oglas else None  # cel broj ili None
    except (ValueError, TypeError):  # nevaliden id od AI
        id_oglas = None  # bez filter po id

    try:  # citaj od baza
        with db_cursor() as (_, cur):  # konekcija + kursor (auto close)
            sql = prijaveni_select_sql(full=True) + " WHERE 1=1"
            params: list = []  # vrednosti za %s

            if id_oglas:  # baranje po konkreten oglas
                sql += " AND id_oglas = %s"  # tocno id
                params.append(id_oglas)  # parametar
            elif pozicija:  # baranje po ime na pozicija
                sql += " AND LOWER(TRIM(pozicija)) LIKE %s"  # del od tekst
                params.append(f"%{pozicija.strip().lower()}%")  # npr. %kardiolog%

            sql += " ORDER BY datum_prijava DESC"  # najnovi prvi
            cur.execute(sql, tuple(params))  # izvrshi query
            rows = cur.fetchall() or []  # lista redovi
    except Exception as e:  # greska na baza
        print(f"[aplikanti] DB greska: {e}")  # log
        return "Се случи грешка при вчитувањето на апликантите. Те молам обиди се повторно."  # poraka

    if not rows:  # nema rezultati
        if id_oglas:  # barashe po id
            return f"Нема апликанти за оглас со ID {id_oglas}."  # prazen oglas
        if pozicija:  # barashe po pozicija
            return f'Нема апликанти за позицијата „{pozicija}".'  # nema takva pozicija
        return "Нема апликанти во системот."  # prazna tabela

    naslov_filtri = []  # tekst za naslov (filtri)
    if id_oglas:  # filtrirano po oglas
        naslov_filtri.append(f"оглас #{id_oglas}")  # dodaj vo naslov
    if pozicija:  # filtrirano po pozicija
        naslov_filtri.append(f'„{pozicija}"')  # dodaj vo naslov
    naslov_suffix = (" (" + ", ".join(naslov_filtri) + ")") if naslov_filtri else ""  # zagrada ili prazno
    naslov = f"Апликанти ({len(rows)}){naslov_suffix}:"  # naslov so broj

    redovi = [naslov, ""]  # pocni lista za odgovor
    for raw in rows:  # sekoj aplikant
        r = as_dict(raw)  # red -> dict
        ime = (r.get("ime_lekar") or "").strip()  # ime
        prezime = (r.get("prezime_lekar") or "").strip()  # prezime
        polno = f"{ime} {prezime}".strip() or "—"  # celo ime
        poz = (r.get("pozicija") or "").strip() or "—"  # pozicija
        email = (r.get("email") or "").strip() or "—"  # email
        tel = r.get("telefon") or "—"  # telefon
        lic = r.get("broj_med_licenca") or "—"  # licenca
        kogo = format_datum_vreme(r.get("datum_prijava"))  # datum na prijava
        oglas_ref = r.get("id_oglas")  # id na oglasot
        oglas_str = f" | оглас #{oglas_ref}" if oglas_ref else ""  # dopolnitelen tekst

        red = (  # blok za eden aplikant
            f"• {polno} – {poz}{oglas_str}\n"  # ime i pozicija
            f"   Email: {email} | Тел: {tel} | Лиценца: {lic}\n"  # kontakt
            f"   Пријавен: {kogo}"  # koga
        )
        redovi.append(red)  # dodadi vo listata

    return "\n".join(redovi)  # finalen tekst za chat
