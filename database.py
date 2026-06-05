"""Database helper module for FormGuard AI.

Provides `get_db_connection()` and `init_db()` to initialize and access
the SQLite database. Kept separate for clarity and reuse.
"""
from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'formguard.db'


def get_db_connection():
    """Return a sqlite3 connection with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create required tables if they don't exist."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'user',
        created_at TEXT,
        reset_token TEXT,
        reset_expires TEXT
    );
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        filename TEXT,
        uploaded_at TEXT,
        status TEXT,
        confidence INTEGER,
        summary TEXT,
        verification_score REAL DEFAULT 0,
        is_genuine INTEGER DEFAULT 1,
        is_fake_confidence REAL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS extractions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER,
        field_name TEXT,
        field_value TEXT,
        note TEXT,
        FOREIGN KEY(document_id) REFERENCES documents(id)
    );
    CREATE TABLE IF NOT EXISTS forms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        document_id INTEGER,
        filled_data TEXT,
        submitted_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(document_id) REFERENCES documents(id)
    );
    CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER,
        result TEXT,
        reason TEXT,
        confidence_score REAL,
        created_at TEXT,
        FOREIGN KEY(document_id) REFERENCES documents(id)
    );
    CREATE TABLE IF NOT EXISTS user_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        theme TEXT DEFAULT 'dark',
        language TEXT DEFAULT 'english',
        notifications_enabled INTEGER DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    ''')
    conn.commit()
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN stored_filename TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE extractions ADD COLUMN coordinates TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN verification_score REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN is_genuine INTEGER DEFAULT 1')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN is_fake_confidence REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN content_hash TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN quality_score REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN ocr_confidence REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN image_quality_note TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN issue_date TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN document_type TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN signature_detected INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN stamp_detected INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN layout_validation TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN language_detected TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('CREATE TABLE IF NOT EXISTS user_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE, theme TEXT DEFAULT "dark", language TEXT DEFAULT "english", notifications_enabled INTEGER DEFAULT 1, FOREIGN KEY(user_id) REFERENCES users(id))')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('ALTER TABLE documents ADD COLUMN extracted_text TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute('''CREATE TABLE IF NOT EXISTS verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            result TEXT,
            reason TEXT,
            confidence_score REAL,
            created_at TEXT,
            FOREIGN KEY(document_id) REFERENCES documents(id)
        )''')
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def seed_demo_documents(user_id: int, min_docs: int = 10) -> int:
    """
    Create demo documents + verifications if the given user has too few.
    Returns number of documents inserted.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    existing = cur.execute('SELECT COUNT(*) AS c FROM documents WHERE user_id = ?', (user_id,)).fetchone()['c'] or 0
    if existing >= min_docs:
        conn.close()
        return 0

    # Spread uploads across recent days so charts/analytics look alive.
    import datetime
    now = datetime.datetime.now()

    demo_rows = [
        # filename, status, confidence, summary, is_genuine, fake_conf
        ('citizenship_card_ramesh_adhikari.jpg', 'Verified', 96, 'Genuine document — fields match expected format.', 1, 0.04),
        ('passport_sita_sharma.pdf', 'Warning', 58, 'Needs review — one or more fields uncertain.', 1, 0.22),
        ('degree_certificate_bikash_thapa.png', 'Verified', 92, 'Genuine document — strong OCR match.', 1, 0.06),
        ('marksheet_transcript_priya_karki.jpg', 'Verified', 89, 'Genuine document — consistent identifiers.', 1, 0.10),
        ('experience_letter_sunil_kc.pdf', 'Warning', 49, 'Low confidence — verify issuer/format.', 1, 0.35),
        ('national_id_card_mina_gurung.png', 'Verified', 94, 'Genuine document — valid ID layout.', 1, 0.05),
        ('birth_certificate_fake_sample.jpg', 'Rejected', 22, 'Rejected — suspected tampering or invalid format.', 0, 0.88),
        ('citizenship_card_duplicate_check.png', 'Warning', 54, 'Possible duplicate — requires manual confirmation.', 1, 0.28),
        ('employment_letter_company_x.pdf', 'Verified', 90, 'Genuine document — consistent data.', 1, 0.09),
        ('other_document_sample.png', 'Verified', 86, 'Genuine document — accepted by verification model.', 1, 0.14),
        ('marksheet_grade_sheet_demo.jpg', 'Warning', 52, 'Medium confidence — check legibility and seal.', 1, 0.30),
        ('certificate_training_demo.pdf', 'Verified', 91, 'Genuine document — structured fields detected.', 1, 0.07),
    ]

    to_insert = demo_rows[: max(0, min_docs - existing)]
    inserted = 0

    for i, (filename, status, confidence, summary, is_genuine, fake_conf) in enumerate(to_insert):
        dt = (now - datetime.timedelta(days=min(12, i))).replace(hour=10, minute=20).isoformat()
        cur.execute(
            '''INSERT INTO documents
               (user_id, filename, uploaded_at, status, confidence, summary, verification_score, is_genuine, is_fake_confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                user_id,
                filename,
                dt,
                status,
                confidence,
                summary,
                float(confidence or 0),
                int(is_genuine),
                float(fake_conf),
            ),
        )
        doc_id = cur.lastrowid
        cur.execute(
            '''INSERT INTO verifications (document_id, result, reason, confidence_score, created_at)
               VALUES (?, ?, ?, ?, ?)''',
            (
                doc_id,
                status,
                summary,
                float(confidence or 0),
                dt,
            ),
        )
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def delete_document(document_id: int, user_id: int, is_admin: bool = False) -> bool:
    """
    Permanently delete a document and related rows (extractions, verifications, forms).
    Removes the uploaded file from disk when stored_filename is set.
    Returns True if a row was deleted, False if not found or not allowed.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    if is_admin:
        row = cur.execute('SELECT * FROM documents WHERE id = ?', (document_id,)).fetchone()
    else:
        row = cur.execute(
            'SELECT * FROM documents WHERE id = ? AND user_id = ?',
            (document_id, user_id),
        ).fetchone()
    if not row:
        conn.close()
        return False

    stored = row['stored_filename'] if 'stored_filename' in row.keys() else None
    cur.execute('DELETE FROM extractions WHERE document_id = ?', (document_id,))
    cur.execute('DELETE FROM verifications WHERE document_id = ?', (document_id,))
    cur.execute('DELETE FROM forms WHERE document_id = ?', (document_id,))
    cur.execute('DELETE FROM documents WHERE id = ?', (document_id,))
    conn.commit()
    conn.close()

    if stored:
        try:
            path = BASE_DIR / 'uploads' / stored
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    return True


def delete_all_documents(user_id: int, is_admin: bool = False) -> int:
    """Delete all documents for a user (or all documents if admin). Returns count deleted."""
    conn = get_db_connection()
    if is_admin:
        rows = conn.execute('SELECT id FROM documents').fetchall()
    else:
        rows = conn.execute('SELECT id FROM documents WHERE user_id = ?', (user_id,)).fetchall()
    conn.close()
    count = 0
    for row in rows:
        if delete_document(row['id'], user_id, is_admin):
            count += 1
    return count
