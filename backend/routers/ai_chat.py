"""
AI чат рутер - главна точка за сите AI прашања од frontend.

Како работи:
1. Frontend (script.js → pitajAI) праќа POST /ai-chat/ask со {prashanje, pacient}.
2. Овој рутер прави transliteracija (латиница → кирилица).
3. Детектира интент (што сака корисникот) преку intent_detector
   (keyword прво, AI fallback).
4. Според интентот, повикува соодветен AI модул:
       - slobodni_termini   → "Кога е слободен д-р Петров?"
       - zakazi_termin      → "Сакам преглед кај Петров среда 10:00"
       - otkazi_termin      → "Откажи го утрешниот преглед"
       - prenesi_termin     → "Префрли го за петок"
       - postavi_potsetnik  → "Потсети ме 1 ден претходно"
       - oceni_pregled      → "Оцена 5 за д-р Петров"
       - trgni_ocena        → "Избриши ја оцената за вчерашниот преглед"
       - info_lekar         → "Каков е д-р Петров?"
       - preporaka_lekar    → "Имам болка во колено - кому?"
       - rabotno_vreme      → "Кога е отворена лабораторијата?"
       - lokacija           → "Каде е оддел за гинекологија?"
       - kontakti           → "На кој број за итна?"
       - uslugi             → "Кои услуги имате?"
       - objavi_vest        → "Објави вест: https://youtube.com/..." (само директор)
       - kreiraj_oglas      → "Креирај оглас за кардиолог" (само директор)
       - izbrisi_vest_oglas → "Избриши го најновиот оглас" (само директор)
       - zatvori_oglas      → "Затвори го огласот за кардиолог" (само директор)
       - promeni_dezurstvo  → "Префрли го д-р Петров за петок" (само директор)
       - statistika_oddeli  → "Кои се најпопуларни оддели?" (само директор)
       - zavrshi_pregled    → "Заврши го прегледот на Иванов" (лекар)
       - istorija_pacient   → "Колку пати беше Иванов кај мене?" (лекар)
       - karton_pacient     → "Дај ми картон на Иванов" (лекар)
       - moja_statistika    → "Колку прегледи имам?" (лекар)
       - general            → општ одговор од Groq AI
5. Враќа {"odgovor": "..."} назад на frontend-от.

ВАЖНО: AI операциите одат преку Groq (Llama 3.3 70B), не Gemini.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from ai.groq_client import ask_ai
from ai.intent_detector import detektiraj_intent
from ai.transliteracija import normaliziraj_prashanje

from ai import slobodni_termini
from ai import zakazi_termin
from ai import otkazi_termin
from ai import prenesi_termin
from ai import postavi_potsetnik
from ai import oceni_pregled
from ai import trgni_ocena
from ai import info_lekar
from ai import preporaka_lekar
from ai import bolnica_info
from ai import uslugi as uslugi_modul
from ai import objavi_vest
from ai import kreiraj_oglas
from ai import izbrisi_vest_oglas
from ai import zatvori_oglas
from ai import promeni_dezurstvo
from ai import statistika_oddeli
from ai import zavrshi_pregled
from ai import istorija_pacient
from ai import karton_pacient
from ai import moja_statistika
from ai import moj_raspored
from ai import navigacija
from ai import lekari_oddel
from ai import apliciraj_za_rabota


router = APIRouter(prefix="/ai-chat", tags=["AI Chat"])


class PacientModel(BaseModel):
    """Податоци за логиран пациент (опционално - frontend ги испраќа ако е логиран)."""
    pacient_ID: int | None = None
    ime: str | None = None
    prezime: str | None = None
    email: str | None = None
    telefon: str | None = None


class LekarModel(BaseModel):
    """Податоци за логиран лекар/директор (опционално)."""
    doctor_ID: int | None = None
    name: str | None = None
    surname: str | None = None
    email: str | None = None
    specialty: str | None = None


class PitanjeModel(BaseModel):
    """
    Тело на барањето од frontend.
    {
      "prashanje": "Сакам преглед кај Петров утре во 10",
      "pacient": {"pacient_ID": 1, "ime": "Даниел", ..., "email": "..."},
      "lekar":   {"doctor_ID": 5, "name": "Владко", "surname": "Захариев", ...},
      "kontekst": {"intent": "apliciraj_za_rabota", "cekam": "licenca", "pozicija": "Кардиолог", ...}
    }
    `kontekst` е конверзациска состојба – фронтот го памти и го испраќа назад
    при следно прашање, за да можеме да водиме повеќестепен дијалог.
    """
    prashanje: str
    pacient: PacientModel | None = None
    lekar: LekarModel | None = None
    kontekst: dict | None = None


@router.post("/ask")
def ask(data: PitanjeModel):
    """
    Главниот ендпоинт.
    Прима: {"prashanje": "...", "pacient": {...}|null}
    Враќа: {"odgovor": "..."}
    """

    pitanje = (data.prashanje or "").strip()
    if not pitanje:
        return {"odgovor": "Те молам внеси прашање."}

    # 1. Транслитерација (латиница → кирилица), ако треба
    pitanje_norm = normaliziraj_prashanje(pitanje)

    # 2. Pacient како dict (за модулите што го очекуваат)
    pacient_dict = None
    if data.pacient and data.pacient.email:
        pacient_dict = {
            "pacient_ID": data.pacient.pacient_ID,
            "ime": data.pacient.ime or "",
            "prezime": data.pacient.prezime or "",
            "email": data.pacient.email,
            "telefon": data.pacient.telefon or "",
        }

    # 2b. Lekar како dict (за функциите што имаат лекарска улога, нпр. објави вест)
    lekar_dict = None
    if data.lekar and data.lekar.doctor_ID:
        lekar_dict = {
            "doctor_ID": data.lekar.doctor_ID,
            "name": data.lekar.name or "",
            "surname": data.lekar.surname or "",
            "email": data.lekar.email or "",
            "specialty": data.lekar.specialty or "",
        }

    # 3. Детекција на интент
    # Ако фронтот ни прати активен kontekst (повеќестепен flow),
    # форсирај го интентот од контекстот за да го продолжиме разговорот.
    aktiven_kontekst = None
    if isinstance(data.kontekst, dict) and data.kontekst.get("intent"):
        aktiven_kontekst = data.kontekst
        intent = data.kontekst.get("intent")
        print(f"[ai_chat] продолжуваме kontekst intent={intent}")
    else:
        try:
            intent = detektiraj_intent(pitanje_norm)
        except Exception as e:
            print(f"[ai_chat] greshka pri detekcija na intent: {e}")
            intent = "general"

    print(f"[ai_chat] pitanje={pitanje_norm!r} -> intent={intent}")

    # Резервни променливи за дополнителни полиња во одговорот
    nav_info: dict | None = None
    nov_kontekst: dict | None = None
    akcija: str | None = None

    # 4. Рутирање според интент
    try:
        if intent == "slobodni_termini":
            odgovor = slobodni_termini.odgovori_za_slobodni_termini(pitanje_norm)

        elif intent == "zakazi_termin":
            odgovor = zakazi_termin.odgovori_za_zakazuvanje(pitanje_norm, pacient_dict)

        elif intent == "otkazi_termin":
            odgovor = otkazi_termin.odgovori_za_otkazuvanje(pitanje_norm, pacient_dict)

        elif intent == "prenesi_termin":
            odgovor = prenesi_termin.odgovori_za_prenesuvanje(pitanje_norm, pacient_dict)

        elif intent == "postavi_potsetnik":
            odgovor = postavi_potsetnik.odgovori_za_potsetnik(pitanje_norm, pacient_dict)

        elif intent == "oceni_pregled":
            odgovor = oceni_pregled.odgovori_za_ocenuvanje(pitanje_norm, pacient_dict)

        elif intent == "trgni_ocena":
            odgovor = trgni_ocena.odgovori_za_trgni_ocena(pitanje_norm, pacient_dict)

        elif intent == "info_lekar":
            odgovor = info_lekar.odgovori_za_info_lekar(pitanje_norm)

        elif intent == "preporaka_lekar":
            odgovor = preporaka_lekar.odgovori_za_preporaka(pitanje_norm)

        elif intent == "rabotno_vreme":
            odgovor = bolnica_info.odgovori_za_rabotno_vreme(pitanje_norm)

        elif intent == "lokacija":
            odgovor = bolnica_info.odgovori_za_lokacija(pitanje_norm)

        elif intent == "kontakti":
            odgovor = bolnica_info.odgovori_za_kontakti(pitanje_norm)

        elif intent == "uslugi":
            odgovor = uslugi_modul.odgovori_za_uslugi(pitanje_norm)

        elif intent == "objavi_vest":
            # ВАЖНО: за објавување вест ни треба ОРИГИНАЛНИОТ pitanje (не норм.),
            # зашто транслитерацијата може да го расипе URL-от со кирилица.
            odgovor = objavi_vest.odgovori_za_objava_vest(pitanje, lekar_dict)

        elif intent == "kreiraj_oglas":
            odgovor = kreiraj_oglas.odgovori_za_kreiranje_oglas(pitanje_norm, lekar_dict)

        elif intent == "izbrisi_vest_oglas":
            odgovor = izbrisi_vest_oglas.odgovori_za_brisenje(pitanje_norm, lekar_dict)

        elif intent == "zatvori_oglas":
            odgovor = zatvori_oglas.odgovori_za_zatvoranje_oglas(pitanje_norm, lekar_dict)

        elif intent == "promeni_dezurstvo":
            odgovor = promeni_dezurstvo.odgovori_za_dezurstvo(pitanje_norm, lekar_dict)

        elif intent == "statistika_oddeli":
            odgovor = statistika_oddeli.odgovori_za_statistika(pitanje_norm, lekar_dict)

        elif intent == "zavrshi_pregled":
            odgovor = zavrshi_pregled.odgovori_za_zavrshi(pitanje_norm, lekar_dict)

        elif intent == "istorija_pacient":
            odgovor = istorija_pacient.odgovori_za_istorija(pitanje_norm, lekar_dict)

        elif intent == "karton_pacient":
            odgovor = karton_pacient.odgovori_za_karton(pitanje_norm, lekar_dict)

        elif intent == "moja_statistika":
            odgovor = moja_statistika.odgovori_za_moja_statistika(pitanje_norm, lekar_dict)

        elif intent == "moj_raspored":
            odgovor = moj_raspored.odgovori_za_raspored(pitanje_norm, lekar_dict)

        elif intent == "navigacija":
            nav_rezultat = navigacija.odgovori_za_navigacija(pitanje_norm)
            odgovor = nav_rezultat.get("odgovor", "")
            nav_info = nav_rezultat.get("navigacija")

        elif intent == "lekari_oddel":
            odgovor = lekari_oddel.odgovori_za_lekari_oddel(pitanje_norm)

        elif intent == "apliciraj_za_rabota":
            rezultat_apl = apliciraj_za_rabota.odgovori_za_aplikacija(
                pitanje_norm, pacient_dict, aktiven_kontekst
            )
            odgovor = rezultat_apl.get("odgovor", "")
            nov_kontekst = rezultat_apl.get("kontekst")
            akcija = rezultat_apl.get("akcija")

        else:
            # general → директен повик до Groq AI
            odgovor = ask_ai(pitanje_norm)

    except Exception as e:
        print(f"[ai_chat] greshka pri obrabotka na intent {intent}: {e}")
        odgovor = (
            "Се случи неочекувана грешка при обработката на прашањето. "
            "Те молам обиди се повторно или контактирај ја рецепцијата."
        )

    rezultat: dict = {"odgovor": odgovor}
    if nav_info:
        rezultat["navigacija"] = nav_info
    if akcija:
        rezultat["akcija"] = akcija
    # Враќаме kontekst (може и null) за да фронтот експлицитно знае дали
    # треба да го памти за следно прашање или да го избрише.
    rezultat["kontekst"] = nov_kontekst
    return rezultat
