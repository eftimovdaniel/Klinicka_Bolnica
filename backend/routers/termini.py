import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.header import Header
from email import encoders

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from datetime import datetime
from database import get_connection
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from io import BytesIO

router = APIRouter(prefix="/termini", tags=["termini"])


def _isprati_email_poraka(to_email: str, subject: str, body: str, log_uspesno: str) -> None:
    """Заедничка SMTP испраќање (или печатење во конзола без SMTP)."""
    if not to_email or "@" not in to_email:
        return

    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_pass = os.environ.get("SMTP_PASSWORD", "").strip()
    from_addr = os.environ.get("EMAIL_FROM", smtp_user or "noreply@kbstip.mk").strip()

    if smtp_host and smtp_user and smtp_pass:
        try:
            smtp_port = int(os.environ.get("SMTP_PORT", "587") or "587")
            msg = MIMEMultipart()
            msg["From"] = from_addr
            msg["To"] = to_email
            msg["Subject"] = str(Header(subject, "utf-8"))
            msg.attach(MIMEText(body, "plain", "utf-8"))
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_addr, to_email, msg.as_string())
            print(f"[EMAIL] {log_uspesno} {to_email}")
        except Exception as e:
            print(f"[EMAIL] Грешка при испраќање на {to_email}: {e}")
    else:
        print("\n" + "=" * 60)
        print("[EMAIL] (SMTP не е поставен – пораката би се испратила на)")
        print("  До:", to_email)
        print("  Наслов:", subject)
        print("-" * 60)
        print(body)
        print("=" * 60 + "\n")


def _poslati_potvrda_na_email(
    to_email: str, ime_pacient: str, ime_lekar: str, datum: str, vreme: str,
    napomena: str | None = None,  # Opcionalna napomena za lekarot — vleguva vo mailot ako ja ima
):
    """Испрати потврда на е-пошта до пациентот по закажан термин."""
    subject = "Потврда за закажан термин – Клиничка Болница Штип"
    # Bazichniot del od mailot (sekogash isti polinja)
    body = f"""Почитуван/а {ime_pacient},

Вашиот термин е успешно закажан.

Лекар: {ime_lekar}
Датум: {datum}
Време: {vreme}
"""
    # Ako pacientot ostavil napomena, dodadi ja na kraj
    if napomena and napomena.strip():
        body += f"\nНапомена за лекарот: {napomena.strip()}\n"
    body += "\nКлиничка Болница Штип\n"
    _isprati_email_poraka(to_email, subject, body, "Потврда за закажување испратена на")


def _poslati_otkaz_na_email(
    to_email: str,
    ime_pacient: str,
    ime_lekar: str,
    datum: str,
    vreme: str,
    specialnost: str = "",
):
    """Испрати потврда на е-пошта до пациентот по откажан термин."""
    spec_red = f"\nСпецијалност: {specialnost}" if specialnost else ""
    subject = "Потврда за откажан термин – Клиничка Болница Штип"
    body = f"""Почитуван/а {ime_pacient},

Вашиот термин е откажан.

Лекар: {ime_lekar}{spec_red}
Датум: {datum}
Време: {vreme}

Доколку сакате нов термин, закажете преку сајтот или AI асистентот.

Клиничка Болница Штип
"""
    _isprati_email_poraka(to_email, subject, body, "Потврда за откажување испратена на")


def _get_termin_za_izvestaj(db_cursor, termin_id: int):
    """Го зема терминот со податоци за пациент и лекар за извештај."""
    db_cursor.execute("""
        SELECT 
            tp.termin_ID,
            tp.datum_pregled,
            TIME(tp.vreme_pregled) as vreme_pregled,
            tp.ime_pacient,
            tp.email_pacient,
            tp.telefon_pacient,
            tp.dijagnoza,
            tp.terapija,
            tp.ime_lekar,
            tp.specijalnost_termin,
            d.name as lekar_ime,
            d.surname as lekar_prezime,
            d.email as lekar_email,
            d.specialty as lekar_specijalnost,
            COALESCE(p.name_patient, '') AS pacient_ime,
            COALESCE(p.surname_patient, '') AS pacient_prezime
        FROM Termin_pregled tp
        LEFT JOIN Doctors d ON tp.doctor_ID = d.doctor_ID
        LEFT JOIN patient p ON LOWER(TRIM(tp.email_pacient)) = LOWER(TRIM(p.email))
        WHERE tp.termin_ID = %s
    """, (termin_id,))
    return db_cursor.fetchone()


def _build_pdf_izvestaj(termin: dict, termin_id: int) -> bytes:
    """Генерира PDF извештај од податоците на терминот. Враќа bytes."""
    vreme = termin.get("vreme_pregled")
    if vreme and hasattr(vreme, "strftime"):
        vreme_str = vreme.strftime("%H:%M")
    elif vreme and hasattr(vreme, "total_seconds"):
        s = int(vreme.total_seconds())
        vreme_str = f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    else:
        vreme_str = str(vreme)[:5] if vreme else ""

    datum = termin.get("datum_pregled")
    if datum:
        if isinstance(datum, str):
            datum_obj = datetime.strptime(datum, "%Y-%m-%d").date()
        else:
            datum_obj = datum if hasattr(datum, 'strftime') else datetime.strptime(str(datum), "%Y-%m-%d").date()
        datum_str = datum_obj.strftime("%d.%m.%Y")
    else:
        datum_str = "Н/П"

    if termin.get("pacient_ime") and termin.get("pacient_prezime"):
        pacient_ime_puno = f"{termin.get('pacient_ime', '').strip()} {termin.get('pacient_prezime', '').strip()}".strip()
    else:
        pacient_ime_puno = termin.get("ime_pacient", "").strip()

    if termin.get("lekar_ime") and termin.get("lekar_prezime"):
        lekar_ime_puno = f"{termin.get('lekar_ime')} {termin.get('lekar_prezime')}".strip()
    else:
        lekar_ime_puno = termin.get("ime_lekar", "").strip()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Heading1'],
        fontSize=18, textColor=colors.HexColor('#e74c3c'), spaceAfter=30, alignment=1, fontName='Helvetica-Bold'
    )
    heading_style = ParagraphStyle(
        'CustomHeading', parent=styles['Heading2'],
        fontSize=14, textColor=colors.HexColor('#2c3e50'), spaceAfter=12, spaceBefore=12, fontName='Helvetica-Bold'
    )
    normal_style = styles['Normal']
    normal_style.fontSize = 11
    normal_style.leading = 14

    story = []
    story.append(Paragraph("Клиничка Болница Штип - Медицински Извештај", title_style))
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("Податоци за пациентот:", heading_style))
    pacient_data = [
        ["Име и презиме:", pacient_ime_puno or "Н/П"],
        ["Е-пошта:", termin.get("email_pacient", "Н/П")],
        ["Телефон:", termin.get("telefon_pacient", "Н/П")],
    ]
    t1 = Table(pacient_data, colWidths=[2*inch, 4*inch])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    story.append(t1)
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("Податоци за лекарот:", heading_style))
    lekar_data = [
        ["Име и презиме:", lekar_ime_puno or "Н/П"],
        ["Специјалност:", termin.get("lekar_specijalnost") or termin.get("specijalnost_termin") or "Н/П"],
        ["Е-пошта:", termin.get("lekar_email", "Н/П")],
    ]
    t2 = Table(lekar_data, colWidths=[2*inch, 4*inch])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    story.append(t2)
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("Податоци за терминот:", heading_style))
    termin_data = [["Датум:", datum_str], ["Време:", vreme_str or "Н/П"]]
    t3 = Table(termin_data, colWidths=[2*inch, 4*inch])
    t3.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    story.append(t3)
    story.append(Spacer(1, 0.3*inch))
    story.append(Paragraph("Дијагноза:", heading_style))
    story.append(Paragraph((termin.get("dijagnoza", "") or "Нема внесена дијагноза.").replace('\n', '<br/>'), normal_style))
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("Терапија:", heading_style))
    story.append(Paragraph((termin.get("terapija", "") or "Нема внесена терапија.").replace('\n', '<br/>'), normal_style))
    story.append(Spacer(1, 0.3*inch))
    doc.build(story)
    buffer.seek(0)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

@router.get("/dostapni")
def get_dostapni_termini(lekar_id: int, datum: str):    # funkcija koja dava prikaz koj lekar ima sloboden termin, id na lekarot e od tip int, a datum e string
    conn = None                 # nema konekcija pri aktiviranje 
    try:
        if "T" in datum:            # proverka dali vnesot e vo ISO fromat(yy-mm-dd T hh:mm:ss), T go deli vremeto od datumot na pregled
            datum = datum.split("T")[0] # se pravi podelba na mestoto kade e zapisno T ni dava format datum , vreme
                                        # [0] go zema prviot element od listata, toa e datumot (datum T vreme)

        d = datetime.strptime(datum, "%Y-%m-%d").date() # izbraniot string e smesten vo d za proverka na delovi vo nedelata, d se koriste za den 
                                                        # strptime parsiranje na string vo data

        if d.weekday() >= 5:        # proverka dali e vikend, d treba da e pogolemo od 5, sabota i nedela se 6 7 
            return []                  # se vraka prazna lista, nema moznost da se zakaze termin 
        conn = get_connection()         # ostvaruvanje konekcija so bazata 
        db_cursor = conn.cursor(dictionary=True)   # posrednik so bazata na podatoci 
        # se selektira vremeto na pregled od soodvetna tabela
        # ВАЖНО: Според базата, колоната за статус е status_pregled
        # so vneseno ime na lekar i imame status na zakazan pregled
        # СИНХРОНИЗАЦИЈА: Вклучи ги и термините на апарати за да се синхронизираат календарите
        db_cursor.execute("""
            SELECT TIME(vreme_pregled) as vreme
            FROM Termin_pregled
            WHERE doctor_ID = %s AND DATE(datum_pregled) = %s AND status_pregled = 'закажан'
            UNION
            SELECT TIME(vreme_pregled) as vreme
            FROM Aparati_termini
            WHERE doctor_ID = %s AND DATE(datum_pregled) = %s AND status != 'откажан'
        """, (lekar_id, datum, lekar_id, datum))         # dve vrednosti za dve prazni mesta (%s) vo SQL
                                        # lekar_id odi vo prviot %s, datum odi vo vtoriot %s
        rows = db_cursor.fetchall()    # se zemaat site zafateni termini kaj lekar
        out = []                    # lista za vreme
        for r in rows:                 # r minuva niz site rows, odnosno niz site zafateni termini
            v = r.get("vreme")      # v go zima vremeto od redovite
            if v is None:           # ako nema vreme, nema zafaten termin se prodolzuva
                continue
            if hasattr(v, "strftime"):         # hasattr proveruva dali postoi strftime, strftime go dobivam avtomstski bidejki vremeto vo bazata mi e datatime, ako e string ne mora 
                out.append(v.strftime("%H:%M"))  # formatiranje na vremeto spored tip nna cas:minuta
            elif hasattr(v, "total_seconds"):       # proverka dali ima total_seconds    
                s = int(v.total_seconds())          # konverzija vo seknudi 
                out.append(f"{s // 3600:02d}:{(s % 3600) // 60:02d}")       # se pretvara vo cas: minuti format
            else:
                out.append(str(v)[:5])  # za drugi tipovi na podatoci, se pretvara vo string i se zema prvite 5 karaktera
        return out
    # nevazecki format na veneso, so status kod
    except ValueError:
        raise HTTPException(status_code=400, detail="Неважечки формат на датум")
    # ostanatie greski, so statusen kod 500 i string za objasnuvanje
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    # blok kade se traze ako ima konekcija, ako ima aktivna se naoga i se zatvara.
    finally:
        if conn and conn.is_connected():       
            conn.close()


@router.post("")
async def create_termini(request: Request):     # funkcija koja ceka podatoci od klientot 
    conn = None
    try:
        data = await request.json()     # gi zema podatocite od frontend vo vid JSON
        datum_str = data.get("datum", "")       # se zema datumot od formata 
        if "T" in datum_str:               # se pravi proverka dali e vo ISO format 
            datum_str = datum_str.split("T")[0]     # se deli na mestoto na T i se zema samo datumot 
        try:
            # proverka na datumot , konvertiranje na string vo data ovjekt 
            appointment_date = datetime.strptime(datum_str, "%Y-%m-%d").date()
            if appointment_date.weekday() >= 5:     # proverka dali e vikend (sabota i nedela)
                raise HTTPException(    # ako e vikend se javuva greska, so stausen kod i objasnuvanje
                    status_code=400, detail="Не се закажуваат прегледи во сабота и недела. Изберете друг датум."
                )
        except ValueError:   # ako e izbran nevazecki datum
            raise HTTPException(status_code=400, detail="Неважечки формат на датум")
        # se zema vremeto za obrabotka, odnosno delot sto se naoga posle T
        vreme_str = data.get("vreme", "")   # go zema vremeto od podatocite
        if ":" in vreme_str:    # se pravi proverka dali e so :
            parts = vreme_str.split(":")    # se deli na cas i minuti 
            vreme_str = f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"      # .zfill(2) = додава водечка нула (2→02, 5→05), sekogas ke e vo oblik 13:06 ili slicno 

        conn = get_connection()         # konekcija so bazata 
        db_cursor = conn.cursor(dictionary=True)       # posrednik so bazata
        # prv povik, se proveruva dali lekar postoi
        db_cursor.execute("SELECT name, surname, specialty FROM Doctors WHERE doctor_ID = %s", (data['lekar_id'],))
        doctor = db_cursor.fetchone()          # se zema najdobriot lekar
        if not doctor:          # ako ne e pronajden lekar
            raise HTTPException(status_code=404, detail="Лекар не е пронајден")
        # vtor povik, da se proveri dali termin e veke zakazan
        # ВАЖНО: Според базата, колоната за статус е status_pregled
        db_cursor.execute("""
            SELECT termin_ID FROM Termin_pregled
            WHERE doctor_ID = %s AND DATE(datum_pregled) = %s AND TIME(vreme_pregled) = %s AND status_pregled = 'закажан'
        """, (data['lekar_id'], datum_str, vreme_str))
        if db_cursor.fetchone():
            raise HTTPException(status_code=409, detail="Овој термин е веќе закажан. Изберете друго време.")
        # povik da vnesenite podatoci se vnesat vo bazata za da se zakaze termin 
        # se vnesuvaat id na lekat, ime na pacient, spacijalnost, ime na lekar, datum na pregled, email na pacienti i napomena dokolku e potreba do lekarot
        db_cursor.execute("""
            INSERT INTO Termin_pregled 
            (doctor_ID, ime_pacient, specijalnost_termin, ime_lekar, datum_pregled, vreme_pregled, status_pregled, email_pacient, telefon_pacient, napomena)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data['lekar_id'],       # se zapisuva id na lekaror
            data['ime'] + " " + data['prezime'],        # ime i prezime
            doctor['specialty'],            # speciјалност
            doctor['name'] + " " + doctor['surname'], # ime i prezime na lekar
            datum_str,          # datum
            vreme_str,          # vreme
            'закажан',          # status na pregledot 
            data.get('email', ''),      # email na pacient
            data.get('telefon', ''),    # telefon na pacitne
            data.get('napomena', '')    # napomena od pacient do lekar
        ))
        conn.commit()       # se pravi promena vo bazata, se zacuvuva sekoja promena
        appointment_id = db_cursor.lastrowid   #Se zima id to na novozakazaniot termin

        # Испрати потврда на е-пошта до пациентот
        patient_email = data.get("email", "").strip()
        if patient_email:
            ime_prezime = (data.get("ime", "") + " " + data.get("prezime", "")).strip()
            doctor_full = doctor["name"] + " " + doctor["surname"]
            _poslati_potvrda_na_email(patient_email, ime_prezime, doctor_full, datum_str, vreme_str)

        return {
            "message": "Терминот е успешно закажан! Ќе добиете потврда на вашата е-пошта.",
            "appointment_ID": appointment_id
        }
    except HTTPException:                   # formatirana greska
        raise
    except Exception as e:              # bilo koja druga greksa, so statusen kod i soodvetno objasnuvanje
        raise HTTPException(status_code=500, detail=str(e))
    finally:                    # blok koj ja zatvara konekcija bez razlika dali ima ili nema greska
        if conn and conn.is_connected():
            conn.close()


@router.patch("/{termin_id}")
async def update_termin_dijagnoza_terapija(termin_id: int, request: Request):   # funkcija za update na dijagnoza i terapija so id na termin
    conn = None
    try:
        data = await request.json()  # gi zema podatocite od frontend (JSON)
        dijagnoza = data.get("dijagnoza")  # dijagnoza moze da bide string ili None
        terapija = data.get("terapija")    # terapija moze da bide string ili None
        
        conn = get_connection()         # konekcija so bazata na podatoci
        db_cursor = conn.cursor(dictionary=True)
        db_cursor.execute(
            "SELECT termin_ID FROM Termin_pregled WHERE termin_ID = %s",
            (termin_id,)
        )
        if not db_cursor.fetchone():
            raise HTTPException(status_code=404, detail="Термин не е пронајден")
        dij_n = (dijagnoza or "").strip() or None
        ter_n = (terapija or "").strip() or None
        # Кога лекарот ги зачува дијагноза/терапија, прегледот се смета за завршен (пациентот може да оцени).
        if dij_n or ter_n:
            db_cursor.execute(
                """
                UPDATE Termin_pregled
                SET dijagnoza = %s, terapija = %s, status_pregled = 'завршен'
                WHERE termin_ID = %s
                """,
                (dij_n, ter_n, termin_id),
            )
        else:
            db_cursor.execute(
                "UPDATE Termin_pregled SET dijagnoza = %s, terapija = %s WHERE termin_ID = %s",
                (dij_n, ter_n, termin_id),
            )
        conn.commit()       # se pravi promena vo bazata, se zacuvuva
        return {"message": "Дијагноза и терапија се ажурирани."}
    except HTTPException:               # formatirana greska
        raise
    except Exception as e:              # dokolku se javi bilo koja druga greska
        raise HTTPException(status_code=500, detail=str(e))   # statusen kod 500 i objasnuvanje smesteno vo e
    finally:                        # se proveruva dali ima konekcija, ako ima se zatvara, se izvrasuva bez razlika dali ima ili nema greksa
        if conn and conn.is_connected():
            conn.close()


@router.get("/izvestaj-pdf/{termin_id}")
async def generate_izvestaj_pdf(termin_id: int):
    """
    Генерира PDF извештај за одреден термин.
    Вклучува податоци за пациентот, лекарот, дијагноза и терапија.
    """
    conn = None
    try:
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        termin = _get_termin_za_izvestaj(db_cursor, termin_id)
        if not termin:
            raise HTTPException(status_code=404, detail="Термин не е пронајден")
        pdf_content = _build_pdf_izvestaj(termin, termin_id)
        return Response(
            content=pdf_content,
            media_type='application/pdf',
            headers={"Content-Disposition": f'attachment; filename="izvestaj_termin_{termin_id}.pdf"'}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Грешка при генерирање на PDF: {str(e)}")
    finally:
        if conn and conn.is_connected():
            conn.close()


@router.post("/{termin_id}/poslati-izvestaj")
async def poslati_izvestaj_na_pacient(termin_id: int):
    """
    Генерира PDF извештај за терминот и го испраќа на е-поштата на пациентот
    (email_pacient од терминот – истата адреса со која пациентот е најавен).
    За конфигурација: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, FROM_EMAIL (опционално).
    """
    conn = None
    try:
        conn = get_connection()
        db_cursor = conn.cursor(dictionary=True)
        termin = _get_termin_za_izvestaj(db_cursor, termin_id)
        if not termin:
            raise HTTPException(status_code=404, detail="Термин не е пронајден")

        email_pacient = (termin.get("email_pacient") or "").strip()
        if not email_pacient or "@" not in email_pacient:
            raise HTTPException(
                status_code=400,
                detail="Пациентот нема валидна е-пошта за испраќање на извештај."
            )

        pdf_bytes = _build_pdf_izvestaj(termin, termin_id)

        smtp_host = os.environ.get("SMTP_HOST")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER")
        smtp_password = os.environ.get("SMTP_PASSWORD")
        from_email = (os.environ.get("FROM_EMAIL") or smtp_user or "").strip()

        if not smtp_host or not smtp_user or not smtp_password or not from_email:
            raise HTTPException(
                status_code=503,
                detail="Испраќањето е-пошта не е конфигурирано (SMTP_HOST, SMTP_USER, SMTP_PASSWORD)."
            )

        msg = MIMEMultipart()
        msg["Subject"] = f"Медицински извештај - Клиничка Болница Штип (термин #{termin_id})"
        msg["From"] = from_email
        msg["To"] = email_pacient
        msg.attach(MIMEText(
            "Почитувани,\n\nВо прилог е вашиот медицински извештај од прегледот.\n\nПоздрав,\nКлиничка Болница Штип",
            "plain",
            "utf-8"
        ))
        part = MIMEBase("application", "pdf")
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=f"izvestaj_termin_{termin_id}.pdf"
        )
        msg.attach(part)

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(from_email, [email_pacient], msg.as_string())

        return {"message": "Извештајот е успешно испратен на е-поштата на пациентот.", "email": email_pacient}
    except HTTPException:
        raise
    except smtplib.SMTPException as e:
        raise HTTPException(status_code=502, detail=f"Грешка при испраќање е-пошта: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Грешка: {str(e)}")
    finally:
        if conn and conn.is_connected():
            conn.close()

