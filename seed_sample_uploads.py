"""
Generate realistic sample documents in uploads/ and register them in the database
with OCR-style extracted fields and correct document-type categories.
Run: python seed_sample_uploads.py
"""
import datetime
import json
import secrets
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fpdf import FPDF

from database import get_db_connection, init_db, DB_PATH

BASE_DIR = Path(__file__).resolve().parent
UPLOADS = BASE_DIR / 'uploads'
UPLOADS.mkdir(exist_ok=True)

# (filename, doc meta)
SAMPLES = [
    {
        'filename': 'citizenship_card_ramesh_adhikari.jpg',
        'kind': 'citizenship',
        'status': 'Verified',
        'confidence': 96,
        'summary': 'Genuine citizenship card — all fields match expected format.',
        'is_genuine': 1,
        'fake_conf': 0.04,
        'fields': {
            'Name': 'Ramesh Adhikari',
            'Date of Birth': '1995-04-12',
            'Gender': 'Male',
            'Address': 'Pokhara-8, Kaski, Gandaki Province',
            'Citizenship Number': '11-04-78-01234',
            'Document ID': 'CIT-2024-88421',
        },
        'extracted_text': (
            'NEPAL CITIZENSHIP CERTIFICATE\n'
            'Name: Ramesh Adhikari\n'
            'Date of Birth: 1995-04-12\n'
            'Gender: Male\n'
            'Citizenship Number: 11-04-78-01234\n'
            'Address: Pokhara-8, Kaski, Gandaki Province\n'
            'Issued: District Administration Office, Kaski\n'
        ),
    },
    {
        'filename': 'national_id_card_mina_gurung.png',
        'kind': 'id_card',
        'status': 'Verified',
        'confidence': 94,
        'summary': 'Valid national ID card layout and identifiers.',
        'is_genuine': 1,
        'fake_conf': 0.05,
        'fields': {
            'Name': 'Mina Gurung',
            'Date of Birth': '1998-11-03',
            'Gender': 'Female',
            'Address': 'Lalitpur-14, Bagmati Province',
            'Citizenship Number': '45-02-91-05678',
            'Document ID': 'NID-8849201',
        },
        'extracted_text': (
            'NATIONAL ID CARD — NEPAL\n'
            'Name: Mina Gurung\n'
            'Date of Birth: 1998-11-03\n'
            'Gender: Female\n'
            'Citizenship Number: 45-02-91-05678\n'
            'Address: Lalitpur-14, Bagmati Province\n',
        ),
    },
    {
        'filename': 'marksheet_transcript_priya_karki.jpg',
        'kind': 'marksheet',
        'status': 'Verified',
        'confidence': 89,
        'summary': 'Mark sheet verified — grades and student ID consistent.',
        'is_genuine': 1,
        'fake_conf': 0.10,
        'fields': {
            'Name': 'Priya Karki',
            'Date of Birth': '2001-07-23',
            'Gender': 'Female',
            'Institution Name': 'Tribhuvan University, Institute of Science and Technology',
            'Document ID': 'TU-MS-2024-1192',
            'Address': 'Kathmandu, Nepal',
        },
        'extracted_text': (
            'TRIBHUVAN UNIVERSITY — MARK SHEET\n'
            'Name: Priya Karki\n'
            'Symbol No: 02411876\n'
            'Program: B.Sc. Computer Science\n'
            'Semester: VI | Year: 2024\n'
            'GPA: 3.72 | Percentage: 78.4%\n'
            'Institution: Institute of Science and Technology\n',
        ),
    },
    {
        'filename': 'marksheet_grade_sheet_demo.jpg',
        'kind': 'marksheet',
        'status': 'Warning',
        'confidence': 52,
        'summary': 'Medium confidence — seal partially unclear on scan.',
        'is_genuine': 1,
        'fake_conf': 0.30,
        'fields': {
            'Name': 'Sunil KC',
            'Date of Birth': '1999-02-14',
            'Gender': 'Male',
            'Institution Name': 'Kathmandu Model College',
            'Document ID': 'KMC-GRADE-2023-441',
        },
        'extracted_text': (
            'GRADE SHEET / MARK SHEET\n'
            'Name: Sunil KC\n'
            'Class: Grade XII\n'
            'Percentage: 71.2%\n'
            'Institution: Kathmandu Model College\n',
        ),
    },
    {
        'filename': 'degree_certificate_bikash_thapa.png',
        'kind': 'certificate',
        'status': 'Verified',
        'confidence': 92,
        'summary': 'Degree certificate authentic — institution seal detected.',
        'is_genuine': 1,
        'fake_conf': 0.06,
        'fields': {
            'Name': 'Bikash Thapa',
            'Date of Birth': '1996-09-18',
            'Gender': 'Male',
            'Institution Name': 'Pokhara University',
            'Document ID': 'PU-DEG-2019-3301',
            'Address': 'Pokhara, Nepal',
        },
        'extracted_text': (
            'DEGREE CERTIFICATE\n'
            'This is to certify that Bikash Thapa\n'
            'has been awarded Bachelor of Information Technology\n'
            'Institution: Pokhara University\n'
            'Year of Completion: 2019\n',
        ),
    },
    {
        'filename': 'certificate_training_demo.pdf',
        'kind': 'certificate',
        'status': 'Verified',
        'confidence': 91,
        'summary': 'Training certificate — structured fields detected.',
        'is_genuine': 1,
        'fake_conf': 0.07,
        'fields': {
            'Name': 'Anita Shrestha',
            'Institution Name': 'Nepal Skills Training Center',
            'Document ID': 'NSTC-CERT-2022-88',
            'Address': 'Bhaktapur, Nepal',
        },
        'extracted_text': (
            'CERTIFICATE OF COMPLETION\n'
            'Name: Anita Shrestha\n'
            'Course: Digital Literacy & Office Applications\n'
            'Institution: Nepal Skills Training Center\n'
            'Date: 2022-08-15\n',
        ),
    },
    {
        'filename': 'passport_sita_sharma.pdf',
        'kind': 'passport',
        'status': 'Warning',
        'confidence': 58,
        'summary': 'Passport pending review — MRZ zone slightly blurred.',
        'is_genuine': 1,
        'fake_conf': 0.22,
        'fields': {
            'Name': 'Sita Sharma',
            'Date of Birth': '1998-07-23',
            'Gender': 'Female',
            'Citizenship Number': 'PA4523811',
            'Document ID': 'P1234567',
            'Address': 'Baneshwor, Kathmandu',
        },
        'extracted_text': (
            'NEPAL PASSPORT\n'
            'Name: Sita Sharma\n'
            'Date of Birth: 1998-07-23\n'
            'Passport No: PA4523811\n'
            'Nationality: Nepali\n',
        ),
    },
    {
        'filename': 'experience_letter_sunil_kc.pdf',
        'kind': 'experience',
        'status': 'Warning',
        'confidence': 49,
        'summary': 'Experience letter — verify employer signature.',
        'is_genuine': 1,
        'fake_conf': 0.35,
        'fields': {
            'Name': 'Sunil KC',
            'Institution Name': 'Himalaya Tech Solutions Pvt. Ltd.',
            'Document ID': 'HTS-EXP-2024-12',
            'Address': 'Kathmandu, Nepal',
        },
        'extracted_text': (
            'EXPERIENCE LETTER\n'
            'To Whom It May Concern\n'
            'This certifies that Sunil KC worked as Junior Developer\n'
            'at Himalaya Tech Solutions Pvt. Ltd. from 2022-01 to 2024-06.\n',
        ),
    },
    {
        'filename': 'employment_letter_company_x.pdf',
        'kind': 'experience',
        'status': 'Verified',
        'confidence': 90,
        'summary': 'Employment letter verified — consistent employer data.',
        'is_genuine': 1,
        'fake_conf': 0.09,
        'fields': {
            'Name': 'Kiran Maharjan',
            'Institution Name': 'FormGuard Systems Nepal',
            'Document ID': 'FGN-EMP-2025-03',
            'Address': 'Lalitpur, Nepal',
        },
        'extracted_text': (
            'EMPLOYMENT VERIFICATION LETTER\n'
            'Employee: Kiran Maharjan\n'
            'Position: Document Verification Officer\n'
            'Company: FormGuard Systems Nepal\n'
            'Date: 2025-01-10\n',
        ),
    },
    {
        'filename': 'birth_certificate_fake_sample.jpg',
        'kind': 'other',
        'status': 'Rejected',
        'confidence': 22,
        'summary': 'Rejected — suspected tampering or invalid certificate number.',
        'is_genuine': 0,
        'fake_conf': 0.88,
        'fields': {
            'Name': 'Priya Karki',
            'Date of Birth': '2001-01-05',
            'Gender': 'Female',
            'Document ID': 'N/A',
            'Address': 'Chitwan, Nepal',
        },
        'extracted_text': (
            'BIRTH CERTIFICATE\n'
            'Name: Priya Karki\n'
            'Date of Birth: 2001-01-05\n'
            'Certificate No: INVALID-0000\n',
        ),
    },
]


def _font(size=16):
    try:
        return ImageFont.truetype('arial.ttf', size)
    except OSError:
        try:
            return ImageFont.truetype('C:/Windows/Fonts/arial.ttf', size)
        except OSError:
            return ImageFont.load_default()


def draw_document_image(path: Path, title: str, lines: list[str], accent=(124, 58, 237)):
    w, h = 720, 480
    img = Image.new('RGB', (w, h), (248, 245, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((24, 24, w - 24, h - 24), radius=16, outline=accent, width=3, fill=(255, 255, 255))
    draw.rectangle((24, 24, w - 24, 88), fill=accent)
    title_font = _font(22)
    body_font = _font(15)
    draw.text((44, 42), title, fill=(255, 255, 255), font=title_font)
    y = 110
    for line in lines:
        draw.text((48, y), line, fill=(30, 16, 48), font=body_font)
        y += 32
    draw.text((48, h - 56), 'FormGuard AI — Sample Document (Demo)', fill=(107, 84, 160), font=_font(11))
    img.save(path, quality=92)


def write_pdf(path: Path, title: str, paragraphs: list[str]):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 12, title, ln=True)
    pdf.ln(4)
    pdf.set_font('Helvetica', '', 11)
    for p in paragraphs:
        pdf.multi_cell(0, 7, p)
        pdf.ln(2)
    pdf.set_font('Helvetica', 'I', 9)
    pdf.ln(6)
    pdf.cell(0, 8, 'Sample document for FormGuard AI demonstration.', ln=True)
    pdf.output(str(path))


def create_file(sample: dict) -> str:
    """Create file on disk; return stored_filename (with token prefix)."""
    token = secrets.token_hex(8)
    stored = f'{token}_{sample["filename"]}'
    path = UPLOADS / stored
    kind = sample['kind']
    fields = sample['fields']

    if sample['filename'].endswith('.pdf'):
        lines = [f'{k}: {v}' for k, v in fields.items()]
        write_pdf(path, sample['filename'].replace('_', ' ').replace('.pdf', '').title(), lines)
    else:
        title_map = {
            'citizenship': 'NEPAL CITIZENSHIP CERTIFICATE',
            'id_card': 'NATIONAL ID CARD',
            'marksheet': 'MARK SHEET / TRANSCRIPT',
            'certificate': 'CERTIFICATE',
            'other': 'BIRTH CERTIFICATE',
        }
        title = title_map.get(kind, 'OFFICIAL DOCUMENT')
        body = [f'{k}: {v}' for k, v in fields.items()]
        draw_document_image(path, title, body)

    return stored


def _as_text(value) -> str:
    if isinstance(value, tuple):
        return ''.join(value)
    return str(value)


def insert_document(cur, user_id: int, sample: dict, stored_filename: str, day_offset: int):
    now = datetime.datetime.now() - datetime.timedelta(days=day_offset)
    dt = now.replace(hour=10, minute=20, second=0, microsecond=0).isoformat()
    extracted = _as_text(sample['extracted_text'])

    cur.execute(
        '''INSERT INTO documents
           (user_id, filename, stored_filename, uploaded_at, status, confidence, summary,
            verification_score, is_genuine, is_fake_confidence, extracted_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            user_id,
            sample['filename'],
            stored_filename,
            dt,
            sample['status'],
            sample['confidence'],
            sample['summary'],
            float(sample['confidence']),
            int(sample['is_genuine']),
            float(sample['fake_conf']),
            extracted,
        ),
    )
    doc_id = cur.lastrowid

    for field_name, field_value in sample['fields'].items():
        cur.execute(
            'INSERT INTO extractions (document_id, field_name, field_value, note) VALUES (?, ?, ?, ?)',
            (doc_id, field_name, field_value, 'seed_sample'),
        )

    cur.execute(
        '''INSERT INTO verifications (document_id, result, reason, confidence_score, created_at)
           VALUES (?, ?, ?, ?, ?)''',
        (doc_id, sample['status'], sample['summary'], float(sample['confidence']), dt),
    )
    return doc_id


def seed_for_user(user_id: int, replace: bool = False):
    conn = get_db_connection()
    cur = conn.cursor()

    if replace:
        rows = cur.execute('SELECT id, stored_filename FROM documents WHERE user_id = ?', (user_id,)).fetchall()
        for row in rows:
            cur.execute('DELETE FROM extractions WHERE document_id = ?', (row['id'],))
            cur.execute('DELETE FROM verifications WHERE document_id = ?', (row['id'],))
            cur.execute('DELETE FROM forms WHERE document_id = ?', (row['id'],))
            cur.execute('DELETE FROM documents WHERE id = ?', (row['id'],))
            if row['stored_filename']:
                p = UPLOADS / row['stored_filename']
                if p.is_file():
                    p.unlink()

    existing_names = {
        r[0]
        for r in cur.execute(
            'SELECT filename FROM documents WHERE user_id = ?', (user_id,)
        ).fetchall()
    }

    inserted = 0
    for i, sample in enumerate(SAMPLES):
        if sample['filename'] in existing_names and not replace:
            continue
        stored = create_file(sample)
        insert_document(cur, user_id, sample, stored, day_offset=min(12, i))
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def main():
    init_db()
    conn = get_db_connection()
    admin = conn.execute("SELECT id FROM users WHERE email = 'admin@formguard.ai'").fetchone()
    conn.close()
    if not admin:
        print('No admin user. Run: python create_db.py first')
        return

    user_id = admin['id']
    count = seed_for_user(user_id, replace=False)
    print(f'Database: {DB_PATH}')
    print(f'Uploads folder: {UPLOADS}')
    print(f'Added {count} sample document(s) with real demo fields for user id {user_id}.')
    print('Document types: Citizenship/ID, Mark Sheets, Certificates, Experience Letters, Other')
    if count == 0:
        print('All samples already exist. Re-run with: python seed_sample_uploads.py --replace')


if __name__ == '__main__':
    import sys
    init_db()
    conn = get_db_connection()
    admin = conn.execute("SELECT id FROM users WHERE email = 'admin@formguard.ai'").fetchone()
    conn.close()
    if not admin:
        print('Run create_db.py first.')
    else:
        replace = '--replace' in sys.argv
        n = seed_for_user(admin['id'], replace=replace)
        print(f'Done. Seeded {n} documents into uploads + database.')
