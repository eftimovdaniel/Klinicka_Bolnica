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

# site sliki od novosti se smestuvat vo blob ne lokalno na serverot
from azure.storage.blob import BlobServiceClient    # povrzuvanje na python so azure
# ako nema .env / prazen string – nema Azure pri start (inaku from_connection_string(None) frla AttributeError)
AZURE_CONNECTION_STRING = (os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "").strip()
CONTAINER_NAME = (os.getenv("AZURE_CONTAINER_NAME") or "").strip()

blob_service_client = None
if AZURE_CONNECTION_STRING and CONTAINER_NAME:
    blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)


router = APIRouter(tags=["novosti"])

# pateka do kade ke odat slikite i site dozvoleni formati koj moze da se stavat kako slika video od strana na admin bez da se naprave prob 
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads" / "novosti"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _ensure_upload_dir():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def _save_upload(file: UploadFile) -> Optional[str]:        # prima objekti od tip UploadFile fastapi standard za fajlovi i vraka link ili none
    if not file or not file.filename:       # proverka dali e isptaten fajl ili ne
        return None
    ext = Path(file.filename).suffix.lower()        # ja vlece ekstenzijata, tipot na prikaceniot fajl.
    if ext not in ALLOWED_EXTENSIONS:       # proverka dali e vo dozvoleni ekstenzii ili ne
        return None
    
    name = f"{uuid.uuid4().hex}{ext}"       # generiranje na novo, unikatno ime za fajlot. Korisni e koga dvajca korisnici ke prikacat slika so isto ime

    contents = file.file.read()     # go cita fajlot od memorijata na serverot, binarna forma
    if blob_service_client and CONTAINER_NAME:
        try:
            blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=name)      # povrzuvanje so cloud provajderot i se koriste za save na fajlovi vo kontenjeri so unikatno ime
            blob_client.upload_blob(contents, overwrite=True)   # gi praka podatocite na cloud
            return blob_client.url
        except Exception as e:
            print(f"Грешка при Azure Upload:{e}")
            return None
    # lokalen dev: nema Azure – zacuvaj pod static/uploads/novosti, URL za frontend /static/...
    try:
        _ensure_upload_dir()
        dest = UPLOAD_DIR / name
        dest.write_bytes(contents)
        return f"/static/uploads/novosti/{name}"
    except Exception as e:
        print(f"Грешка при локален upload:{e}")
        return None
    
def _is_full_url(s: Optional[str]) -> bool:
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    return s.startswith("http://") or s.startswith("https://")


@router.post("/admin/novosti")
def create_novost(
    naslov: str = Form(...),
    sodrzina: str = Form(...),
    admin_doctor_id: int = Form(...),
    video_url: Optional[str] = Form(None),
    slika_position: Optional[str] = Form(None),
    slika_height: Optional[str] = Form(None),
    slika_url: Optional[str] = Form(None),
    slika: Optional[UploadFile] = File(None),
    slike_extra_urls: Optional[str] = Form(None),
    sliki_extra: List[UploadFile] = File(default=[]),
):
    if not check_admin_access(admin_doctor_id):
        raise HTTPException(status_code=403, detail="За зал немате пристап, новости се додаваат само од овластени лица во установата. Би благодариме на разбиранјето.")
    naslov = (naslov or "").strip()
    sodrzina = (sodrzina or "").strip()
    if not naslov:
        raise HTTPException(status_code=400, detail="Насловот е задолжителен.")
    video_url = (video_url or "").strip() or None
    slika_position = (slika_position or "").strip() or None
    slika_height = (slika_height or "").strip() or None
    slika_path = None
    slika_url_val = (slika_url or "").strip() or None
    if slika_url_val and _is_full_url(slika_url_val):
        slika_path = slika_url_val
    elif slika:
        slika_path = _save_upload(slika)
    extra_paths = []
    if slike_extra_urls and isinstance(slike_extra_urls, str):
        for line in slike_extra_urls.strip().splitlines():
            u = line.strip()
            if u and _is_full_url(u):
                extra_paths.append(u)
            elif u and u.startswith("uploads/"):
                extra_paths.append(u)
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
                "INSERT INTO Novosti (naslov, sodrzina, slika_path, slika_position, slika_height, video_url, slike_extra, author_doctor_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (naslov, sodrzina, slika_path, slika_position, slika_height, video_url, slike_extra_json, admin_doctor_id),
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
    slika_position: Optional[str] = Form(None),
    slika_height: Optional[str] = Form(None),
    slika_url: Optional[str] = Form(None),
    slika: Optional[UploadFile] = File(None),
    remove_slika: Optional[str] = Form(None),
    slike_extra_urls: Optional[str] = Form(None),
    sliki_extra: List[UploadFile] = File(default=[]),
):
    if not check_admin_access(admin_doctor_id):
        raise HTTPException(status_code=403, detail="Немате пристап. Само директорот може да уредува новости.")
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT id, slika_path, slika_position, slika_height, video_url, slike_extra FROM Novosti WHERE id = %s", (novost_id,))
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
        slika_position_val = (slika_position or "").strip() or None if slika_position is not None else row.get("slika_position")
        slika_height_val = (slika_height or "").strip() or None if slika_height is not None else row.get("slika_height")
        slike_extra_current = row.get("slike_extra")
        if isinstance(slike_extra_current, str) and slike_extra_current:
            try:
                slike_extra_current = json.loads(slike_extra_current)
            except Exception:
                slike_extra_current = []
        else:
            slike_extra_current = [] if slike_extra_current is None else slike_extra_current
        if remove_slika and str(remove_slika).strip().lower() in ("1", "true", "yes"):
            if slika_path and not _is_full_url(slika_path):
                full = Path(__file__).resolve().parent.parent / "static" / slika_path
                if full.exists():
                    try:
                        full.unlink()
                    except Exception:
                        pass
            slika_path = None
        slika_url_val = (slika_url or "").strip() or None
        if slika_url_val and _is_full_url(slika_url_val):
            slika_path = slika_url_val
        elif slika:
            if slika_path and not _is_full_url(slika_path):
                full = Path(__file__).resolve().parent.parent / "static" / slika_path
                if full.exists():
                    try:
                        full.unlink()
                    except Exception:
                        pass
            slika_path = _save_upload(slika)
        extra_paths = []
        if slike_extra_urls and isinstance(slike_extra_urls, str):
            for line in slike_extra_urls.strip().splitlines():
                u = line.strip()
                if u and _is_full_url(u):
                    extra_paths.append(u)
                elif u and u.startswith("uploads/"):
                    extra_paths.append(u)
        elif slike_extra_current:
            extra_paths = list(slike_extra_current)
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
                "UPDATE Novosti SET naslov = %s, sodrzina = %s, slika_path = %s, slika_position = %s, slika_height = %s, video_url = %s, slike_extra = %s WHERE id = %s",
                (new_naslov, new_sodrzina, slika_path, slika_position_val, slika_height_val, video_url_val, slike_extra_json, novost_id),
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



def _normalize_novost_row(r: dict) -> None:
    if r.get("created_at"):
        r["created_at"] = r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"])
    if r.get("updated_at"):
        r["updated_at"] = r["updated_at"].isoformat() if hasattr(r["updated_at"], "isoformat") else str(r["updated_at"])
    r.setdefault("slika_position", None)
    r.setdefault("slika_height", None)
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
                SELECT n.id, n.naslov, n.sodrzina, n.slika_path, n.slika_position, n.slika_height, n.video_url, n.slike_extra, n.created_at, n.updated_at,
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
                SELECT n.id, n.naslov, n.sodrzina, n.slika_path, n.slika_position, n.slika_height, n.video_url, n.slike_extra, n.created_at, n.updated_at,
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
