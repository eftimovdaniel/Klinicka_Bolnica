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

        return {
            "message": "Терминот е успешно закажан!",       # pecatenje na poraka deka imame uspesno zakazan termin
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
        db_cursor.execute(
            "UPDATE Termin_pregled SET dijagnoza = %s, terapija = %s WHERE termin_ID = %s",
            ((dijagnoza or "").strip() or None, (terapija or "").strip() or None, termin_id)
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
        
        # Земи ги податоците за терминот со JOIN на Doctors и patient табелата
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
        
        termin = db_cursor.fetchone()
        
        if not termin:
            raise HTTPException(status_code=404, detail="Термин не е пронајден")
        
        # Форматирај го времето
        vreme = termin.get("vreme_pregled")
        if vreme and hasattr(vreme, "strftime"):
            vreme_str = vreme.strftime("%H:%M")
        elif vreme and hasattr(vreme, "total_seconds"):
            s = int(vreme.total_seconds())
            vreme_str = f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
        else:
            vreme_str = str(vreme)[:5] if vreme else ""
        
        # Форматирај го датумот
        datum = termin.get("datum_pregled")
        if datum:
            if isinstance(datum, str):
                datum_obj = datetime.strptime(datum, "%Y-%m-%d").date()
            else:
                datum_obj = datum if hasattr(datum, 'strftime') else datetime.strptime(str(datum), "%Y-%m-%d").date()
            datum_str = datum_obj.strftime("%d.%m.%Y")
        else:
            datum_str = "Н/П"
        
        # Извлечи име и презиме на пациентот
        if termin.get("pacient_ime") and termin.get("pacient_prezime"):
            pacient_ime = termin.get("pacient_ime", "").strip()
            pacient_prezime = termin.get("pacient_prezime", "").strip()
            pacient_ime_puno = f"{pacient_ime} {pacient_prezime}".strip()
        else:
            # Ако нема JOIN, користи го комбинираното име од Termin_pregled
            pacient_ime_puno = termin.get("ime_pacient", "").strip()
            parts = pacient_ime_puno.split(" ", 1)
            pacient_ime = parts[0] if len(parts) > 0 else ""
            pacient_prezime = parts[1] if len(parts) > 1 else ""
        
        # Извлечи име и презиме на лекарот
        if termin.get("lekar_ime") and termin.get("lekar_prezime"):
            lekar_ime_puno = f"{termin.get('lekar_ime')} {termin.get('lekar_prezime')}".strip()
        else:
            lekar_ime_puno = termin.get("ime_lekar", "").strip()
        
        # Креирај PDF во меморија
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, 
                                rightMargin=72, leftMargin=72,
                                topMargin=72, bottomMargin=72)
        
        # Стилови
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#e74c3c'),
            spaceAfter=30,
            alignment=1,  # Center alignment
            fontName='Helvetica-Bold'
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=12,
            spaceBefore=12,
            fontName='Helvetica-Bold'
        )
        
        normal_style = styles['Normal']
        normal_style.fontSize = 11
        normal_style.leading = 14
        
        # Содржина на PDF-от
        story = []
        
        # Наслов
        story.append(Paragraph("Клиничка Болница Штип - Медицински Извештај", title_style))
        story.append(Spacer(1, 0.3*inch))
        
        # Податоци за пациентот
        story.append(Paragraph("Податоци за пациентот:", heading_style))
        pacient_data = [
            ["Име и презиме:", pacient_ime_puno or "Н/П"],
            ["Е-пошта:", termin.get("email_pacient", "Н/П")],
            ["Телефон:", termin.get("telefon_pacient", "Н/П")],
        ]
        pacient_table = Table(pacient_data, colWidths=[2*inch, 4*inch])
        pacient_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        story.append(pacient_table)
        story.append(Spacer(1, 0.2*inch))
        
        # Податоци за лекарот
        story.append(Paragraph("Податоци за лекарот:", heading_style))
        lekar_data = [
            ["Име и презиме:", lekar_ime_puno or "Н/П"],
            ["Специјалност:", termin.get("lekar_specijalnost") or termin.get("specijalnost_termin") or "Н/П"],
            ["Е-пошта:", termin.get("lekar_email", "Н/П")],
        ]
        lekar_table = Table(lekar_data, colWidths=[2*inch, 4*inch])
        lekar_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        story.append(lekar_table)
        story.append(Spacer(1, 0.2*inch))
        
        # Податоци за терминот
        story.append(Paragraph("Податоци за терминот:", heading_style))
        termin_data = [
            ["Датум:", datum_str],
            ["Време:", vreme_str or "Н/П"],
        ]
        termin_table = Table(termin_data, colWidths=[2*inch, 4*inch])
        termin_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        story.append(termin_table)
        story.append(Spacer(1, 0.3*inch))
        
        # Дијагноза
        story.append(Paragraph("Дијагноза:", heading_style))
        dijagnoza_text = termin.get("dijagnoza", "") or "Нема внесена дијагноза."
        story.append(Paragraph(dijagnoza_text.replace('\n', '<br/>'), normal_style))
        story.append(Spacer(1, 0.2*inch))
        
        # Терапија
        story.append(Paragraph("Терапија:", heading_style))
        terapija_text = termin.get("terapija", "") or "Нема внесена терапија."
        story.append(Paragraph(terapija_text.replace('\n', '<br/>'), normal_style))
        story.append(Spacer(1, 0.3*inch))
        
        # Генерирај PDF
        doc.build(story)
        buffer.seek(0)
        pdf_content = buffer.getvalue()
        buffer.close()
        
        # Врати PDF како Response
        return Response(
            content=pdf_content,
            media_type='application/pdf',
            headers={
                "Content-Disposition": f'attachment; filename="izvestaj_termin_{termin_id}.pdf"'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Грешка при генерирање на PDF: {str(e)}")
    finally:
        if conn and conn.is_connected():
            conn.close()

