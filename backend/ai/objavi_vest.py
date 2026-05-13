import re
import json
import requests
from typing import Optional
from urllib.parse import urlparse, parse_qs

from database import get_connection
from ai.groq_client import ask_ai


# Системски prompt за генерирање вест од transcript
VEST_PROMPT = """
Ти си професионален новинар во Клиничка Болница Штип. Од transcript на видео, треба да напишеш кратка вест за веб-страницата на болницата.

ПРАВИЛА:
1. Одговори на македонски јазик (кирилица).
2. Врати ЧИСТ JSON во форматот:
   {"naslov": "...", "sodrzina": "..."}
3. naslov: до 100 знаци, информативен, без емоџи.
4. sodrzina: 2-4 параграфи во HTML формат, со <p> тагови.
   Може да користиш <strong>, <em>, <h3> , <i> доколку е потребно е потребно.
5. Тонот да биде професионален и официјален, како здравствена институција.
6. Ако видеото не е поврзано со здравство/медицина, сепак направи најдобар можен наслов и содржина.
7. НЕ копирај го директно transcript-от - синтетизирај го и парафразирај.
8. НЕ додавај markdown кодни блокови (```), наводници или објаснувања пред/после JSON-от.

Пример формат:
{"naslov": "Нова кампања за здрави срца", "sodrzina": "<p>Клиничка Болница Штип започна нова кампања...</p><p>Цел на кампањата е...</p>"}
""".strip()


def izvlechi_video_id(url: str) -> Optional[str]:
    """
    Извлекува YouTube video ID од разни формати на URL:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    """
    if not url:
        return None
    url = url.strip()

    # youtu.be/VIDEO_ID
    match = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", url)
    if match:
        return match.group(1)

    # youtube.com/watch?v=VIDEO_ID
    parsed = urlparse(url)
    if "youtube.com" in parsed.netloc:
        if parsed.path == "/watch":
            q = parse_qs(parsed.query)
            if "v" in q and q["v"]:
                return q["v"][0]

        # embed/VIDEO_ID или shorts/VIDEO_ID
        match = re.search(r"/(?:embed|shorts)/([a-zA-Z0-9_-]{11})", parsed.path)
        if match:
            return match.group(1)

    # Голи 11-знакови ID
    match = re.fullmatch(r"[a-zA-Z0-9_-]{11}", url)
    if match:
        return url

    return None


def najdi_youtube_link(tekst: str) -> Optional[str]:
    """Бара YouTube линк во даден текст (пишано прашање од директор)."""
    if not tekst:
        return None

    pattern = r"(https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s]+|embed/[a-zA-Z0-9_-]{11}|shorts/[a-zA-Z0-9_-]{11})|youtu\.be/[a-zA-Z0-9_-]{11}[^\s]*))"
    match = re.search(pattern, tekst)
    if match:
        return match.group(1)
    return None


def zimi_transcript(video_id: str) -> Optional[str]:
    """
    Земе transcript од YouTube видео.
    Прво проба македонски, потоа англиски, потоа кој било достапен.
    Враќа спoен текст или None ако нема transcript.
    """
    try:
        # Подоцнежниот API на youtube-transcript-api (v1+)
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()

        # Проба со список приоритетни јазици
        prefered_langs = ["mk", "en", "en-US", "en-GB", "sr", "bg", "hr", "bs"]

        try:
            transcript = api.fetch(video_id, languages=prefered_langs)
        except Exception:
            # Ако не успее, проба со кој било достапен јазик
            try:
                transcript_list = api.list(video_id)
                # Земи прв достапен
                first = next(iter(transcript_list))
                transcript = first.fetch()
            except Exception as e:
                print(f"[objavi_vest] Nema dostapen transcript: {e}")
                return None

        # Зависно од верзијата на API-то, snippets може да се FetchedTranscript обект
        snippets = list(transcript)
        if not snippets:
            return None

        # Секој snippet има .text атрибут (или ['text'] во постари верзии)
        parts = []
        for s in snippets:
            text = getattr(s, "text", None) or (s.get("text") if isinstance(s, dict) else None)
            if text:
                parts.append(text.strip())

        full = " ".join(parts)
        # Лимитирај должина (Groq контекст лимит)
        if len(full) > 8000:
            full = full[:8000] + "..."
        return full or None

    except Exception as e:
        print(f"[objavi_vest] greshka pri transcript: {e}")
        return None


def zimi_youtube_naslov(video_id: str) -> Optional[str]:
    """
    Земе оригинален наслов на YouTube видео преку oEmbed API.
    Бесплатно, без клуч.
    """
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        response = requests.get(
            f"https://www.youtube.com/oembed?url={url}&format=json",
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("title")
    except Exception as e:
        print(f"[objavi_vest] greshka pri oembed: {e}")
    return None


def zimi_thumbnail_url(video_id: str) -> str:
    """Враќа URL до thumbnail на видеото (висока резолуција)."""
    # maxresdefault не постои за сите видеа, hqdefault е сигурен fallback
    return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"


def zimi_embed_url(video_id: str) -> str:
    """
    Враќа embed URL за видеото - за вградување во новоста.
    Користиме `youtube-nocookie.com` наместо `youtube.com` за да го избегнеме
    Error 153 (Video player configuration error) и за приватност на корисниците.
    """
    return f"https://www.youtube-nocookie.com/embed/{video_id}"


def generiraj_naslov_i_sodrzina(transcript: str, original_naslov: Optional[str]) -> dict:
    """
    Праќа transcript кон Groq, добива {"naslov": "...", "sodrzina": "..."}.
    Враќа dict или {"_error": "..."} при проблем.
    """
    kontekst = ""
    if original_naslov:
        kontekst = f"Оригинален наслов на видеото: „{original_naslov}\"\n\n"
    kontekst += f"Transcript на видеото:\n{transcript}"

    odgovor = ask_ai(kontekst, system_prompt=VEST_PROMPT)

    # Detektiraj rate limit / greshki
    error_indicators = [
        "Привремено сум преоптоварен",
        "Привремена грешка",
        "не одговори навреме",
        "Не е поставен",
        "Непозната грешка",
        "неочекуван формат",
        "Невалиден API",
    ]
    if any(ind in odgovor for ind in error_indicators):
        return {"_error": odgovor}

    # Исчисти markdown ако има ```json ... ```
    cist = odgovor.strip()
    cist = re.sub(r"^```(?:json)?\s*", "", cist)
    cist = re.sub(r"\s*```$", "", cist)

    try:
        podatoci = json.loads(cist)
        naslov = (podatoci.get("naslov") or "").strip()
        sodrzina = (podatoci.get("sodrzina") or "").strip()
        if not naslov or not sodrzina:
            return {"_error": "AI не врати валиден наслов или содржина."}
        return {"naslov": naslov, "sodrzina": sodrzina}
    except json.JSONDecodeError as e:
        print(f"[objavi_vest] JSON greshka: {e}, raw: {cist!r}")
        return {"_error": "AI врати неочекуван формат."}


def vmetni_vest_vo_baza(
    naslov: str,
    sodrzina: str,
    slika_url: str,
    video_url: str,
    author_doctor_id: int,
) -> Optional[int]:
    """
    INSERT во Novosti табелата. Враќа id на нова вест или None при грешка.
    Со slika_url ставаме full URL (https://img.youtube.com/vi/.../hqdefault.jpg)
    што frontend-от веќе го поддржува.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO Novosti (naslov, sodrzina, slika_path, video_url, author_doctor_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (naslov, sodrzina, slika_url, video_url, author_doctor_id),
        )
        conn.commit()
        new_id = cur.lastrowid
        cur.close()
        return new_id
    except Exception as e:
        print(f"[objavi_vest] DB greshka: {e}")
        return None
    finally:
        if conn:
            conn.close()


def odgovori_za_objava_vest(prashanje: str, lekar: Optional[dict]) -> str:
    """
    Главна точка - повикана од router-от.

    Параметри:
        prashanje - целата порака од директорот (треба да содржи YouTube линк)
        lekar     - dict со податоци за логиран лекар (треба да биде директор)

    Враќа: текстуален одговор за приказ во чатот.
    """
    # 1. Проверка дали корисникот е лекар
    if not lekar or not lekar.get("doctor_ID"):
        return (
            "За да објавиш вест преку AI асистентот, мораш прво да се најавиш "
            "како лекар (директор) горе десно."
        )

    # 2. Проверка дали корисникот е директор (Владко Захариев)
    # Користиме истата функција од routers/admin.py
    try:
        from routers.admin import check_admin_access
        if not check_admin_access(lekar.get("doctor_ID")):
            return (
                "Само директорот на болницата може да објавува вести преку AI асистентот."
            )
    except Exception as e:
        print(f"[objavi_vest] greshka pri admin proverka: {e}")
        return "Не можам да ги проверам твоите права во моментов. Обиди се повторно."

    # 3. Извлечи YouTube линк од пораката
    yt_link = najdi_youtube_link(prashanje)
    if not yt_link:
        return (
            'За да објавам вест, испрати ми YouTube линк во пораката.\n\n'
            'Пример: „Објави вест: https://www.youtube.com/watch?v=XXXXXXXXXXX"'
        )

    video_id = izvlechi_video_id(yt_link)
    if not video_id:
        return (
            "Линкот не изгледа како валиден YouTube линк. "
            "Те молам провери го и пробај пак."
        )

    # 4. Земе transcript
    transcript = zimi_transcript(video_id)
    if not transcript:
        # Fallback: користи го само насловот ако нема transcript
        original = zimi_youtube_naslov(video_id)
        if not original:
            return (
                "Видеото нема достапни титлови (transcript), а ниту насловот не можев "
                "да го прочитам. Пробај со друго видео што има титлови."
            )
        # Гради „transcript" само од насловот - AI ке генерира пократка вест
        transcript = f"Наслов: {original}. (Без достапни титлови за подетално опишување.)"
        original_naslov = original
    else:
        original_naslov = zimi_youtube_naslov(video_id)

    # 5. Generiraj naslov + sodrzina
    rez = generiraj_naslov_i_sodrzina(transcript, original_naslov)
    if rez.get("_error"):
        return f"Грешка при генерирање вест: {rez['_error']}"

    naslov = rez["naslov"]
    sodrzina = rez["sodrzina"]

    # 6. Add YouTube embed на крајот од содржината (за прикажување на видеото)
    embed_url = zimi_embed_url(video_id)
    # video_url полето во Novosti се користи за embed
    thumbnail_url = zimi_thumbnail_url(video_id)

    # 7. INSERT во базата
    new_id = vmetni_vest_vo_baza(
        naslov=naslov,
        sodrzina=sodrzina,
        slika_url=thumbnail_url,
        video_url=embed_url,
        author_doctor_id=lekar.get("doctor_ID"),
    )

    if not new_id:
        return (
            "Веста беше успешно генерирана, но не успеав да ја зачувам во базата. "
            "Пробај пак за неколку секунди."
        )

    return (
        'Веста е успешно објавена!\n\n'
        f'Наслов: {naslov}\n\n'
        'Може да ја видиш на страната „Новости" на сајтот.\n'
        f'ID: {new_id}'
    )
