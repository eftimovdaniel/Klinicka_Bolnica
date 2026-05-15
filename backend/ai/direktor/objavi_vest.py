"""
Објавување вест од YouTube линк - само за директорот.

Tek: Корисник пишува „Објави вест: https://youtube.com/watch?v=XYZ"
→ Земи transcript од YouTube → AI генерира наслов + текст → INSERT во Novosti.
"""

import re
import json
import requests
from urllib.parse import urlparse, parse_qs

from database import get_connection
from ai._kernel.auth import require_direktor
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai


PROMPT = """
Ти си новинар во Клиничка Болница Штип. Од transcript на видео, напиши вест.

Врати САМО JSON: {"naslov": "...", "sodrzina": "<p>...</p><p>...</p>"}

Правила:
- naslov: до 100 знаци, на македонски, без емоџи.
- sodrzina: 2-4 параграфи во HTML со <p> тагови. Може <strong>, <em>.
- НЕ копирај го transcript-от - парафразирај.
- БЕЗ markdown (```), БЕЗ објаснувања пред/после JSON.
""".strip()


def _video_id(text: str) -> str | None:
    """Извлечи YouTube video ID од URL или текст со URL."""
    m = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", text)
    if m:
        return m.group(1)
    m = re.search(r"youtube\.com/(?:watch\?v=|embed/|shorts/)([a-zA-Z0-9_-]{11})", text)
    if m:
        return m.group(1)
    return None


def _zimi_transcript(video_id: str) -> str | None:
    """Земи transcript од YouTube видеото (пробува mk → en → било кој)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        try:
            tr = api.fetch(video_id, languages=["mk", "en", "en-US", "sr", "bg"])
        except Exception:
            tr = next(iter(api.list(video_id))).fetch()
        tekst = " ".join(s.text.strip() for s in tr if s.text)
        return tekst[:8000] if tekst else None
    except Exception as e:
        print(f"[objavi_vest] transcript greshka: {e}")
        return None


def _zimi_naslov(video_id: str) -> str | None:
    """Оригинален наслов на видеото преку YouTube oEmbed API (бесплатно)."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        r = requests.get(f"https://www.youtube.com/oembed?url={url}&format=json", timeout=10)
        return r.json().get("title") if r.ok else None
    except Exception:
        return None


def _generiraj_vest(transcript: str, naslov_yt: str | None) -> dict:
    """AI генерира naslov + sodrzina од transcript."""
    kontekst = (f"Оригинален наслов: „{naslov_yt}\"\n\n" if naslov_yt else "") + f"Transcript:\n{transcript}"
    odgovor = ask_ai(kontekst, system_prompt=PROMPT)

    data = parse_ai_json(odgovor, log_tag="objavi_vest")
    if data.get("_error"):
        return data
    if data.get("naslov") and data.get("sodrzina"):
        return data
    return {"_error": "AI врати неочекуван формат."}


def odgovori_za_objava_vest(prashanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_direktor(lekar):
        return err

    vid = _video_id(prashanje)
    if not vid:
        return (
            'Испрати ми YouTube линк.\n\n'
            'Пример: „Објави вест: https://www.youtube.com/watch?v=XXXXXXXXXXX"'
        )

    transcript = _zimi_transcript(vid)
    naslov_yt = _zimi_naslov(vid)

    if not transcript:
        if not naslov_yt:
            return "Видеото нема титлови ниту наслов. Пробај друго видео."
        transcript = f"Наслов: {naslov_yt}. (Без титлови.)"

    vest = _generiraj_vest(transcript, naslov_yt)
    if vest.get("_error"):
        return f"Грешка: {vest['_error']}"

    # INSERT во Novosti
    thumbnail = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
    embed = f"https://www.youtube-nocookie.com/embed/{vid}"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO Novosti (naslov, sodrzina, slika_path, video_url, author_doctor_id)"
        " VALUES (%s, %s, %s, %s, %s)",
        (vest["naslov"], vest["sodrzina"], thumbnail, embed, lekar["doctor_ID"]),
    )
    conn.commit()
    new_id = cur.lastrowid
    cur.close()
    conn.close()

    return (
        f"Веста е објавена!\n\n"
        f"Наслов: {vest['naslov']}\n"
        f"ID: {new_id}\n\n"
        f"Може да ја видиш на страната „Новости\"."
    )
