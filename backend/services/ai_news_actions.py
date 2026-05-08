import html
import json
import re
import urllib.parse
import urllib.request
from urllib.parse import urljoin

from routers.admin import check_admin_access
from routers.novosti import insert_novost_from_ai
from services.ai_parser import parse_news

PENDING_NEWS_CACHE = {}


def _mk_lower(s: str) -> str:
    return str(s or "").strip().lower()


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

    if "fmt=" not in base_url:
        sep = "&" if "?" in base_url else "?"
        base_url = f"{base_url}{sep}fmt=json3"

    req = urllib.request.Request(base_url, headers={"User-Agent": "Mozilla/5.0 (compatible; KBStipAI/1.0)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8", errors="ignore")

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

    chunks = re.findall(r'>([^<]+)<', body)
    cleaned = []
    for c in chunks:
        txt = re.sub(r"\s+", " ", html.unescape(c)).strip()
        if not txt or txt.startswith("<?xml") or txt.lower() in ("transcript",):
            continue
        cleaned.append(txt)
    return " ".join(cleaned).strip()


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


def handle_news_intent(intent: str, prompt: str, pacient: dict, state: dict):
    if intent not in ("news_publish_preview", "news_publish_confirm"):
        return None

    admin_doctor_id = _extract_actor_id(pacient, state)

    if intent == "news_publish_preview":
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
