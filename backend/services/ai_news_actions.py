# standardni biblioteki za rabota so html, json, regex i HTTP baranja
import html
import json
import re
import urllib.parse
import urllib.request
from urllib.parse import urljoin   # urljoin se koristi za spojuvanje na relativni URL-ovi so osnoven URL
from routers.admin import check_admin_access # import na funkcija za proverka na admin pristap
from routers.novosti import insert_novost_from_ai # import na funkcija koja zacuvuva nova novost vo bazata
from services.ai_parser import parse_news # import na AI parser koj generira naslov i sodrzina od tekst

# globalen recnik koj cuva privremen predlog za novost po admin (kluc = admin_doctor_id)
PENDING_NEWS_CACHE = {}
# pomosna funkcija koja vraka string vo mali bukvi i bez praznini na rabovite
def _mk_lower(s: str) -> str:
    return str(s or "").strip().lower()


# pomosna funkcija koja go vlece ID-to na lekarot/admin od pacient ili state recnikot
def _extract_actor_id(pacient: dict, state: dict) -> int:
    # se proveruvaat poveke moznosti za ID po prioritet
    raw_id = (
        (pacient or {}).get("doctor_ID") # prvo se proveruva 'doctor_ID' vo pacient
        or (pacient or {}).get("doctor_id") # potoa varijantata 'doctor_id' (mali bukvi)
        or (pacient or {}).get("id") # potoa opstiot kluc 'id'
        or (state or {}).get("admin_doctor_id")  # 'admin_doctor_id' vo state recnikot
        or (state or {}).get("doctor_id")   # i na kraj 'doctor_id' vo state recnikot
    )
    # se obiduvame da go konvertirame vo cel broj
    try:
        return int(raw_id)
    # vo sprotivno vrakame 0 kako default vrednost
    except Exception:
        return 0


# funkcija koja go vlece prviot URL od dadeniot tekst preku regex
def _extract_first_url(prompt_text: str) -> str:
   m = re.search(r"(https?://[^\s\])>\"']+)", str(prompt_text or "")) # regex koj prepoznava http ili https URL i ne vlece specijalni karakteri kako kraj
   return m.group(1).strip() if m else ""  # vrakame go najdeniot URL ili prazen string ako nema match

# proverka dali daden URL e YouTube link
def _is_youtube_url(url: str) -> bool:
    u = _mk_lower(url) # se konvertira vo mali bukvi za case-insensitive proverka
    return "youtube.com/" in u or "youtu.be/" in u # vrakame True ako sodrzi nekoja od dvete YouTube domeni


# vlecenje na ID na YouTube video od URL preku regex
def _extract_youtube_video_id(url: str) -> str:
    u = str(url or "").strip()
    m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{6,})", u) # regex koj prepoznava razlicni formi na YouTube URL-ovi i go zima ID-to
    return m.group(1) if m else "" # vrakame ID ili prazen string ako nema match


# funkcija koja go vlece transkriptot (titlovite) na YouTube video
def _fetch_youtube_transcript(source_url: str, raw_html: str) -> str:
    html_text = str(raw_html or "")  # se osiguruvame deka raw_html e string
    video_id = _extract_youtube_video_id(source_url)  # se zima ID-to na videoto
    # ako nema ID, vrakame prazen string
    if not video_id:
        return ""

    # baranje na captionTracks vo HTML stranata (taa e JSON koj sodrzi linkovi do titlovite)
    tracks_match = re.search(r'"captionTracks":(\[.*?\])', html_text)
    if not tracks_match:    # ako ne najde captionTracks, vrakame prazen string
        return ""

    # se obiduvame da go parsirame JSON-ot na tracks
    try:
        tracks = json.loads(tracks_match.group(1))
    # ako parsiranjeto fali, vrakame prazno
    except Exception:
        return ""
    # proverka deka tracks e neprazna lista
    if not isinstance(tracks, list) or not tracks:
        return ""

    # listata na jazici po prioritet (makedonski, srpski, hrvatski, bugarski, angliski)
    preferred_langs = ("mk", "sr", "hr", "bg", "en")
    chosen = None
    # iteracija niz preferiranite jazici
    for lang in preferred_langs:
        # iteracija niz site dostapni titlovi
        for t in tracks:
            # se zima jaziciot na titlot
            code = str((t or {}).get("languageCode") or "").lower()
            # ako jaziciot pocnuva so preferiraniot kod, go izbirame
            if code.startswith(lang):
                chosen = t
                break
        # ako vekje sme izbrale, prekinuvame nadvoresnata jamka
        if chosen:
            break
    # ako ne najde nikoj preferiran, zima go prviot dostapen
    if not chosen:
        chosen = tracks[0]

    # se zima base URL-ot za titlovite
    base_url = str((chosen or {}).get("baseUrl") or "").strip()
    if not base_url:
        return ""

    # ako URL-ot nema fmt parametar, dodavame fmt=json3 za polesno parsiranje
    if "fmt=" not in base_url:
        sep = "&" if "?" in base_url else "?"
        base_url = f"{base_url}{sep}fmt=json3"

    # praveme HTTP baranje so User-Agent zaglavie
    req = urllib.request.Request(base_url, headers={"User-Agent": "Mozilla/5.0 (compatible; KBStipAI/1.0)"})
    # otvoranje na konekcijata so timeout od 15 sekundi
    with urllib.request.urlopen(req, timeout=15) as resp:
        # citanje na odgovorot vo UTF-8
        body = resp.read().decode("utf-8", errors="ignore")

    # primarna obrabotka kako JSON3 format
    try:
        payload = json.loads(body)
        # se zimaat events (segmenti od titlot)
        events = payload.get("events") or []
        out = []
        # iteracija niz site segmenti
        for ev in events:
            # se zimaat segs (parcinja od subtitle)
            segs = (ev or {}).get("segs") or []
            # se spojuva tekstot od site segs
            chunk = "".join(str((s or {}).get("utf8") or "") for s in segs)
            # se ciste belite prazni i HTML entiteti
            chunk = re.sub(r"\s+", " ", html.unescape(chunk)).strip()
            # ako ima tekst, go dodavame
            if chunk:
                out.append(chunk)
        # ako sobravme tekstovi, gi vrakame spoeni
        if out:
            return " ".join(out).strip()
    # ako parsiranjeto na JSON falese, prefrlame na fallback (XML format)
    except Exception:
        pass

    # fallback: se vlecat tekstovi pomegu < i > tagovi (za XML format)
    chunks = re.findall(r'>([^<]+)<', body)
    cleaned = []
    # iteracija niz najdenite parcinja
    for c in chunks:
        # ciste tekstot od HTML entiteti i prazni mesta
        txt = re.sub(r"\s+", " ", html.unescape(c)).strip()
        # preskoknuvame nevalidni redovi (prazno, XML deklaracija, naslov "transcript")
        if not txt or txt.startswith("<?xml") or txt.lower() in ("transcript",):
            continue
        cleaned.append(txt)
    # vrakame go spoeniot tekst
    return " ".join(cleaned).strip()


# funkcija koja prepravat HTTP GET baranje za HTML sodrzina od dadena URL
def _download_webpage_html(url: str) -> str:
    # baranje so User-Agent (nekoi serveri ne dozvoluvaat baranja bez UA)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; KBStipAI/1.0)"},
    )
    # otvoranje na konekcija so timeout od 15 sekundi
    with urllib.request.urlopen(req, timeout=15) as resp:
        # se zima encoding-ot od zaglavija ili default utf-8
        charset = resp.headers.get_content_charset() or "utf-8"
        # citanje i dekodiranje na sodrzinata
        return resp.read().decode(charset, errors="ignore")


# funkcija koja vlece cist tekst od HTML stranata (otstranuva tagovi, skripti, stilovi)
def _extract_text_from_html(raw_html: str) -> str:
    raw = str(raw_html or "")
    # otstranuvanje na <script> tagovi i nivnata sodrzina
    raw = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
    # otstranuvanje na <style> tagovi
    raw = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw)
    # otstranuvanje na <noscript> tagovi
    raw = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", raw)
    # otstranuvanje na site preostanati HTML tagovi
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    # konverzija na HTML entiteti vo normalni karakteri (&amp; -> &)
    raw = html.unescape(raw)
    # zameneuvanje na poveke prazni mesta so eden razmak i otstranuvanje na rabovite
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


# funkcija koja vlece tekstualna informacija od YouTube stranata (naslov, opis, avtor, transkript)
def _extract_youtube_text(raw_html: str, source_url: str) -> str:
    html_text = str(raw_html or "")
    # inicijalizacija na pole iza naslov, opis i avtor
    title = ""
    description = ""
    author = ""

    # vlecenje na og:title (Open Graph naslov) preku regex
    og_title_m = re.search(r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if og_title_m:
        # ciste tekstot od HTML entiteti i prazni mesta
        title = re.sub(r"\s+", " ", html.unescape(og_title_m.group(1))).strip()

    # ako nema og:title, probuvame so <title> tagot
    if not title:
        title_m = re.search(r"(?is)<title>(.*?)</title>", html_text)
        if title_m:
            title = re.sub(r"\s+", " ", html.unescape(title_m.group(1))).strip()
    # otstranuvanje na sufiks " - YouTube" od naslovot
    title = re.sub(r"\s*-\s*YouTube\s*$", "", title, flags=re.IGNORECASE).strip()

    # vlecenje na og:description (Open Graph opis)
    og_desc_m = re.search(r'(?is)<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if og_desc_m:
        description = re.sub(r"\s+", " ", html.unescape(og_desc_m.group(1))).strip()
    # ako nema og:description, probuvame so meta name="description"
    if not description:
        desc_m = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html_text)
        if desc_m:
            description = re.sub(r"\s+", " ", html.unescape(desc_m.group(1))).strip()
    # otstranuvanje na site URL-ovi od opisot
    description = re.sub(r"https?://\S+", "", description).strip()

    # vlecenje na imeto na avtorot/kanalot
    chan_m = re.search(r'(?is)<meta[^>]+itemprop=["\']author["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if chan_m:
        author = re.sub(r"\s+", " ", html.unescape(chan_m.group(1))).strip()

    # obid za vlecenje na podatoci preku YouTube oEmbed API kako fallback
    try:
        # gradnje na URL za oEmbed barenjeto
        oembed_url = "https://www.youtube.com/oembed?url=" + urllib.parse.quote(source_url, safe="") + "&format=json"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0 (compatible; KBStipAI/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            # parsiranje na JSON odgovor
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
            # ako oEmbed vrati naslov a nemame, go koristime
            if payload.get("title") and not title:
                title = str(payload.get("title")).strip()
                title = re.sub(r"\s*-\s*YouTube\s*$", "", title, flags=re.IGNORECASE).strip()
            # ako oEmbed vrati avtor a nemame, go koristime
            if payload.get("author_name") and not author:
                author = str(payload.get("author_name")).strip()
    # ako oEmbed fali, samo prodolzuvame natamu
    except Exception:
        pass

    # vlecenje na transkriptot (titlovite) na videoto
    transcript = _fetch_youtube_transcript(source_url, raw_html)

    # gradnje na finalniot tekst od site najdeni informacii
    parts = []
    if title:
        parts.append(f"Наслов на видео: {title}")
    if author:
        parts.append(f"Автор: {author}")
    if transcript:
        parts.append(f"Транскрипт: {transcript}")
    if description:
        # opisot se ogranichuva na 500 karakteri
        parts.append(f"Краток опис: {description[:500]}")
    # se dodava i izvorniot URL
    parts.append(f"Извор: {source_url}")
    # vrakame gi delovite spoeni so nov red
    return "\n".join(parts).strip()


# fallback funkcija koja gradi naslov i sodrzina ako AI parserot fali
def _fallback_news_draft(source_text: str, source_url: str):
    # cisten tekst od poveke prazni mesta
    clean = re.sub(r"\s+", " ", str(source_text or "")).strip()
    # ako nemame tekst, koristime samo URL
    if not clean:
        clean = f"Информација од извор: {source_url}"

    # delenje na recenicii so kraj na recenica (. ! ?)
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    # filtriranje na samo recenicii so dovolno znaci (preku 12)
    sentences = [s.strip() for s in sentences if s and len(s.strip()) > 12]
    # ako nema validni recenicii, koristime go celiot tekst kako edna recenica
    if not sentences:
        sentences = [clean]

    # se gradi naslov od prvata recenica, isciste rabovi i interpunkcija
    first = re.sub(r"\s+", " ", sentences[0]).strip(" .,:;-")
    # naslovot se ogranichuva na 110 karakteri
    naslov = first[:110] if first else "Нова информација од медиум"
    # ako e premnogu kratok, koristime default
    if len(naslov) < 8:
        naslov = "Нова информација од медиум"

    # sodrzinata se gradi od prvite 4 recenicii
    body_parts = sentences[:4]
    sodrzina = " ".join(body_parts).strip()
    # ako sodrzinata e kratka, dodavame izvor i napomena
    if len(sodrzina) < 120:
        sodrzina = (
            f"{sodrzina} Извор: {source_url}. "
            "Ова е автоматски подготвен предлог и може да се доуреди пред објава."
        ).strip()
    # vrakame ja dvojkata naslov i sodrzina
    return naslov, sodrzina


# funkcija koja go cisti generiraniot naslov i sodrzina od AI-to
def _clean_generated_news(naslov: str, sodrzina: str) -> tuple[str, str]:
    # otstranuvanje na YouTube sufiks od naslovot
    clean_title = re.sub(r"\s*-\s*YouTube\s*$", "", str(naslov or ""), flags=re.IGNORECASE).strip()
    # zameneuvanje na poveke prazni mesta so eden razmak
    clean_title = re.sub(r"\s+", " ", clean_title)
    # otstranuvanje na URL-ovi i interpunkcija na rabovite
    clean_title = re.sub(r"https?://\S+", "", clean_title).strip(" .,:;-")
    # ako naslovot e premnogu kratok, koristime default
    if len(clean_title) < 8:
        clean_title = "Нова информација од медиум"

    # se osiguruvame deka sodrzinata e string
    clean_body = str(sodrzina or "")
    # otstranuvanje na URL-ovi od sodrzinata
    clean_body = re.sub(r"https?://\S+", "", clean_body)
    # otstranuvanje na metapodatocite "Naslov", "Avtor", "Kanal"
    clean_body = re.sub(r"\b(?:Наслов на видео|Автор|Канал)\s*:\s*", "", clean_body, flags=re.IGNORECASE)
    # ciste belite prazni i rabovi
    clean_body = re.sub(r"\s+", " ", clean_body).strip()
    # ako sodrzinata e predolga, ja skratuvame na 900 karakteri (na zborovni granici)
    if len(clean_body) > 900:
        clean_body = clean_body[:900].rsplit(" ", 1)[0].strip() + "..."
    # vrakame ja dvojkata cisten naslov i sodrzina
    return clean_title, clean_body


# funkcija koja vlece slika i video URL od HTML stranata
def _extract_media_urls_from_html(raw_html: str, source_url: str):
    html_text = str(raw_html or "")

    # inicijalizacija na URL-ovite
    image_url = ""
    video_url = ""

    # vlecenje na og:image (Open Graph slika)
    og_img = re.search(r'(?is)<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if og_img:
        image_url = og_img.group(1).strip()

    # ako nema og:image, probuvame so prviot <img> tag
    if not image_url:
        first_img = re.search(r'(?is)<img[^>]+src=["\']([^"\']+)["\']', html_text)
        if first_img:
            image_url = first_img.group(1).strip()

    # vlecenje na og:video (Open Graph video)
    og_video = re.search(r'(?is)<meta[^>]+property=["\']og:video(?::url)?["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if og_video:
        video_url = og_video.group(1).strip()

    # ako nema og:video, probuvame so prviot <video> tag
    if not video_url:
        first_video = re.search(r'(?is)<video[^>]+src=["\']([^"\']+)["\']', html_text)
        if first_video:
            video_url = first_video.group(1).strip()

    # ako sé uste nema video, probuvame so <iframe> tag (samo YouTube/Vimeo se prifakaat)
    if not video_url:
        iframe = re.search(r'(?is)<iframe[^>]+src=["\']([^"\']+)["\']', html_text)
        if iframe:
            iframe_url = iframe.group(1).strip()
            # samo ako iframe-ot e od YouTube ili Vimeo, go zimame
            if "youtube.com" in _mk_lower(iframe_url) or "vimeo.com" in _mk_lower(iframe_url):
                video_url = iframe_url

    # ako image URL-ot e relativen (ne pocnuva so http/https), go spojuvame so source_url
    if image_url and not image_url.startswith("http://") and not image_url.startswith("https://"):
        image_url = urljoin(source_url, image_url)
    # isto za video URL
    if video_url and not video_url.startswith("http://") and not video_url.startswith("https://"):
        video_url = urljoin(source_url, video_url)

    # vrakame gi dvete URL-ovi
    return image_url, video_url


# glavna funkcija koja go obrabotuva intentot za novosti (preview ili confirm)
def handle_news_intent(intent: str, prompt: str, pacient: dict, state: dict):
    # ako intentot ne e nieden od podderzhanite, vrakame None
    if intent not in ("news_publish_preview", "news_publish_confirm"):
        return None

    # se zima admin/doctor ID-to od pacient ili state
    admin_doctor_id = _extract_actor_id(pacient, state)

    # GRANKA 1: priprema na preview (predlog) za novost
    if intent == "news_publish_preview":
        # proverka deka korisnikot e admin/direktor
        if not admin_doctor_id or not check_admin_access(admin_doctor_id):
            return {
                "ok": False,
                "intent": intent,
                "message": "За објавување новости мора да сте најавени како директор на болницата.",
                "state": state,
            }
        # vlecenje na URL od promptot
        source_url = _extract_first_url(prompt)
        # ako nema URL, vrakame poraka so greska
        if not source_url:
            return {
                "ok": False,
                "intent": intent,
                "message": "Недостига валиден линк. Внесете целосен URL (http/https) за обработка на веста.",
                "state": state,
            }
        # obid za prevzemanje na HTML sodrzinata
        try:
            raw_html = _download_webpage_html(source_url)
        # ako prevzemanjeto fali, vrakame poraka deka linkot ne e dostapen
        except Exception:
            return {
                "ok": False,
                "intent": intent,
                "message": "Не можев да ја прочитам содржината од линкот. Проверете дали линкот е достапен.",
                "state": state,
            }
        # ako e YouTube, koristi specijalna funkcija za vlecenje na tekst
        if _is_youtube_url(source_url):
            source_text = _extract_youtube_text(raw_html, source_url)
        # vo sprotivno koristi obicen HTML parser
        else:
            source_text = _extract_text_from_html(raw_html)
        # ako tekstot e premnogu kratok, dodavame placeholder za AI da generira
        if len(source_text) < 80:
            source_text = (
                "Нема доволно текст директно извлечен од линкот. "
                f"Извор: {source_url}. Подготви краток формален предлог за болничка вест."
            )
        # vlecenje na slika i video URL od HTML
        media_image_url, media_video_url = _extract_media_urls_from_html(raw_html, source_url)
        # povik kon AI parserot za generiranje na naslov i sodrzina (do 8000 karakteri tekst)
        ai_news = parse_news(source_text[:8000], prompt)
        # ako AI ne vrati nista, koristime fallback
        if not ai_news:
            naslov, sodrzina = _fallback_news_draft(source_text, source_url)
        else:
            # se zimaat naslov i sodrzina od AI rezultatot
            naslov = (ai_news.get("naslov") or "").strip()
            sodrzina = (ai_news.get("sodrzina") or "").strip()
            # ako AI ne vrati naslov ili sodrzina, koristime fallback
            if not naslov or not sodrzina:
                naslov, sodrzina = _fallback_news_draft(source_text, source_url)
        # ciste i naslovot i sodrzinata
        naslov, sodrzina = _clean_generated_news(naslov, sodrzina)
        # gradi nov state recnik (ne menuvame go originalniot)
        new_state = dict(state)
        # zacuvuvanje na predlogot vo state-ot za potoa da go potvrdi korisnikot
        new_state["pending_news"] = {
            "naslov": naslov,
            "sodrzina": sodrzina,
            "source_url": source_url,
            "slika_url": media_image_url,
            "video_url": media_video_url,
        }
        # zacuvuvanje vo globalniot cache spored admin ID
        if admin_doctor_id:
            PENDING_NEWS_CACHE[int(admin_doctor_id)] = dict(new_state["pending_news"])
        # gradnje na poraka so info za media (slika/video) ako postojat
        media_note = []
        if media_image_url:
            media_note.append(f"Слика: {media_image_url}")
        if media_video_url:
            media_note.append(f"Видео: {media_video_url}")
        # spojuvanje na media porakata so nov red (chr(10) e \n)
        media_block = f"\n{chr(10).join(media_note)}\n" if media_note else "\n"
        # vrakanje na rezultat so cel predlog za korisnikot da go potvrdi
        return {
            "ok": True,
            "intent": intent,
            "message": (
                "Веста е обработена. Еве го предлогот за објава:\n"
                f"Наслов: {naslov}\n"
                f"Текст: {sodrzina}{media_block}\n"
                "Дали сакате веднаш да ја објавам оваа содржина на почетната страна на веб-сајтот?"
            ),
            "state": new_state,
        }

    # GRANKA 2: potvrda i objavuvanje na predlogot
    # se zima predlogot od state-ot
    pending_news = (state or {}).get("pending_news") or {}
    # ako nema vo state, probuvame od globalniot cache
    if not pending_news and admin_doctor_id:
        pending_news = PENDING_NEWS_CACHE.get(int(admin_doctor_id), {}) or {}
    # se zimaat poliata od predlogot
    naslov = (pending_news.get("naslov") or "").strip()
    sodrzina = (pending_news.get("sodrzina") or "").strip()
    slika_url = (pending_news.get("slika_url") or "").strip()
    video_url = (pending_news.get("video_url") or "").strip()
    # ako nema naslov ili sodrzina, vrakame deka nema predlog
    if not naslov or not sodrzina:
        return {
            "ok": False,
            "intent": intent,
            "message": "Нема подготвен предлог за објава. Прво пратете линк за обработка на вест.",
            "state": state,
        }

    # ponovna proverka na admin pristap pred snimanje vo bazata
    if not admin_doctor_id or not check_admin_access(admin_doctor_id):
        return {
            "ok": False,
            "intent": intent,
            "message": "Немате дозвола за објавување. Само директорот може да објавува новости.",
            "state": state,
        }

    # snimanje na novosta vo bazata preku pomosna funkcija
    new_id = insert_novost_from_ai(
        naslov=naslov,
        sodrzina=sodrzina,
        admin_doctor_id=admin_doctor_id,
        slika_url=slika_url,
        video_url=video_url,
    )
    # gradi nov state bez pending_news (vekje e objaveno)
    new_state = dict(state)
    new_state.pop("pending_news", None)
    # otstranuvanje od globalniot cache
    if admin_doctor_id:
        PENDING_NEWS_CACHE.pop(int(admin_doctor_id), None)
    # vrakame uspesna poraka so ID-to na novata novost
    return {
        "ok": True,
        "intent": intent,
        "message": "Успешно објавено. Веста е веќе видлива за сите посетители.",
        "news_id": new_id,
        "state": new_state,
    }
