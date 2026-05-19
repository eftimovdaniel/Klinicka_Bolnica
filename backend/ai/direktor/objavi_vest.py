import re
import requests
from database import get_connection
from ai._kernel.auth import require_direktor
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import GROQ_OFFLINE_MSG, ask_ai, groq_e_isklucen
from ai._kernel.groq_helpers import groq_zadolzhitelen
from ai._kernel.prompt_loader import load_prompt
# funkcija za izvlekuvanje na karakterite na videoto sto e staveno od direktorot
def _video_id(text: str) -> str | None:
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", text)   # baranje na nekoj skreaten link
    if m:   #ako e pronajden 
        return m.group(1)   # go vraka id to 
    m = re.search(r"youtube\.com/(?:watch\?v=|embed/|shorts/)([a-zA-Z0-9_-]{11})", text)    # prebaruvanje za embed ili shorts linkovi
    if m:   #ako imame pokopuvanje so nekoj standarten format
        return m.group(1)   # se izvlekuva i se veka id to 
    return None # ako ne vrka ni none
# vlecenje na title preku standardna biblioteka
def _zimi_transcript(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi # lokalno se povikuva biblioteka za da se dobie tekst 

        api = YouTubeTranscriptApi()   #instalacija od api klienti za rabota so titles
        try:
            tr = api.fetch(video_id, languages=["mk", "en", "en-US", "sr", "bg"])   # se postavuva prioreite na koj jazici da bidat
        except Exception:   # ako za pogore navedenite jazici nema vneseno title 
            tr = next(iter(api.list(video_id))).fetch() # se zema prviot title bez razlika na koj jazik e
        tekst = " ".join(s.text.strip() for s in tr if s.text)  # site tekstovi sto se dobivaat se spojuvaat vo eden paragraf
        return tekst[:8000] if tekst else None  # se zemaat prvite 8000 karakteri od the title i se obrabotuvaat od groq za da se objavat kako vest
    except Exception as e:  #ako se pojavi bilo kakva greska ili imame prob so titles
        print(f"[objavi_vest] transcript greska: {e}")  
        return None # se vraka none
# se izvlekuva naslvot preku embed protokol i se postavuva kako naslov na vesta
def _zimi_naslov(video_id: str) -> str | None:
    try:
        url = f"https://www.youtube.com/watch?v={video_id}" # kreiranje na link so youtube videoto 
        r = requests.get(   #se pravi http get baranje od oficijalniot oembed servis na youtube
            f"https://www.youtube.com/oembed?url={url}&format=json", timeout=10 # mu se dostavuva prethodno izgradeniot link vo json format do tajmer od 10 sekundi
        )
        return r.json().get("title") if r.ok else None  # ako go odobrat se izvlekuva naslovot vo spotivno se vraka none
    except Exception:   # ako nastane sinstaksna ili mrezna greska ne dobivame nikakov odgovor
        return None
# se praka info do groq da sostave vest
def _generiraj_vest(transcript: str, naslov_yt: str | None) -> dict:
    if msg := groq_zadolzhitelen(): # proveka na api klucot dali e navistina tamu i dali moze da se obrabota mojte baranja
        return {"_error": msg}  # ako ne e uspesno vraka poraka za greska
# se formira konteks ili promt koj sodrzi naslov i transription
    kontekst = (
        (f"Оригинален наслов: „{naslov_yt}\"\n\n" if naslov_yt else "") #kontekst od naslovot na youtube
        + f"Transcript:\n{transcript}"  # tekst od titles za obrabotaka.
    )
    odgovor = ask_ai(kontekst, system_prompt=load_prompt("direktor_objavi_vest")) # se povikuva groq za obabotka
    if (odgovor or "").strip() == GROQ_OFFLINE_MSG or "преоптоварен" in (odgovor or ""):    # zastita vo slucaj da e api preoptovareno
        return {"_error": GROQ_OFFLINE_MSG} # se dava poraka deka e preoptovaren ili offline ne moze da se obrabote baranjeto vo dadeniot vremenski intereval
    data = parse_ai_json(odgovor, log_tag="objavi_vest")   #go parsira stringot vo python recnik 
    if data.get("_error"):  #dokolku se jave greska pri parsiranje 
        return data # ja prosleduva greskata do povikuvacot
    if data.get("naslov") and data.get("sodrzina"): # provekra dali gi imame site zadolzitelni polinja za nova vest
        return data #go vraka spakuvaniot python recnik kako vest
    return {"_error": "AI врати неочекуван формат за вест."}    # dokolku imeme nekompletiran struktira na json vraka error
# glaven hendler koj ja izvrasuva logikata na direktorot
def odgovori_za_objava_vest(prasanje: str, lekar: dict | None) -> str | dict:
    if err := require_direktor(lekar):  # proverka na privilegiite dali sme najaveni kako direktor ili kako noramlen lekar
        return err  # ako e najaven normalen lekar dava error i ne moze da se objave vesta
    if groq_e_isklucen():   # isto ke mi dade error ako groq ne rabote ili nemam vise tokeni so moze da go obrabotat baranjeto
        return GROQ_OFFLINE_MSG
    vid = _video_id(prasanje)   # analiza na prasanjeto za da go izvlece id to na youtube videoto
    if not vid: # ako ne e praten validen youtube link 
        return (    # se dava poraka so instrukcii kako treba da izgleda najosnovnipt promt za da moze da se obajvi nekoja vest
            "Испрати ми YouTube линк.\n\n"
            'Пример: „Објави вест: https://www.youtube.com/watch?v=XXXXXXXXXXX"'
        )
    transcript = _zimi_transcript(vid)  # se pravi obid da se izvlece titlot od videoto preku soodvetno api
    naslov_yt = _zimi_naslov(vid)   # go zemame naslovot na videoto 
    if not transcript:     # ako videot nema nikakov title na nitu eden jazik vo sistemot
        if not naslov_yt:   # i ako ne moze da se prepoznae nikakov naslov
            return "Видеото нема титлови ниту наслов. Пробај друго видео."  # se vraka slednata poraka
        transcript = f"Наслов: {naslov_yt}. (Без титлови.)" # ako ima samo naslov go zima naslovot samo 
    vest = _generiraj_vest(transcript, naslov_yt)   # se povikuva groq da gi sobere informaciite i da gi pretvore vo vest
    if vest.get("_error"):  #ako se dobie nekoj error pri obrabotkata 
        return f"Грешка: {vest['_error']}"  # ni se pecate greska
    # vo sprotivno se:
    thumbnail = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"   #avtomatski generira thumbnail identicen kako toj na videoto
    embed = f"https://www.youtube-nocookie.com/embed/{vid}" # go vgraduvame videot vo pleerot na sajtot bez kolacinja site kolacinja se trganit

    conn = get_connection() # se ostvaruva konekcija so bazata na podatoci i se ovozmozuva manipulacija so podatoci vo istata 
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO Novosti (naslov, sodrzina, slika_path, video_url, author_doctor_id)"
        " VALUES (%s, %s, %s, %s, %s)",
        (vest["naslov"], vest["sodrzina"], thumbnail, embed, lekar["doctor_ID"]),   # se smestiva vo bazata na podatoci
    )
    conn.commit()
    new_id = cur.lastrowid
    cur.close()
    conn.close()

    link = f"[[Новости|novosti.html?id={new_id}]]"  # link koj vo ai agento moze da ne direkto odnese do novostite i da se vide dali e objavena ili pa ne e 
    return {
        "odgovor": (
            "Веста е објавена!\n\n"
            f"Можете да ја погледнете во делот за {link} на сајтот!"
        ),
        "kontekst": {
            "last_vest_id": int(new_id),
            "last_vest_naslov": vest["naslov"],
            "last_action": "objavi_vest",
        },
    }
