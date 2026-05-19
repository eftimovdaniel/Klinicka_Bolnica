"""
Објавување вест од YouTube линк - само за директорот.

Tek: Корисник пишува „Објави вест: https://youtube.com/watch?v=XYZ"
→ Земи transcript од YouTube → AI генерира наслов + текст → INSERT во Novosti.
"""

import html
import re

import requests

from database import get_connection
from ai._kernel.auth import require_direktor
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import GROQ_OFFLINE_MSG, ask_ai, groq_e_isklucen


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
        print(f"[objavi_vest] transcript greska: {e}")
        return None


def _zimi_naslov(video_id: str) -> str | None:
    """Оригинален наслов на видеото преку YouTube oEmbed API (бесплатно)."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        r = requests.get(f"https://www.youtube.com/oembed?url={url}&format=json", timeout=10)
        return r.json().get("title") if r.ok else None
    except Exception:
        return None


def _paragrafi_od_transcript(transcript: str, *, max_para: int = 4) -> list[str]:
    """Подели transcript во 2–4 параграфи (без AI)."""
    text = re.sub(r"\s+", " ", (transcript or "").strip())
    if not text:
        return ["Видете го прикаченото видео за повеќе информации."]

    delovi = re.split(r"(?<=[.!?])\s+", text)
    paras: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for rec in delovi:
        rec = rec.strip()
        if not rec:
            continue
        if buf_len + len(rec) > 480 and buf:
            paras.append(" ".join(buf))
            buf = []
            buf_len = 0
            if len(paras) >= max_para:
                break
        buf.append(rec)
        buf_len += len(rec)
    if buf and len(paras) < max_para:
        paras.append(" ".join(buf))

    if not paras:
        paras = [text[:800]]
    return paras[:max_para]


def _generiraj_vest_lokalno(transcript: str, naslov_yt: str | None) -> dict:
    """
    Вест од transcript + YouTube наслов — без Groq.
    Користи се кога AI е offline или врати грешка.
    """
    naslov = (naslov_yt or "Вест од видео").strip()
    if len(naslov) > 100:
        naslov = naslov[:97].rstrip() + "…"

    paras = _paragrafi_od_transcript(transcript)
    html_delovi: list[str] = []
    if naslov_yt:
        html_delovi.append(
            "<p>"
            f"Клиничката болница објавува видео: "
            f"<strong>{html.escape(naslov_yt)}</strong>."
            "</p>"
        )
    for p in paras:
        html_delovi.append(f"<p>{html.escape(p)}</p>")

    return {
        "naslov": naslov,
        "sodrzina": "".join(html_delovi),
        "_lokalno": True,
    }


def _generiraj_vest(transcript: str, naslov_yt: str | None) -> dict:
    """AI генерира naslov + sodrzina (без локален шаблон fallback)."""
    if groq_e_isklucen():
        return {"_error": GROQ_OFFLINE_MSG}

    kontekst = (
        (f"Оригинален наслов: „{naslov_yt}\"\n\n" if naslov_yt else "")
        + f"Transcript:\n{transcript}"
    )
    odgovor = ask_ai(kontekst, system_prompt=PROMPT)

    if (odgovor or "").strip() == GROQ_OFFLINE_MSG or "преоптоварен" in (odgovor or ""):
        return {"_error": GROQ_OFFLINE_MSG}

    data = parse_ai_json(odgovor, log_tag="objavi_vest")
    if data.get("_error"):
        return data
    if data.get("naslov") and data.get("sodrzina"):
        return data

    return {"_error": "AI врати неочекуван формат за вест."}


def odgovori_za_objava_vest(prasanje: str, lekar: dict | None) -> str | dict:
    """Главна точка - повикана од router-от."""
    if err := require_direktor(lekar):
        return err

    vid = _video_id(prasanje)
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

    lokalno = bool(vest.pop("_lokalno", False))

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

    if lokalno:
        print(
            "[objavi_vest] објавена локално од титлови (AI недостапен), id=",
            new_id,
        )

    link = f"[[Новости|novosti.html?id={new_id}]]"
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
