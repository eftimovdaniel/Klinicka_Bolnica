from fastapi import APIRouter, Request

from database import get_connection
from session_auth import read_token

router = APIRouter(tags=["sesija"])


def _pacient(pacient_id: int) -> dict | None:
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT patient_ID, name_patient AS ime, surname_patient AS prezime,
                   email, phone_number AS telefon, embg
            FROM patient
            WHERE patient_ID = %s
            """,
            (pacient_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "pacient_ID": row["patient_ID"],
            "ime": row.get("ime") or "",
            "prezime": row.get("prezime") or "",
            "email": row.get("email") or "",
            "telefon": row.get("telefon") or "",
            "embg": row.get("embg") or "",
        }
    finally:
        if conn and conn.is_connected():
            conn.close()


def _lekar(doctor_id: int) -> dict | None:
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT doctor_ID, name, surname, email, specialty AS specijalnost
            FROM Doctors
            WHERE doctor_ID = %s
            """,
            (doctor_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "doctor_ID": row["doctor_ID"],
            "name": row.get("name") or "",
            "surname": row.get("surname") or "",
            "email": row.get("email") or "",
            "specijalnost": (row.get("specijalnost") or "").strip(),
        }
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.get("/sesija")
async def tekowna_sesija(request: Request):
    """Кој е најавен според колачето. Празно ако нема валидна сесија."""
    pacient = None
    lekar = None
    try:
        payload = read_token(request, "pacient")
        if payload:
            pacient = _pacient(payload["id"])
        payload = read_token(request, "lekar")
        if payload:
            lekar = _lekar(payload["id"])
    except Exception:
        pacient = None
        lekar = None
    return {"pacient": pacient, "lekar": lekar}
