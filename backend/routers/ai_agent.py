import re
from datetime import datetime, timedelta
import html
import json
import urllib.request
import urllib.parse
from urllib.parse import urljoin

from fastapi import APIRouter, HTTPException, Request

from database import get_connection
from services.ai_parser import parse_news, parse_prompt
from services.ai_patient_actions import handle_patient_action
from routers.admin import check_admin_access
from routers.novosti import insert_novost_from_ai

router = APIRouter(prefix="/ai-agent", tags=["ai-agent"])
# Fallback cache за 2-чекор flow (preview -> confirm), ако frontend не го прати state.
# Клуч: admin_doctor_id, Вредност: pending_news dict
PENDING_NEWS_CACHE = {}


def _mk_lower(s: str) -> str:
    return str(s or "").strip().lower()


def _izvadi_iso_datum(prompt_text: str) -> str:
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", str(prompt_text or ""))
    return m.group(1) if m else ""


def _izvadi_relativen_ili_iso_datum(prompt_text: str, fallback_iso: str = "") -> str:
    text = _mk_lower(prompt_text)
    today = datetime.now().date()
    if "задутре" in text:
        return (today + timedelta(days=2)).isoformat()
    if "утре" in text:
        return (today + timedelta(days=1)).isoformat()
    if "денес" in text:
        return today.isoformat()
    return _izvadi_iso_datum(prompt_text) or fallback_iso


def _extract_time(prompt_text: str) -> str:
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", str(prompt_text or ""))
    if not m:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _extract_note(prompt_text: str) -> str:
    text = str(prompt_text or "")
    idx = _mk_lower(text).find("напомена")
    if idx < 0:
        return ""
    return re.sub(r"^[:\s-]+", "", text[idx + len("напомена"):]).strip()


def _contains_any(text: str, needles) -> bool:
    t = _mk_lower(text)
    return any(n in t for n in needles)


def _detect_intent(prompt_text: str) -> str:
    text = _mk_lower(prompt_text)
    if _contains_any(text, ["најнови информации", "што е ново", "новости", "нови вести"]) and _contains_any(text, ["болница", "пациент", "пациенти"]):
        return "hospital_updates"
    asks_people = _contains_any(text, ["кој", "кои", "каков состав", "листа"])
    mentions_doctors = _contains_any(text, ["лекар", "доктор", "уролог", "кардиолог", "радиолог", "педијатар", "хирург"])
    mentions_department = _contains_any(text, ["оддел", "служб", "специјалност", "област", "тим"])
    if asks_people and (mentions_doctors or mentions_department):
        return "department_doctors"
    if _contains_any(text, ["да, објави", "да објави", "објави веднаш"]) or text.strip() == "објави":
        return "news_publish_confirm"
    if _contains_any(text, ["објави", "вести", "вест", "новост", "додади новост", "објава"]):
        return "news_publish_preview"
    if _contains_any(text, ["апарат", "опрема", "уред"]) and _contains_any(text, ["оддел", "област", "служб", "специјалност"]):
        return "department_equipment"
    if mentions_doctors and _contains_any(text, ["недела", "оваа недела", "во неделава", "седмица"]):
        return "specialty_week_availability"
    if _contains_any(text, ["мои термини", "моите термини", "мој термин", "моите закажани"]):
        return "patient_list_appointments"
    if _contains_any(text, ["откажи", "поништи термин", "избриши термин"]):
        return "patient_cancel_appointment"
    if _contains_any(text, ["промени термин", "премести термин", "презакажи"]):
        return "patient_reschedule_appointment"
    if _contains_any(text, ["потсетник", "потсети ме", "подсети ме"]):
        return "patient_set_reminder"
    if _contains_any(text, ["закаж", "резерв", "термин во"]):
        return "book"
    if _contains_any(text, ["слобод", "достап", "провери", "има ли", "кога има"]):
        return "availability"
    return ""


def _normalize_intent(value: str) -> str:
    v = _mk_lower(value)
    if v in (
        "availability",
        "book",
        "specialty_week_availability",
        "department_equipment",
        "department_doctors",
        "hospital_updates",
        "news_publish_preview",
        "news_publish_confirm",
        "patient_list_appointments",
        "patient_cancel_appointment",
        "patient_reschedule_appointment",
        "patient_set_reminder",
    ):
        return v
    if "publish" in v and "confirm" in v:
        return "news_publish_confirm"
    if "publish" in v or "news" in v:
        return "news_publish_preview"
    if "aparat" in v or "equipment" in v:
        return "department_equipment"
    if "doctor" in v and "department" in v:
        return "department_doctors"
    if "specialty" in v and "week" in v:
        return "specialty_week_availability"
    if "update" in v or ("news" in v and "hospital" in v):
        return "hospital_updates"
    if "закаж" in v:
        return "book"
    if "cancel" in v:
        return "patient_cancel_appointment"
    if "reschedule" in v or "change appointment" in v:
        return "patient_reschedule_appointment"
    if "my appointment" in v or "list appointment" in v:
        return "patient_list_appointments"
    if "reminder" in v:
        return "patient_set_reminder"
    if "слобод" in v or "достап" in v or "провери" in v:
        return "availability"
    return ""

# tuka se gleda dali i koj termini se slobodni 
def _list_busy_times(db_cursor, doctor_id: int, date_iso: str):
    db_cursor.execute(
        """
        SELECT TIME(vreme_pregled) AS vreme
        FROM Termin_pregled
        WHERE doctor_ID = %s AND DATE(datum_pregled) = %s AND status_pregled = 'закажан'
        UNION
        SELECT TIME(vreme_pregled) AS vreme
        FROM Aparati_termini
        WHERE doctor_ID = %s AND DATE(datum_pregled) = %s AND status != 'откажан'
        """,
        (doctor_id, date_iso, doctor_id, date_iso),
    )
    # se zimat site redovi so se free ako ima, onala se vraka [prazna lista]
    rows = db_cursor.fetchall() or []
    out = set()
    for r in rows:
        # tuka se gledaat slobodnite vreminja
        v = r.get("vreme")
        if v is None:
            continue
        if hasattr(v, "strftime"):
            out.add(v.strftime("%H:%M"))
        elif hasattr(v, "total_seconds"):
            s = int(v.total_seconds())
            out.add(f"{s // 3600:02d}:{(s % 3600) // 60:02d}")
        else:
            out.add(str(v)[:5])
    return out


def _build_workday_slots():
    return [f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)]


def _format_mk_date(date_iso: str) -> str:
    try:
        parsed = datetime.strptime(date_iso, "%Y-%m-%d").date()
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return date_iso


def _find_selected_doctor(doctors, prompt_l: str, parsed_doctor_name: str, state):
    selected_doctor = None
    cleaned_prompt = re.sub(r"\b(д-р|dr\.?|doctor)\b", " ", prompt_l)
    cleaned_prompt = re.sub(r"\s+", " ", cleaned_prompt).strip()
    cleaned_parsed = re.sub(r"\b(д-р|dr\.?|doctor)\b", " ", parsed_doctor_name)
    cleaned_parsed = re.sub(r"\s+", " ", cleaned_parsed).strip()

    for d in doctors:
        name = _mk_lower(d.get("name", ""))
        surname = _mk_lower(d.get("surname", ""))
        full = _mk_lower(f"{name} {surname}")
        if not full:
            continue
        if (
            full in prompt_l
            or full in cleaned_prompt
            or (cleaned_parsed and full in cleaned_parsed)
            or (surname and surname in cleaned_prompt)
            or (surname and cleaned_parsed and surname in cleaned_parsed)
        ):
            selected_doctor = d
            break

    if not selected_doctor and state.get("doctor_id"):
        for d in doctors:
            if int(d.get("doctor_ID") or 0) == int(state.get("doctor_id")):
                selected_doctor = d
                break

    return selected_doctor


def _extract_specialty(prompt_text: str, state):
    text = _mk_lower(prompt_text)
    if _contains_any(text, ["кардиолог", "кардио"]):
        return "Кардиологија"
    if _contains_any(text, ["радиолог", "радио оддел"]):
        return "Радиологија"
    if _contains_any(text, ["педијатр", "детски"]):
        return "Педијатрија"
    if _contains_any(text, ["хирург", "хирурш", "оператив"]):
        return "Хирургија"
    if _contains_any(text, ["уролог", "уролош", "уро"]):
        return "Урологија"
    if _contains_any(text, ["интерна", "внатрешни болести"]):
        return "Интерна медицина"
    if "овој оддел" in text and state.get("specialty"):
        return state.get("specialty")
    return state.get("specialty", "")


def _doctors_by_specialty(doctors, specialty: str):
    s = _mk_lower(specialty)
    return [d for d in doctors if s in _mk_lower(d.get("specialty", ""))]


def _validate_workday_date(date_iso: str):
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except ValueError:
        return False, "Неважечки датум. Користете YYYY-MM-DD."
    if d.weekday() >= 5:
        return False, "Не се закажуваат прегледи во сабота и недела."
    return True, ""


def _extract_first_url(prompt_text: str) -> str:
    m = re.search(r"(https?://[^\s\])>\"']+)", str(prompt_text or ""))
    return m.group(1).strip() if m else ""


def _is_youtube_url(url: str) -> bool:
    u = _mk_lower(url)
    return "youtube.com/" in u or "youtu.be/" in u


def _extract_youtube_video_id(url: str) -> str:
    u = str(url or "").strip()
    m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{6,})", u)
    return m.group(1) if m else ""


def _fetch_youtube_transcript(source_url: str, raw_html: str) -> str:
    """
    Вади транскрипт од YouTube captions ако се достапни.
    """
    html_text = str(raw_html or "")
    video_id = _extract_youtube_video_id(source_url)
    if not video_id:
        return ""

    tracks_match = re.search(r'"captionTracks":(\[.*?\])', html_text)
    if not tracks_match:
        return ""

    try:
        tracks = json.loads(tracks_match.group(1))
    except Exception:
        return ""
    if not isinstance(tracks, list) or not tracks:
        return ""

    # Prefer Macedonian/Serbian/Croatian/Bulgarian/English captions if present.
    preferred_langs = ("mk", "sr", "hr", "bg", "en")
    chosen = None
    for lang in preferred_langs:
        for t in tracks:
            code = str((t or {}).get("languageCode") or "").lower()
            if code.startswith(lang):
                chosen = t
                break
        if chosen:
            break
    if not chosen:
        chosen = tracks[0]

    base_url = str((chosen or {}).get("baseUrl") or "").strip()
    if not base_url:
        return ""

    # json3 format is easiest for parsing subtitles.
    if "fmt=" not in base_url:
        sep = "&" if "?" in base_url else "?"
        base_url = f"{base_url}{sep}fmt=json3"

    req = urllib.request.Request(base_url, headers={"User-Agent": "Mozilla/5.0 (compatible; KBStipAI/1.0)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8", errors="ignore")

    # Preferred: json3 subtitles
    try:
        payload = json.loads(body)
        events = payload.get("events") or []
        out = []
        for ev in events:
            segs = (ev or {}).get("segs") or []
            chunk = "".join(str((s or {}).get("utf8") or "") for s in segs)
            chunk = re.sub(r"\s+", " ", html.unescape(chunk)).strip()
            if chunk:
                out.append(chunk)
        if out:
            return " ".join(out).strip()
    except Exception:
        pass

    # Fallback: XML/TTML subtitles
    chunks = re.findall(r'>([^<]+)<', body)
    cleaned = []
    for c in chunks:
        txt = re.sub(r"\s+", " ", html.unescape(c)).strip()
        # Skip metadata-like fragments
        if not txt or txt.startswith("<?xml") or txt.lower() in ("transcript",):
            continue
        cleaned.append(txt)
    return " ".join(cleaned).strip()


def _extract_actor_id(pacient: dict, state: dict) -> int:
    raw_id = (
        (pacient or {}).get("doctor_ID")
        or (pacient or {}).get("doctor_id")
        or (pacient or {}).get("id")
        or (state or {}).get("admin_doctor_id")
        or (state or {}).get("doctor_id")
    )
    try:
        return int(raw_id)
    except Exception:
        return 0


def _download_webpage_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; KBStipAI/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="ignore")


def _extract_text_from_html(raw_html: str) -> str:
    raw = str(raw_html or "")
    raw = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw)
    raw = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _extract_youtube_text(raw_html: str, source_url: str) -> str:
    html_text = str(raw_html or "")
    title = ""
    description = ""
    author = ""

    og_title_m = re.search(r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if og_title_m:
        title = re.sub(r"\s+", " ", html.unescape(og_title_m.group(1))).strip()

    if not title:
        title_m = re.search(r"(?is)<title>(.*?)</title>", html_text)
        if title_m:
            title = re.sub(r"\s+", " ", html.unescape(title_m.group(1))).strip()
    title = re.sub(r"\s*-\s*YouTube\s*$", "", title, flags=re.IGNORECASE).strip()

    og_desc_m = re.search(r'(?is)<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if og_desc_m:
        description = re.sub(r"\s+", " ", html.unescape(og_desc_m.group(1))).strip()
    if not description:
        desc_m = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html_text)
        if desc_m:
            description = re.sub(r"\s+", " ", html.unescape(desc_m.group(1))).strip()
    description = re.sub(r"https?://\S+", "", description).strip()

    chan_m = re.search(r'(?is)<meta[^>]+itemprop=["\']author["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if chan_m:
        author = re.sub(r"\s+", " ", html.unescape(chan_m.group(1))).strip()

    # YouTube oEmbed provides a reliable title/author fallback.
    try:
        oembed_url = "https://www.youtube.com/oembed?url=" + urllib.parse.quote(source_url, safe="") + "&format=json"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0 (compatible; KBStipAI/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if payload.get("title") and not title:
                title = str(payload.get("title")).strip()
                title = re.sub(r"\s*-\s*YouTube\s*$", "", title, flags=re.IGNORECASE).strip()
            if payload.get("author_name") and not author:
                author = str(payload.get("author_name")).strip()
    except Exception:
        pass

    transcript = _fetch_youtube_transcript(source_url, raw_html)

    parts = []
    if title:
        parts.append(f"Наслов на видео: {title}")
    if author:
        parts.append(f"Автор: {author}")
    if transcript:
        # Use transcript as primary source when available.
        parts.append(f"Транскрипт: {transcript}")
    if description:
        parts.append(f"Краток опис: {description[:500]}")
    parts.append(f"Извор: {source_url}")
    return "\n".join(parts).strip()


def _fallback_news_draft(source_text: str, source_url: str):
    clean = re.sub(r"\s+", " ", str(source_text or "")).strip()
    if not clean:
        clean = f"Информација од извор: {source_url}"

    sentences = re.split(r"(?<=[.!?])\s+", clean)
    sentences = [s.strip() for s in sentences if s and len(s.strip()) > 12]
    if not sentences:
        sentences = [clean]

    first = re.sub(r"\s+", " ", sentences[0]).strip(" .,:;-")
    naslov = first[:110] if first else "Нова информација од медиум"
    if len(naslov) < 8:
        naslov = "Нова информација од медиум"

    body_parts = sentences[:4]
    sodrzina = " ".join(body_parts).strip()
    if len(sodrzina) < 120:
        sodrzina = (
            f"{sodrzina} Извор: {source_url}. "
            "Ова е автоматски подготвен предлог и може да се доуреди пред објава."
        ).strip()
    return naslov, sodrzina


def _clean_generated_news(naslov: str, sodrzina: str) -> tuple[str, str]:
    clean_title = re.sub(r"\s*-\s*YouTube\s*$", "", str(naslov or ""), flags=re.IGNORECASE).strip()
    clean_title = re.sub(r"\s+", " ", clean_title)
    clean_title = re.sub(r"https?://\S+", "", clean_title).strip(" .,:;-")
    if len(clean_title) < 8:
        clean_title = "Нова информација од медиум"

    clean_body = str(sodrzina or "")
    clean_body = re.sub(r"https?://\S+", "", clean_body)
    clean_body = re.sub(r"\b(?:Наслов на видео|Автор|Канал)\s*:\s*", "", clean_body, flags=re.IGNORECASE)
    clean_body = re.sub(r"\s+", " ", clean_body).strip()
    if len(clean_body) > 900:
        clean_body = clean_body[:900].rsplit(" ", 1)[0].strip() + "..."
    return clean_title, clean_body


def _extract_media_urls_from_html(raw_html: str, source_url: str):
    html_text = str(raw_html or "")

    image_url = ""
    video_url = ""

    og_img = re.search(r'(?is)<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if og_img:
        image_url = og_img.group(1).strip()

    if not image_url:
        first_img = re.search(r'(?is)<img[^>]+src=["\']([^"\']+)["\']', html_text)
        if first_img:
            image_url = first_img.group(1).strip()

    og_video = re.search(r'(?is)<meta[^>]+property=["\']og:video(?::url)?["\'][^>]+content=["\']([^"\']+)["\']', html_text)
    if og_video:
        video_url = og_video.group(1).strip()

    if not video_url:
        first_video = re.search(r'(?is)<video[^>]+src=["\']([^"\']+)["\']', html_text)
        if first_video:
            video_url = first_video.group(1).strip()

    if not video_url:
        iframe = re.search(r'(?is)<iframe[^>]+src=["\']([^"\']+)["\']', html_text)
        if iframe:
            iframe_url = iframe.group(1).strip()
            if "youtube.com" in _mk_lower(iframe_url) or "vimeo.com" in _mk_lower(iframe_url):
                video_url = iframe_url

    if image_url and not image_url.startswith("http://") and not image_url.startswith("https://"):
        image_url = urljoin(source_url, image_url)
    if video_url and not video_url.startswith("http://") and not video_url.startswith("https://"):
        video_url = urljoin(source_url, video_url)

    return image_url, video_url


def _mk_weekday_name_mk(day_date):
    names = ["понеделник", "вторник", "среда", "четврток", "петок", "сабота", "недела"]
    return names[day_date.weekday()]


def _remaining_weekdays():
    today = datetime.now().date()
    out = []
    for i in range(7):
        d = today + timedelta(days=i)
        if d.weekday() < 5:
            out.append(d)
    return out


# API за барања преку AI асистент.
# Ново (македонски): /ai-agent/baranja
# Алијас за постоечки клиенти: /ai-agent/termini
@router.post("/baranja")
@router.post("/termini")
async def ai_agent_termini(request: Request):
    conn = None
    try:
        data = await request.json()
        prompt = (data.get("prompt") or "").strip()
        pacient = data.get("pacient") or {}
        state = data.get("state") or {}

        if not prompt:
            raise HTTPException(status_code=400, detail="Недостига prompt.")

        ai_out = parse_prompt(prompt)
        intent = _normalize_intent((ai_out or {}).get("intent", "")) or _detect_intent(prompt)
        if not intent:
            return {
                "ok": False,
                "message": "Не го разбрав барањето. Напишете „провери слободни термини...“ или „закажи ми...“.",
                "state": state,
            }

        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)

        if intent in (
            "patient_list_appointments",
            "patient_cancel_appointment",
            "patient_reschedule_appointment",
            "patient_set_reminder",
        ):
            patient_resp = handle_patient_action(intent, db_cursor, conn, prompt, pacient, state, ai_out or {})
            if patient_resp is not None:
                return patient_resp

        if intent == "hospital_updates":
            try:
                db_cursor.execute(
                    """
                    SELECT id, naslov, created_at
                    FROM Novosti
                    ORDER BY created_at DESC
                    LIMIT 5
                    """
                )
                latest_news = db_cursor.fetchall() or []
            except Exception:
                latest_news = []

            patient_count = None
            try:
                db_cursor.execute("SELECT COUNT(*) AS vkupno FROM Pacienti")
                row = db_cursor.fetchone() or {}
                patient_count = int(row.get("vkupno") or 0)
            except Exception:
                patient_count = None

            if latest_news:
                lines = ["Најнови информации од болницата:"]
                for n in latest_news:
                    title = (n.get("naslov") or "Без наслов").strip()
                    lines.append(f"- {title}")
            else:
                lines = ["Во моментов нема објавени новости во системот."]

            if patient_count is not None:
                lines.append(f"\nЕвидентирани пациенти во системот: {patient_count}.")

            lines.append("Дали сакате да ви прикажам детали за конкретна вест?")
            return {
                "ok": True,
                "intent": intent,
                "message": "\n".join(lines),
                "state": state,
            }

        if intent == "news_publish_preview":
            admin_doctor_id = _extract_actor_id(pacient, state)
            if not admin_doctor_id or not check_admin_access(admin_doctor_id):
                return {
                    "ok": False,
                    "intent": intent,
                    "message": "За објавување новости мора да сте најавени како директор на болницата.",
                    "state": state,
                }
            source_url = _extract_first_url(prompt)
            if not source_url:
                return {
                    "ok": False,
                    "intent": intent,
                    "message": "Недостига валиден линк. Внесете целосен URL (http/https) за обработка на веста.",
                    "state": state,
                }
            try:
                raw_html = _download_webpage_html(source_url)
            except Exception:
                return {
                    "ok": False,
                    "intent": intent,
                    "message": "Не можев да ја прочитам содржината од линкот. Проверете дали линкот е достапен.",
                    "state": state,
                }
            if _is_youtube_url(source_url):
                source_text = _extract_youtube_text(raw_html, source_url)
            else:
                source_text = _extract_text_from_html(raw_html)
            if len(source_text) < 80:
                source_text = (
                    "Нема доволно текст директно извлечен од линкот. "
                    f"Извор: {source_url}. Подготви краток формален предлог за болничка вест."
                )
            media_image_url, media_video_url = _extract_media_urls_from_html(raw_html, source_url)
            ai_news = parse_news(source_text[:8000], prompt)
            if not ai_news:
                naslov, sodrzina = _fallback_news_draft(source_text, source_url)
            else:
                naslov = (ai_news.get("naslov") or "").strip()
                sodrzina = (ai_news.get("sodrzina") or "").strip()
                if not naslov or not sodrzina:
                    naslov, sodrzina = _fallback_news_draft(source_text, source_url)
            naslov, sodrzina = _clean_generated_news(naslov, sodrzina)
            new_state = dict(state)
            new_state["pending_news"] = {
                "naslov": naslov,
                "sodrzina": sodrzina,
                "source_url": source_url,
                "slika_url": media_image_url,
                "video_url": media_video_url,
            }
            if admin_doctor_id:
                PENDING_NEWS_CACHE[int(admin_doctor_id)] = dict(new_state["pending_news"])
            media_note = []
            if media_image_url:
                media_note.append(f"Слика: {media_image_url}")
            if media_video_url:
                media_note.append(f"Видео: {media_video_url}")
            media_block = f"\n{chr(10).join(media_note)}\n" if media_note else "\n"
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

        if intent == "news_publish_confirm":
            admin_doctor_id = _extract_actor_id(pacient, state)
            pending_news = (state or {}).get("pending_news") or {}
            if not pending_news and admin_doctor_id:
                pending_news = PENDING_NEWS_CACHE.get(int(admin_doctor_id), {}) or {}
            naslov = (pending_news.get("naslov") or "").strip()
            sodrzina = (pending_news.get("sodrzina") or "").strip()
            slika_url = (pending_news.get("slika_url") or "").strip()
            video_url = (pending_news.get("video_url") or "").strip()
            if not naslov or not sodrzina:
                return {
                    "ok": False,
                    "intent": intent,
                    "message": "Нема подготвен предлог за објава. Прво пратете линк за обработка на вест.",
                    "state": state,
                }

            if not admin_doctor_id or not check_admin_access(admin_doctor_id):
                return {
                    "ok": False,
                    "intent": intent,
                    "message": "Немате дозвола за објавување. Само директорот може да објавува новости.",
                    "state": state,
                }

            new_id = insert_novost_from_ai(
                naslov=naslov,
                sodrzina=sodrzina,
                admin_doctor_id=admin_doctor_id,
                slika_url=slika_url,
                video_url=video_url,
            )
            new_state = dict(state)
            new_state.pop("pending_news", None)
            if admin_doctor_id:
                PENDING_NEWS_CACHE.pop(int(admin_doctor_id), None)
            return {
                "ok": True,
                "intent": intent,
                "message": "Успешно објавено. Веста е веќе видлива за сите посетители.",
                "news_id": new_id,
                "state": new_state,
            }

        prompt_l = _mk_lower(prompt)
        parsed_doctor_name = _mk_lower((ai_out or {}).get("doctor_name", ""))
        db_cursor.execute("SELECT doctor_ID, name, surname, specialty, email FROM Doctors")
        doctors = db_cursor.fetchall() or []

        selected_doctor = _find_selected_doctor(doctors, prompt_l, parsed_doctor_name, state)
        specialty = _extract_specialty(prompt, state)

        if not pacient:
            raise HTTPException(status_code=400, detail="Недостигаат податоци за пациент.")

        if intent == "department_doctors":
            if not specialty:
                return {
                    "ok": False,
                    "intent": intent,
                    "message": "Не ја препознав специјалноста. Наведете оддел (на пр. Урологија).",
                    "state": state,
                }

            department_doctors = _doctors_by_specialty(doctors, specialty)
            if not department_doctors:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Во моментов нема евидентирани лекари за одделот {specialty}.",
                    "state": {"specialty": specialty},
                }

            doctor_lines = [f"- Д-р {d.get('name', '')} {d.get('surname', '')}".strip() for d in department_doctors]
            return {
                "ok": True,
                "intent": intent,
                "message": (
                    f"На одделот за {specialty.lower()} работат:\n"
                    + "\n".join(doctor_lines)
                    + "\n\nДали сакате да проверам слободни термини кај некој од нив?"
                ),
                "state": {"specialty": specialty},
            }

        if intent == "specialty_week_availability":
            if not specialty:
                return {
                    "ok": False,
                    "intent": intent,
                    "message": "Не ја препознав областа. Наведете специјалност (на пр. кардиологија).",
                    "state": state,
                }

            specialty_doctors = _doctors_by_specialty(doctors, specialty)
            if not specialty_doctors:
                return {
                    "ok": False,
                    "intent": intent,
                    "message": f"Нема пронајдени лекари за одделот {specialty}.",
                    "state": {"specialty": specialty},
                }

            weekday_dates = _remaining_weekdays()
            availability_rows = []
            for doc in specialty_doctors:
                doctor_id = int(doc["doctor_ID"])
                first_available_day = None
                for day_date in weekday_dates:
                    day_iso = day_date.isoformat()
                    busy = _list_busy_times(db_cursor, doctor_id, day_iso)
                    free_slots = [s for s in _build_workday_slots() if s not in busy]
                    if free_slots:
                        first_available_day = _mk_weekday_name_mk(day_date)
                        break
                if first_available_day:
                    availability_rows.append((doc, first_available_day))

            if not availability_rows:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Во моментов нема слободни термини оваа недела за одделот {specialty}.",
                    "state": {"specialty": specialty},
                }

            lines = [
                f"Во моментов во Клиничка болница Штип, на одделот за {specialty.lower()}, достапни термини оваа недела имаат:"
            ]
            for doc, weekday_name in availability_rows[:6]:
                lines.append(f"- Д-р {doc.get('surname', '')} (достапен во {weekday_name})")
            lines.append("Дали сакате да проверам специфичен термин кај некој од нив?")
            return {
                "ok": True,
                "intent": intent,
                "message": "\n".join(lines),
                "state": {"specialty": specialty},
            }

        if intent == "department_equipment":
            if not specialty:
                return {
                    "ok": False,
                    "intent": intent,
                    "message": "Не е јасно за кој оддел прашувате. Наведете специјалност (на пр. кардиологија).",
                    "state": state,
                }

            db_cursor.execute(
                """
                SELECT DISTINCT a.ime, a.kod
                FROM Aparati a
                INNER JOIN Aparati_termini at ON at.aparat = a.kod
                INNER JOIN Doctors d ON d.doctor_ID = at.doctor_ID
                WHERE a.aktiven = 1
                  AND LOWER(d.specialty) = LOWER(%s)
                ORDER BY a.ime
                """,
                (specialty,),
            )
            filtered = db_cursor.fetchall() or []

            if not filtered:
                return {
                    "ok": True,
                    "intent": intent,
                    "message": f"Нема евидентирани апарати во база за одделот {specialty}.",
                    "state": {"specialty": specialty},
                }

            names = ", ".join(a.get("ime", "") for a in filtered if a.get("ime"))
            return {
                "ok": True,
                "intent": intent,
                "message": f"Одделот за {specialty.lower()} располага со: {names}. Сите апарати се во функција.",
                "state": {"specialty": specialty},
            }

        date_iso = (
            (ai_out or {}).get("date")
            or _izvadi_relativen_ili_iso_datum(prompt)
            or (state.get("date") or "")
        )
        if not selected_doctor:
            return {"ok": False, "message": "Не најдов лекар во промптот. Напишете име и презиме на лекарот.", "state": state}
        if not date_iso:
            return {"ok": False, "message": "Недостига датум во формат YYYY-MM-DD.", "state": state}

        ok_date, date_err = _validate_workday_date(date_iso)
        if not ok_date:
            return {"ok": False, "message": date_err, "state": state}

        busy = _list_busy_times(db_cursor, int(selected_doctor["doctor_ID"]), date_iso)
        all_slots = _build_workday_slots()
        free_slots = [s for s in all_slots if s not in busy]

        new_state = {
            "doctor_id": int(selected_doctor["doctor_ID"]),
            "doctor_name": f"{selected_doctor.get('name', '')} {selected_doctor.get('surname', '')}".strip(),
            "date": date_iso,
            "free_slots": free_slots,
        }

        if intent == "availability":
            if free_slots:
                date_view = _format_mk_date(date_iso)
                shown_slots = ", ".join(free_slots[:8])
                return {
                    "ok": True,
                    "intent": "availability",
                    "message": (
                        f"За {date_view} кај д-р {new_state['doctor_name']} има слободни термини: {shown_slots}. "
                        "Дали сакате да резервираме некое од овие времиња?"
                    ),
                    "state": new_state,
                }
            return {
                "ok": True,
                "intent": "availability",
                "message": f"Нема слободни термини кај Д-р {new_state['doctor_name']} на {date_iso}.",
                "state": new_state,
            }

        time_hhmm = (ai_out or {}).get("time") or _extract_time(prompt)
        note = (ai_out or {}).get("note") or _extract_note(prompt)
        if not time_hhmm:
            return {"ok": False, "message": "Недостига време (на пр. 10:30).", "state": new_state}
        if time_hhmm in busy:
            return {
                "ok": False,
                "message": f"Терминот {date_iso} во {time_hhmm} е веќе зафатен. Побарајте нова проверка на слободни термини.",
                "state": new_state,
            }

        patient_name = (pacient.get("ime") or "").strip()
        patient_surname = (pacient.get("prezime") or "").strip()
        patient_email = (pacient.get("email") or "").strip()
        patient_phone = (pacient.get("telefon") or "").strip()
        if not patient_name or not patient_surname or not patient_email:
            raise HTTPException(status_code=400, detail="Недостигаат задолжителни податоци за најавениот пациент.")

        db_cursor.execute(
            """
            INSERT INTO Termin_pregled
            (doctor_ID, ime_pacient, specijalnost_termin, ime_lekar, datum_pregled, vreme_pregled, status_pregled, email_pacient, telefon_pacient, napomena)
            VALUES (%s, %s, %s, %s, %s, %s, 'закажан', %s, %s, %s)
            """,
            (
                int(selected_doctor["doctor_ID"]),
                f"{patient_name} {patient_surname}".strip(),
                selected_doctor.get("specialty") or "",
                new_state["doctor_name"],
                date_iso,
                time_hhmm,
                patient_email,
                patient_phone,
                note,
            ),
        )
        conn.commit()

        return {
            "ok": True,
            "intent": "book",
            "message": (
                f"Готово, {patient_name}. Вашиот термин кај д-р {new_state['doctor_name']} е успешно закажан за {date_iso} во {time_hhmm}."
                + (f" Напомена: {note}." if note else "")
                + " Ќе добиете потврда и на вашата е-пошта."
            ),
            "state": new_state,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()
