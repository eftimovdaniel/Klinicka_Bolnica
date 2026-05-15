"""
Зачувување на AI чат сесии и пораки (само најавени пациент / лекар).
"""

from __future__ import annotations

import json
from typing import Any

from database import get_connection
from ai._kernel.db_helpers import as_dict

_MAX_NASLOV = 120
_MAX_SESSIONS = 50


def _json_dump(obj: Any) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False)


def _json_load(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _naslov_od_prasanje(text: str) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= _MAX_NASLOV:
        return t
    return t[: _MAX_NASLOV - 1].rstrip() + "…"


def _session_owned(cur, session_id: int, pacient_id: int | None, doctor_id: int | None) -> bool:
    cur.execute(
        """
        SELECT session_id FROM Ai_chat_session
        WHERE session_id = %s
          AND (
            (%s IS NOT NULL AND pacient_id = %s)
            OR (%s IS NOT NULL AND doctor_id = %s)
          )
        LIMIT 1
        """,
        (session_id, pacient_id, pacient_id, doctor_id, doctor_id),
    )
    return bool(cur.fetchone())


def list_sessions(
    *,
    pacient_id: int | None = None,
    doctor_id: int | None = None,
    limit: int = _MAX_SESSIONS,
) -> list[dict[str, Any]]:
    if not pacient_id and not doctor_id:
        return []
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        if pacient_id:
            cur.execute(
                """
                SELECT session_id, naslov, created_at, updated_at
                FROM Ai_chat_session
                WHERE pacient_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (pacient_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT session_id, naslov, created_at, updated_at
                FROM Ai_chat_session
                WHERE doctor_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (doctor_id, limit),
            )
        rows = [as_dict(r) for r in (cur.fetchall() or [])]
        cur.close()
        return rows
    except Exception as e:
        print(f"[ai_chat_store] list_sessions: {e}")
        return []
    finally:
        if conn and conn.is_connected():
            conn.close()


def get_session_messages(
    session_id: int,
    *,
    pacient_id: int | None = None,
    doctor_id: int | None = None,
) -> dict[str, Any] | None:
    if not pacient_id and not doctor_id:
        return None
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        if not _session_owned(cur, session_id, pacient_id, doctor_id):
            return None
        cur.execute(
            """
            SELECT kontekst_json FROM Ai_chat_session WHERE session_id = %s
            """,
            (session_id,),
        )
        sess = as_dict(cur.fetchone() or {})
        cur.execute(
            """
            SELECT uloga, sodrzina, navigacija_json, akcija, created_at
            FROM Ai_chat_message
            WHERE session_id = %s
            ORDER BY created_at ASC, message_id ASC
            """,
            (session_id,),
        )
        msgs = []
        for r in cur.fetchall() or []:
            row = as_dict(r)
            msgs.append(
                {
                    "uloga": row.get("uloga"),
                    "sodrzina": row.get("sodrzina") or "",
                    "navigacija": _json_load(row.get("navigacija_json")),
                    "akcija": row.get("akcija"),
                    "created_at": row.get("created_at"),
                }
            )
        cur.close()
        return {
            "session_id": session_id,
            "kontekst": _json_load(sess.get("kontekst_json")),
            "messages": msgs,
        }
    except Exception as e:
        print(f"[ai_chat_store] get_session_messages: {e}")
        return None
    finally:
        if conn and conn.is_connected():
            conn.close()


def create_session(
    *,
    pacient_id: int | None = None,
    doctor_id: int | None = None,
    naslov: str | None = None,
) -> int | None:
    if not pacient_id and not doctor_id:
        return None
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO Ai_chat_session (pacient_id, doctor_id, naslov)
            VALUES (%s, %s, %s)
            """,
            (pacient_id, doctor_id, naslov),
        )
        conn.commit()
        sid = int(cur.lastrowid)
        cur.close()
        return sid
    except Exception as e:
        print(f"[ai_chat_store] create_session: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return None
    finally:
        if conn and conn.is_connected():
            conn.close()


def delete_session(
    session_id: int,
    *,
    pacient_id: int | None = None,
    doctor_id: int | None = None,
) -> bool:
    """Брише сесија и сите пораки (CASCADE). Само сопственик."""
    if not pacient_id and not doctor_id:
        return False
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        if not _session_owned(cur, session_id, pacient_id, doctor_id):
            return False
        cur.execute(
            "DELETE FROM Ai_chat_session WHERE session_id = %s",
            (session_id,),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[ai_chat_store] delete_session: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()


def save_exchange(
    session_id: int,
    *,
    pacient_id: int | None,
    doctor_id: int | None,
    user_text: str,
    assistant_text: str,
    kontekst: dict | None,
    navigacija: dict | None = None,
    akcija: str | None = None,
    set_naslov: bool = False,
) -> bool:
    if not pacient_id and not doctor_id:
        return False
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        if not _session_owned(cur, session_id, pacient_id, doctor_id):
            return False

        cur.execute(
            """
            INSERT INTO Ai_chat_message (session_id, uloga, sodrzina)
            VALUES (%s, 'user', %s)
            """,
            (session_id, user_text),
        )
        cur.execute(
            """
            INSERT INTO Ai_chat_message (session_id, uloga, sodrzina, navigacija_json, akcija)
            VALUES (%s, 'assistant', %s, %s, %s)
            """,
            (session_id, assistant_text, _json_dump(navigacija), akcija),
        )

        updates = ["kontekst_json = %s", "updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = [_json_dump(kontekst)]
        if set_naslov:
            updates.append("naslov = %s")
            params.append(_naslov_od_prasanje(user_text))
        params.append(session_id)
        cur.execute(
            f"UPDATE Ai_chat_session SET {', '.join(updates)} WHERE session_id = %s",
            tuple(params),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[ai_chat_store] save_exchange: {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()
