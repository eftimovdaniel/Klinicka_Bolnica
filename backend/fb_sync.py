"""
Синхронизација на постови од Facebook Page (Meta Graph API).

Нови постови → Fb_post_pending (status=pending).
Директорот одобрува преку AI или /admin/facebook/* пред објава во Novosti.
"""

from __future__ import annotations

import html
import os
import re
from datetime import datetime, timedelta
from typing import Any

import requests
from database import get_connection

FB_PAGE_ID_RAW = os.getenv("FB_PAGE_ID", "").strip()
FB_PAGE_URL = os.getenv("FB_PAGE_URL", "").strip()
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
FB_API_VERSION = os.getenv("FB_API_VERSION", "v21.0").strip()
FB_SYNC_MOCK = os.getenv("FB_SYNC_MOCK", "").strip().lower() in ("1", "true", "yes", "on")
# Колку постови да се побараат од FB (не сите историски)
FB_SYNC_LIMIT = int(os.getenv("FB_SYNC_LIMIT", "5") or "5")
# Само постови понови од X дена (прв sync / стари постови се игнорираат)
FB_SYNC_SINCE_DAYS = int(os.getenv("FB_SYNC_SINCE_DAYS", "7") or "7")
# Макс. НОВИ pending по едно кликнување „Синхронизирај" (остатокот следен пат)
FB_SYNC_MAX_NEW_PER_RUN = int(os.getenv("FB_SYNC_MAX_NEW_PER_RUN", "1") or "1")


class FbSyncError(Exception):
    pass


def resolve_page_id() -> str:
    """
    ID на Facebook Page за Graph API.
    Може директно FB_PAGE_ID или линк FB_PAGE_URL, на пр.:
    https://www.facebook.com/profile.php?id=61573825102800
    """
    if FB_PAGE_ID_RAW:
        return FB_PAGE_ID_RAW
    url = FB_PAGE_URL
    if not url:
        return ""
    m = re.search(r"profile\.php\?id=(\d+)", url, re.I)
    if m:
        return m.group(1)
    m = re.search(r"facebook\.com/(\d{10,})", url, re.I)
    if m:
        return m.group(1)
    return ""


def get_sync_mode() -> str:
    """mock | live | disabled"""
    if FB_SYNC_MOCK:
        return "mock"
    if resolve_page_id() and FB_PAGE_ACCESS_TOKEN:
        return "live"
    return "disabled"


def get_sync_info() -> dict[str, Any]:
    page_id = resolve_page_id()
    return {
        "mode": get_sync_mode(),
        "page_id": page_id or None,
        "page_url": FB_PAGE_URL or (
            f"https://www.facebook.com/profile.php?id={page_id}" if page_id else None
        ),
        "mock": FB_SYNC_MOCK,
        "has_token": bool(FB_PAGE_ACCESS_TOKEN),
    }


def is_configured() -> bool:
    return get_sync_mode() != "disabled"


def _message_to_html(message: str) -> str:
    msg = (message or "").strip()
    if not msg:
        return "<p></p>"
    blocks = [b.strip() for b in msg.split("\n\n") if b.strip()]
    if not blocks:
        blocks = [msg]
    out: list[str] = []
    for block in blocks:
        inner = html.escape(block).replace("\n", "<br>")
        out.append(f"<p>{inner}</p>")
    return "".join(out)


def naslov_od_message(message: str) -> str:
    msg = (message or "").strip()
    if not msg:
        return "Објава од Facebook"
    first = msg.split("\n")[0].strip()
    if len(first) > 200:
        first = first[:197] + "..."
    return first or "Објава од Facebook"


def sodrzina_od_message(message: str, naslov: str) -> str:
    msg = (message or "").strip()
    if not msg:
        return "<p></p>"
    lines = msg.split("\n")
    body = msg
    if len(lines) > 1 and lines[0].strip() == naslov.strip():
        body = "\n".join(lines[1:]).strip() or msg
    return _message_to_html(body)


def _parse_fb_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        s = value.replace("Z", "+00:00")
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except Exception:
        return None


def _mock_posts() -> list[dict[str, Any]]:
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+0000")
    return [
        {
            "id": "mock_fb_demo_001",
            "message": (
                "Нова опрема во Клиничка Болница Штип\n\n"
                "Инвестиравме во модерна дијагностика за подобра нега на пациентите."
            ),
            "created_time": now,
            "full_picture": None,
            "permalink_url": "https://www.facebook.com/",
        },
        {
            "id": "mock_fb_demo_002",
            "message": "Отворен ден на врати — добредојде на јавниот ден за посетители.",
            "created_time": now,
            "full_picture": None,
            "permalink_url": "https://www.facebook.com/",
        },
    ]


def _since_cutoff() -> datetime:
    days = max(1, FB_SYNC_SINCE_DAYS)
    return datetime.utcnow() - timedelta(days=days)


def _post_created(post: dict[str, Any]) -> datetime | None:
    return _parse_fb_datetime(post.get("created_time"))


def _filter_recent_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Само постови со текст, од последниве N дена."""
    cutoff = _since_cutoff()
    out: list[dict[str, Any]] = []
    for post in posts:
        if not (post.get("message") or "").strip():
            continue
        created = _post_created(post)
        if created is not None and created < cutoff:
            continue
        out.append(post)
    out.sort(key=lambda p: _post_created(p) or datetime.min, reverse=True)
    return out


def fetch_posts_from_facebook(limit: int | None = None) -> list[dict[str, Any]]:
    lim = limit or FB_SYNC_LIMIT
    if FB_SYNC_MOCK:
        return _mock_posts()[:lim]
    page_id = resolve_page_id()
    if not page_id or not FB_PAGE_ACCESS_TOKEN:
        raise FbSyncError(
            "Facebook не е конфигуриран за вистинска страница. "
            "Во backend/.env: FB_SYNC_MOCK=0, FB_PAGE_ID=61573825102800 "
            "(или FB_PAGE_URL со линкот до страницата) и FB_PAGE_ACCESS_TOKEN. "
            "За тест без FB: FB_SYNC_MOCK=1."
        )
    url = f"https://graph.facebook.com/{FB_API_VERSION}/{page_id}/posts"
    params = {
        "access_token": FB_PAGE_ACCESS_TOKEN,
        "fields": "id,message,created_time,full_picture,permalink_url",
        "limit": lim,
    }
    try:
        r = requests.get(url, params=params, timeout=25)
    except requests.RequestException as e:
        raise FbSyncError(f"Неуспешен повик кон Facebook: {e}") from e
    if not r.ok:
        try:
            err = r.json().get("error", {})
            msg = err.get("message") or r.text
        except Exception:
            msg = r.text
        raise FbSyncError(f"Facebook API грешка: {msg}")
    data = r.json()
    posts = [p for p in (data.get("data") or []) if isinstance(p, dict)]
    return _filter_recent_posts(posts)


def _table_exists(cur) -> bool:
    try:
        cur.execute("SELECT 1 FROM Fb_post_pending LIMIT 1")
        cur.fetchone()
        return True
    except Exception as e:
        if "doesn't exist" in str(e).lower() or "1146" in str(e):
            return False
        raise


def sync_facebook_posts(limit: int | None = None) -> dict[str, Any]:
    """
    Повлечи постови од FB и зачувај нови како pending.
    Враќа: {ok, added, already_known, pending_count, message?}
    """
    posts = _filter_recent_posts(fetch_posts_from_facebook(limit))
    max_new = max(1, FB_SYNC_MAX_NEW_PER_RUN)
    conn = None
    added = 0
    already = 0
    skipped_old = 0
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        if not _table_exists(cur):
            raise FbSyncError(
                "Табелата Fb_post_pending не постои. Пуштете ја миграцијата: "
                "backend/migrations/add_fb_post_pending.sql"
            )
        for post in posts:
            if added >= max_new:
                skipped_old += 1
                continue
            fb_id = str(post.get("id") or "").strip()
            if not fb_id:
                continue
            cur.execute(
                "SELECT id FROM Fb_post_pending WHERE fb_post_id = %s LIMIT 1",
                (fb_id,),
            )
            if cur.fetchone():
                already += 1
                continue
            message = (post.get("message") or "").strip()
            naslov = naslov_od_message(message)
            sodrzina = sodrzina_od_message(message, naslov)
            slika = (post.get("full_picture") or "").strip() or None
            permalink = (post.get("permalink_url") or "").strip() or None
            fb_created = _parse_fb_datetime(post.get("created_time"))
            cur.execute(
                """
                INSERT INTO Fb_post_pending
                  (fb_post_id, naslov, sodrzina, slika_url, fb_permalink, fb_created_at, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                """,
                (fb_id, naslov, sodrzina, slika, permalink, fb_created),
            )
            added += 1
        conn.commit()
        cur.execute(
            "SELECT COUNT(*) AS c FROM Fb_post_pending WHERE status = 'pending'"
        )
        row = cur.fetchone() or {}
        pending_count = int(row.get("c") or 0)
        cur.close()
        info = get_sync_info()
        return {
            "ok": True,
            "added": added,
            "already_known": already,
            "fetched": len(posts),
            "pending_count": pending_count,
            "max_new_per_run": max_new,
            "deferred": skipped_old,
            "sync_mode": info.get("mode"),
            "page_id": info.get("page_id"),
            "page_url": info.get("page_url"),
            "note": (
                "Ништо не е објавено на сајтот автоматски. "
                "Само одобрените (да/Објави) одат во Новости."
            ),
        }
    finally:
        if conn and conn.is_connected():
            conn.close()


def run_sync_if_configured() -> dict[str, Any] | None:
    """Периодичен sync — тивок ако FB не е поставен."""
    if not is_configured():
        return None
    try:
        return sync_facebook_posts()
    except Exception as e:
        print(f"[fb_sync] periodic: {e}")
        return None


def list_pending(limit: int = 20) -> list[dict[str, Any]]:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        if not _table_exists(cur):
            return []
        cur.execute(
            """
            SELECT id, fb_post_id, naslov, sodrzina, slika_url, fb_permalink,
                   fb_created_at, synced_at
            FROM Fb_post_pending
            WHERE status = 'pending'
            ORDER BY COALESCE(fb_created_at, synced_at) DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall() or []
        cur.close()
        return [dict(r) for r in rows]
    finally:
        if conn and conn.is_connected():
            conn.close()


def get_pending_by_id(pending_id: int) -> dict[str, Any] | None:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT id, fb_post_id, naslov, sodrzina, slika_url, fb_permalink,
                   fb_created_at, status
            FROM Fb_post_pending
            WHERE id = %s AND status = 'pending'
            """,
            (pending_id,),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    finally:
        if conn and conn.is_connected():
            conn.close()


def get_first_pending() -> dict[str, Any] | None:
    rows = list_pending(limit=1)
    return rows[0] if rows else None


def skip_pending(pending_id: int) -> bool:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE Fb_post_pending
            SET status = 'skipped', resolved_at = NOW()
            WHERE id = %s AND status = 'pending'
            """,
            (pending_id,),
        )
        conn.commit()
        ok = cur.rowcount > 0
        cur.close()
        return ok
    finally:
        if conn and conn.is_connected():
            conn.close()


def publish_pending(pending_id: int, admin_doctor_id: int) -> int:
    """Објави pending пост во Novosti. Враќа novost_id."""
    row = get_pending_by_id(pending_id)
    if not row:
        raise FbSyncError("Постот не е пронајден или веќе е обработен.")
    from routers.novosti import insert_novost_from_ai

    novost_id = insert_novost_from_ai(
        naslov=row["naslov"],
        sodrzina=row["sodrzina"],
        admin_doctor_id=admin_doctor_id,
        slika_url=row.get("slika_url"),
    )
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE Fb_post_pending
            SET status = 'published', novost_id = %s, resolved_at = NOW()
            WHERE id = %s
            """,
            (novost_id, pending_id),
        )
        conn.commit()
        cur.close()
    finally:
        if conn and conn.is_connected():
            conn.close()
    return novost_id
