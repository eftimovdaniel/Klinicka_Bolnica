import json
import os
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from database import get_connection
from routers.admin import check_admin_access

router = APIRouter(tags=["novosti"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads" / "novosti"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _ensure_upload_dir():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _save_upload(file: UploadFile) -> Optional[str]:
    if not file or not file.filename:
        return None
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None
    _ensure_upload_dir()
    name = f"{uuid.uuid4().hex}{ext}"
    path = UPLOAD_DIR / name
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return f"uploads/novosti/{name}"


def _normalize_novost_row(r: dict) -> None:
    if r.get("created_at"):
        r["created_at"] = r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"])
    if r.get("updated_at"):
        r["updated_at"] = r["updated_at"].isoformat() if hasattr(r["updated_at"], "isoformat") else str(r["updated_at"])
    if isinstance(r.get("slike_extra"), str) and r["slike_extra"]:
        try:
            r["slike_extra"] = json.loads(r["slike_extra"])
        except Exception:
            r["slike_extra"] = []
    elif r.get("slike_extra") is None:
        r["slike_extra"] = []


@router.get("/novosti", response_model=List[dict])
def list_novosti():
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("""
                SELECT n.id, n.naslov, n.sodrzina, n.slika_path, n.video_url, n.slike_extra, n.created_at, n.updated_at,
                       d.name AS author_name, d.surname AS author_surname
                FROM Novosti n
                LEFT JOIN Doctors d ON n.author_doctor_id = d.doctor_ID
                ORDER BY n.created_at DESC
            """)
        except Exception as col_err:
            if "Unknown column" in str(col_err) or "unknown column" in str(col_err).lower():
                cur.execute("""
                    SELECT n.id, n.naslov, n.sodrzina, n.slika_path, n.created_at, n.updated_at,
                           d.name AS author_name, d.surname AS author_surname
                    FROM Novosti n
                    LEFT JOIN Doctors d ON n.author_doctor_id = d.doctor_ID
                    ORDER BY n.created_at DESC
                """)
            else:
                raise
        rows = cur.fetchall()
        for r in rows:
            r.setdefault("video_url", None)
            r.setdefault("slike_extra", [])
            _normalize_novost_row(r)
        return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.get("/novosti/{novost_id}", response_model=dict)
def get_novost(novost_id: int):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("""
                SELECT n.id, n.naslov, n.sodrzina, n.slika_path, n.video_url, n.slike_extra, n.created_at, n.updated_at,
                       d.name AS author_name, d.surname AS author_surname
                FROM Novosti n
                LEFT JOIN Doctors d ON n.author_doctor_id = d.doctor_ID
                WHERE n.id = %s
            """, (novost_id,))
        except Exception as col_err:
            if "Unknown column" in str(col_err) or "unknown column" in str(col_err).lower():
                cur.execute("""
                    SELECT n.id, n.naslov, n.sodrzina, n.slika_path, n.created_at, n.updated_at,
                           d.name AS author_name, d.surname AS author_surname
                    FROM Novosti n
                    LEFT JOIN Doctors d ON n.author_doctor_id = d.doctor_ID
                    WHERE n.id = %s
                """, (novost_id,))
            else:
                raise
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Новостта не е пронајдена")
        row.setdefault("video_url", None)
        row.setdefault("slike_extra", [])
        _normalize_novost_row(row)
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.post("/admin/novosti")
def create_novost(
    naslov: str = Form(...),
    sodrzina: str = Form(...),
    admin_doctor_id: int = Form(...),
    video_url: Optional[str] = Form(None),
    slika: Optional[UploadFile] = File(None),
    sliki_extra: List[UploadFile] = File(default=[]),
):
    if not check_admin_access(admin_doctor_id):
        raise HTTPException(status_code=403, detail="Немате пристап. Само директорот може да додава новости.")
    naslov = (naslov or "").strip()
    sodrzina = (sodrzina or "").strip()
    if not naslov:
        raise HTTPException(status_code=400, detail="Насловот е задолжителен.")
    video_url = (video_url or "").strip() or None
    slika_path = _save_upload(slika) if slika else None
    extra_paths = []
    for f in sliki_extra:
        p = _save_upload(f)
        if p:
            extra_paths.append(p)
    slike_extra_json = json.dumps(extra_paths) if extra_paths else None
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "INSERT INTO Novosti (naslov, sodrzina, slika_path, video_url, slike_extra, author_doctor_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (naslov, sodrzina, slika_path, video_url, slike_extra_json, admin_doctor_id),
            )
        except Exception as ins_err:
            if "Unknown column" in str(ins_err) or "unknown column" in str(ins_err).lower():
                cur.execute(
                    "INSERT INTO Novosti (naslov, sodrzina, slika_path, author_doctor_id) VALUES (%s, %s, %s, %s)",
                    (naslov, sodrzina, slika_path, admin_doctor_id),
                )
            else:
                raise
        conn.commit()
        new_id = cur.lastrowid
        return {"message": "Новоста е додадена.", "id": new_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.put("/admin/novosti/{novost_id}")
def update_novost(
    novost_id: int,
    naslov: Optional[str] = Form(None),
    sodrzina: Optional[str] = Form(None),
    admin_doctor_id: int = Form(...),
    video_url: Optional[str] = Form(None),
    slika: Optional[UploadFile] = File(None),
    remove_slika: Optional[str] = Form(None),
    sliki_extra: List[UploadFile] = File(default=[]),
):
    if not check_admin_access(admin_doctor_id):
        raise HTTPException(status_code=403, detail="Немате пристап. Само директорот може да уредува новости.")
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT id, slika_path, video_url, slike_extra FROM Novosti WHERE id = %s", (novost_id,))
        except Exception as sel_err:
            if "Unknown column" in str(sel_err) or "unknown column" in str(sel_err).lower():
                cur.execute("SELECT id, slika_path FROM Novosti WHERE id = %s", (novost_id,))
            else:
                raise
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Новостта не е пронајдена.")
        slika_path = row.get("slika_path")
        video_url_val = (video_url or "").strip() or None if video_url is not None else row.get("video_url")
        slike_extra_current = row.get("slike_extra")
        if isinstance(slike_extra_current, str) and slike_extra_current:
            try:
                slike_extra_current = json.loads(slike_extra_current)
            except Exception:
                slike_extra_current = []
        else:
            slike_extra_current = [] if slike_extra_current is None else slike_extra_current
        if remove_slika and str(remove_slika).strip().lower() in ("1", "true", "yes"):
            if slika_path:
                full = Path(__file__).resolve().parent.parent / "static" / slika_path
                if full.exists():
                    try:
                        full.unlink()
                    except Exception:
                        pass
            slika_path = None
        if slika:
            if slika_path:
                full = Path(__file__).resolve().parent.parent / "static" / slika_path
                if full.exists():
                    try:
                        full.unlink()
                    except Exception:
                        pass
            slika_path = _save_upload(slika)
        extra_paths = list(slike_extra_current) if slike_extra_current else []
        for f in sliki_extra:
            p = _save_upload(f)
            if p:
                extra_paths.append(p)
        slike_extra_json = json.dumps(extra_paths) if extra_paths else None
        cur.execute("SELECT naslov, sodrzina FROM Novosti WHERE id = %s", (novost_id,))
        current = cur.fetchone()
        new_naslov = (naslov or "").strip() if naslov is not None else (current["naslov"] or "")
        new_sodrzina = (sodrzina or "").strip() if sodrzina is not None else (current["sodrzina"] or "")
        if not new_naslov:
            raise HTTPException(status_code=400, detail="Насловот е задолжителен.")
        try:
            cur.execute(
                "UPDATE Novosti SET naslov = %s, sodrzina = %s, slika_path = %s, video_url = %s, slike_extra = %s WHERE id = %s",
                (new_naslov, new_sodrzina, slika_path, video_url_val, slike_extra_json, novost_id),
            )
        except Exception as upd_err:
            if "Unknown column" in str(upd_err) or "unknown column" in str(upd_err).lower():
                cur.execute(
                    "UPDATE Novosti SET naslov = %s, sodrzina = %s, slika_path = %s WHERE id = %s",
                    (new_naslov, new_sodrzina, slika_path, novost_id),
                )
            else:
                raise
        conn.commit()
        return {"message": "Новоста е ажурирана.", "id": novost_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.delete("/admin/novosti/{novost_id}")
def delete_novost(novost_id: int, admin_doctor_id: Optional[int] = None):
    if admin_doctor_id is None or not check_admin_access(admin_doctor_id):
        raise HTTPException(status_code=403, detail="Немате пристап. Само директорот може да брише новости.")
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT slika_path, slike_extra FROM Novosti WHERE id = %s", (novost_id,))
        except Exception as sel_err:
            if "Unknown column" in str(sel_err) or "unknown column" in str(sel_err).lower():
                cur.execute("SELECT slika_path FROM Novosti WHERE id = %s", (novost_id,))
            else:
                raise
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Новостта не е пронајдена.")
        cur.execute("DELETE FROM Novosti WHERE id = %s", (novost_id,))
        conn.commit()
        static_dir = Path(__file__).resolve().parent.parent / "static"
        if row.get("slika_path"):
            full = static_dir / row["slika_path"]
            if full.exists():
                try:
                    full.unlink()
                except Exception:
                    pass
        if row.get("slike_extra"):
            try:
                for p in json.loads(row["slike_extra"]):
                    full = static_dir / p
                    if full.exists():
                        try:
                            full.unlink()
                        except Exception:
                            pass
            except Exception:
                pass
        return {"message": "Новоста е избришана."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn and conn.is_connected():
            conn.close()
