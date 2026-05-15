"""Admin API: синхронизација Facebook → pending → одобрување."""

from fastapi import APIRouter, HTTPException, Query

from fb_sync import (
    FbSyncError,
    get_sync_info,
    is_configured,
    list_pending,
    publish_pending,
    skip_pending,
    sync_facebook_posts,
)
from routers.admin import check_admin_access

router = APIRouter(prefix="/admin/facebook", tags=["facebook"])


def _require_admin(admin_doctor_id: int | None) -> None:
    if admin_doctor_id is None or not check_admin_access(admin_doctor_id):
        raise HTTPException(
            status_code=403,
            detail="Немате пристап. Само директорот може да управува со Facebook новости.",
        )


@router.get("/status")
def facebook_status(admin_doctor_id: int = Query(...)):
    _require_admin(admin_doctor_id)
    pending = list_pending(limit=100)
    info = get_sync_info()
    return {
        "configured": is_configured(),
        "pending_count": len(pending),
        **info,
    }


@router.post("/sync")
def facebook_sync(admin_doctor_id: int = Query(...)):
    _require_admin(admin_doctor_id)
    try:
        return sync_facebook_posts()
    except FbSyncError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/pending")
def facebook_pending(
    admin_doctor_id: int = Query(...),
    limit: int = Query(20, ge=1, le=50),
):
    _require_admin(admin_doctor_id)
    return {"pending": list_pending(limit=limit)}


@router.post("/pending/{pending_id}/publish")
def facebook_publish(pending_id: int, admin_doctor_id: int = Query(...)):
    _require_admin(admin_doctor_id)
    try:
        novost_id = publish_pending(pending_id, admin_doctor_id)
        return {"ok": True, "novost_id": novost_id}
    except FbSyncError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/pending/{pending_id}/skip")
def facebook_skip(pending_id: int, admin_doctor_id: int = Query(...)):
    _require_admin(admin_doctor_id)
    if not skip_pending(pending_id):
        raise HTTPException(status_code=404, detail="Постот не е пронајден или веќе е обработен.")
    return {"ok": True}
