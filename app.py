import os
import re
import csv
import json
import sqlite3
import secrets
import hashlib
import datetime
from io import BytesIO, StringIO
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from fpdf import FPDF
from auth import validate_password_strength, hash_password, verify_password, generate_reset_token
from ocr.ocr import extract_text_and_boxes, parse_fields, assess_image_quality
from backend.ml_model.verifier import get_model, verify_document as ml_verify_document
from backend.routes.api import api_bp

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / 'uploads'
DB_PATH = BASE_DIR / 'formguard.db'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'webp', 'heic', 'tiff', 'bmp'}

app = Flask(__name__)
app.secret_key = secrets.token_hex(24)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)
app.register_blueprint(api_bp)

UPLOAD_FOLDER.mkdir(exist_ok=True)

# --- Database helpers ---
from database import get_db_connection, init_db


# --- ML / Validation helpers ---

def create_model():
    """Load Decision Tree classifier (scikit-learn)."""
    get_model()


def save_verification_record(conn, document_id, status, reason, confidence):
    """Persist ML verification outcome to verifications table."""
    conn.execute(
        'INSERT INTO verifications (document_id, result, reason, confidence_score, created_at) VALUES (?, ?, ?, ?, ?)',
        (document_id, status, reason, confidence, datetime.datetime.now().isoformat()),
    )


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def compute_content_hash(filepath):
    try:
        hasher = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def validate_document(fields, user_id, filename, content_hash=None):
    conn = get_db_connection()
    if content_hash:
        duplicates = conn.execute(
            'SELECT COUNT(*) AS count FROM documents WHERE user_id = ? AND content_hash = ?',
            (user_id, content_hash),
        ).fetchone()['count']
    else:
        duplicates = conn.execute(
            'SELECT COUNT(*) AS count FROM documents WHERE user_id = ? AND filename = ?',
            (user_id, filename),
        ).fetchone()['count']
    conn.close()
    status, confidence, reason, _label = ml_verify_document(fields, duplicate=bool(duplicates))
    return status, confidence, reason


def log_event(message):
    conn = get_db_connection()
    conn.execute('INSERT INTO logs (event, created_at) VALUES (?, ?)', (message, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()


# --- Auth helpers ---

def authenticated():
    return session.get('user_id') is not None


def get_current_user():
    if not authenticated():
        return None
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    return user


@app.context_processor
def inject_globals():
    """Sidebar badge, theme, and shared template variables."""
    if not authenticated():
        return dict(alert_count=0, user_theme='light')
    from utils.dashboard_stats import alert_count as _alert_count
    user = get_current_user()
    is_admin = session.get('role') == 'admin'
    theme = 'light'
    if user:
        conn = get_db_connection()
        row = conn.execute('SELECT theme FROM user_settings WHERE user_id = ?', (user['id'],)).fetchone()
        conn.close()
        if row and row['theme']:
            theme = row['theme']
    return dict(
        alert_count=_alert_count(user['id'], is_admin) if user else 0,
        user_theme=theme,
    )


# --- Routes ---

@app.route('/')
def home():
    return render_template('index.html', user=get_current_user())


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm = request.form.get('confirm_password', '')
        if not name or not email or not password:
            flash('Please fill all fields.', 'danger')
            return redirect(url_for('register'))
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))
        if not request.form.get('privacy_agree'):
            flash('You must agree to the Privacy Policy to register.', 'warning')
            return redirect(url_for('register'))
        ok, msg = validate_password_strength(password)
        if not ok:
            flash(msg, 'warning')
            return redirect(url_for('register'))
        conn = get_db_connection()
        existing = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            flash('Email already registered. Please login.', 'warning')
            conn.close()
            return redirect(url_for('login'))
        hashed = hash_password(password)
        conn.execute('INSERT INTO users (name, email, password, created_at) VALUES (?, ?, ?, ?)',
                     (name, email, hashed, datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        flash('Registration successful. Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', user=get_current_user())


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        if user and verify_password(user['password'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session.permanent = bool(request.form.get('remember'))
            flash('Login successful.', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html', user=get_current_user())


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if user:
            token = secrets.token_urlsafe(16)
            expires = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
            conn.execute('UPDATE users SET reset_token = ?, reset_expires = ? WHERE id = ?', (token, expires, user['id']))
            conn.commit()
            reset_link = url_for('reset_password', token=token, _external=True)
            flash(f'Password reset link generated for demo: {reset_link}', 'success')
            log_event(f'Password reset requested for {email}')
        else:
            flash('Email not found.', 'warning')
        conn.close()
    return render_template('forgot_password.html', user=get_current_user())


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE reset_token = ?', (token,)).fetchone()
    if not user or datetime.datetime.fromisoformat(user['reset_expires']) < datetime.datetime.now():
        conn.close()
        flash('Reset link invalid or expired.', 'danger')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        password = request.form['password']
        if not password:
            flash('Enter a new password.', 'warning')
        else:
            hashed = generate_password_hash(password)
            conn.execute('UPDATE users SET password = ?, reset_token = NULL, reset_expires = NULL WHERE id = ?', (hashed, user['id']))
            conn.commit()
            conn.close()
            flash('Password reset successful. Please login.', 'success')
            return redirect(url_for('login'))
    conn.close()
    return render_template('reset_password.html', user=get_current_user())


@app.route('/dashboard')
def dashboard():
    if not authenticated():
        return redirect(url_for('login'))
    from utils.dashboard_stats import gather_stats, gather_chart_series, gather_doc_types, recent_documents
    user = get_current_user()
    is_admin = session.get('role') == 'admin'
    stats = gather_stats(user['id'], is_admin)
    chart = gather_chart_series(user['id'], 'weekly', is_admin)
    doc_types = gather_doc_types(user['id'], is_admin)
    history = recent_documents(user['id'], 8, is_admin)
    return render_template(
        'dashboard.html',
        user=user,
        stats=stats,
        history=history,
        chart_json=json.dumps(chart),
        doc_types_json=json.dumps(doc_types),
    )


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    if request.method == 'POST':
        file = request.files.get('document')
        if not file or file.filename == '':
            flash('Please select a valid document.', 'danger')
            return redirect(url_for('upload'))
        filename = secure_filename(file.filename)
        if allowed_file(filename):
            try:
                destination = UPLOAD_FOLDER / f'{secrets.token_hex(8)}_{filename}'
                file.save(destination)
            except Exception as e:
                log_event(f'File save error for user {user["id"] if user else "?"}: {e}')
                flash('Failed to save uploaded file. Check server permissions or file size limits.', 'danger')
                return redirect(url_for('upload'))

            try:
                text, line_regions, ocr_confidence, language_detected = extract_text_and_boxes(destination)
                image_quality = assess_image_quality(destination)
                content_hash = compute_content_hash(destination)
            except Exception as e:
                log_event(f'OCR error for file {destination}: {e}')
                flash('OCR processing failed. Try uploading a different file or check OCR installation.', 'danger')
                return redirect(url_for('upload'))

            if not text or not text.strip():
                flash('OCR produced no readable text. If this is a photo (WhatsApp), try saving as PNG/JPG and re-upload.', 'warning')

            try:
                fields, field_boxes = parse_fields(text, line_regions)
                status, confidence, summary = validate_document(fields, user['id'], filename, content_hash=content_hash)
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO documents (user_id, filename, stored_filename, uploaded_at, status, confidence, summary, verification_score, is_genuine, is_fake_confidence, extracted_text, ocr_confidence, quality_score, image_quality_note, issue_date, document_type, signature_detected, stamp_detected, layout_validation, language_detected, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        user['id'],
                        filename,
                        destination.name,
                        datetime.datetime.now().isoformat(),
                        status,
                        confidence,
                        summary,
                        confidence / 100.0,
                        1 if status == 'Verified' else 0,
                        round((1 - (confidence / 100.0)), 2),
                        text,
                        ocr_confidence,
                        image_quality['quality_score'],
                        image_quality['notes'],
                        fields.get('Issue Date'),
                        fields.get('Document Type'),
                        1 if fields.get('Signature Detected') == 'Yes' else 0,
                        1 if fields.get('Stamp Detected') == 'Yes' else 0,
                        fields.get('Layout Validation'),
                        language_detected,
                        content_hash,
                    ),
                )
                doc_id = cursor.lastrowid
                save_verification_record(conn, doc_id, status, summary, confidence)
                for key, value in fields.items():
                    coords = field_boxes.get(key)
                    cursor.execute('INSERT INTO extractions (document_id, field_name, field_value, note, coordinates) VALUES (?, ?, ?, ?, ?)',
                                   (doc_id, key, value, 'Extracted from OCR', json.dumps(coords) if coords else None))
                conn.commit()
                conn.close()
            except Exception as e:
                log_event(f'Database error when saving extraction for user {user["id"] if user else "?"}: {e}')
                flash('Internal error saving extracted data. Try again or contact admin.', 'danger')
                return redirect(url_for('upload'))

            flash('Document uploaded successfully. Review the verification result below.', 'success')
            return redirect(url_for('result', document_id=doc_id))
        flash('Allowed file types are PNG, JPG, JPEG, WEBP, HEIC, TIFF, BMP, and PDF.', 'warning')
    sample_files = []
    for p in sorted(UPLOAD_FOLDER.glob('*')):
        if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif'):
            sample_files.append(p.name)
    return render_template('upload.html', user=user, sample_files=sample_files[:8])


@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    
    if request.method == 'POST':
        file = request.files.get('document')
        if not file or file.filename == '':
            return jsonify({'success': False, 'error': 'Please select a valid document.'})
        
        filename = secure_filename(file.filename)
        if not allowed_file(filename):
            return jsonify({'success': False, 'error': 'Allowed file types: PNG, JPG, JPEG, WEBP, HEIC, TIFF, BMP, PDF'})
        
        try:
            destination = UPLOAD_FOLDER / f'{secrets.token_hex(8)}_{filename}'
            file.save(destination)
        except Exception as e:
            log_event(f'File save error in verify for user {user["id"]}: {e}')
            return jsonify({'success': False, 'error': 'Failed to save file. Check file size/permissions.'})
        
        try:
            text, line_regions, ocr_confidence, language_detected = extract_text_and_boxes(destination)
            image_quality = assess_image_quality(destination)
            content_hash = compute_content_hash(destination)
        except Exception as e:
            log_event(f'OCR error in verify for file {destination}: {e}')
            return jsonify({'success': False, 'error': 'OCR processing failed. Try a different file.'})
        
        if not text or not text.strip():
            return jsonify({'success': False, 'error': 'No readable text found. Please use clear scans.'})
        
        try:
            fields, field_boxes = parse_fields(text, line_regions)
            status, confidence, summary = validate_document(fields, user['id'], filename, content_hash=content_hash)
            
            # Calculate fake confidence (inverse of genuine confidence)
            is_fake_confidence = round((1 - (confidence / 100.0)), 2)
            is_genuine = 1 if status == 'Verified' else 0
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO documents
                (user_id, filename, stored_filename, uploaded_at, status, confidence, summary,
                 verification_score, is_genuine, is_fake_confidence, extracted_text,
                 ocr_confidence, quality_score, image_quality_note, issue_date,
                 document_type, signature_detected, stamp_detected, layout_validation,
                 language_detected, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    user['id'], filename, destination.name, datetime.datetime.now().isoformat(),
                    status, confidence, summary, confidence / 100.0, is_genuine, is_fake_confidence, text,
                    ocr_confidence, image_quality['quality_score'], image_quality['notes'], fields.get('Issue Date'),
                    fields.get('Document Type'), 1 if fields.get('Signature Detected') == 'Yes' else 0,
                    1 if fields.get('Stamp Detected') == 'Yes' else 0, fields.get('Layout Validation'),
                    language_detected, content_hash,
                ),
            )
            doc_id = cursor.lastrowid
            save_verification_record(conn, doc_id, status, summary, confidence)
            
            for key, value in fields.items():
                coords = field_boxes.get(key)
                cursor.execute('''INSERT INTO extractions 
                    (document_id, field_name, field_value, note, coordinates) 
                    VALUES (?, ?, ?, ?, ?)''',
                    (doc_id, key, value, 'Extracted from OCR', json.dumps(coords) if coords else None))
            
            conn.commit()
            conn.close()
            log_event(f'Document verified for user {user["id"]}: {filename} - {status} ({confidence}%)')
            
            return jsonify({
                'success': True,
                'document_id': doc_id,
                'status': status,
                'confidence': confidence,
                'ocr_confidence': ocr_confidence,
                'summary': summary,
                'is_fake_confidence': is_fake_confidence,
                'fields': fields,
                'image_quality': image_quality,
                'language_detected': language_detected,
            })
        except Exception as e:
            log_event(f'Verification error for user {user["id"]}: {e}')
            return jsonify({'success': False, 'error': 'Verification processing failed. Try again.'})
    
    return render_template('verify.html', user=user)


@app.route('/verify-api/status/<int:document_id>')
def verify_status(document_id):
    if not authenticated():
        return jsonify({'error': 'Unauthorized'}), 401
    
    user = get_current_user()
    conn = get_db_connection()
    document = conn.execute('SELECT * FROM documents WHERE id = ? AND user_id = ?', 
                          (document_id, user['id'])).fetchone()
    conn.close()
    
    if not document:
        return jsonify({'error': 'Document not found'}), 404
    
    return jsonify({
        'status': document['status'],
        'confidence': document['confidence'],
        'summary': document['summary'],
        'is_genuine': document['is_genuine'],
        'is_fake_confidence': document['is_fake_confidence']
    })


@app.route('/result/<int:document_id>')
def result(document_id):
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    document = conn.execute('SELECT * FROM documents WHERE id = ? AND user_id = ?', (document_id, user['id'])).fetchone()
    if not document:
        conn.close()
        flash('Document not found.', 'danger')
        return redirect(url_for('dashboard'))
    extraction = conn.execute('SELECT * FROM extractions WHERE document_id = ?', (document_id,)).fetchall()
    conn.close()
    fields = {row['field_name']: row['field_value'] for row in extraction}
    field_boxes = {}
    for row in extraction:
        if row['coordinates']:
            try:
                field_boxes[row['field_name']] = json.loads(row['coordinates'])
            except Exception:
                field_boxes[row['field_name']] = None
    preview_url = None
    if document['stored_filename']:
        preview_url = url_for('uploaded_file', filename=document['stored_filename'])
    return render_template('result.html', user=user, document=document, fields=fields, field_boxes=field_boxes, preview_url=preview_url)


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/auto-fill/<int:document_id>', methods=['GET', 'POST'])
def auto_fill(document_id):
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    document = conn.execute('SELECT * FROM documents WHERE id = ? AND user_id = ?', (document_id, user['id'])).fetchone()
    if not document:
        conn.close()
        flash('Document not found.', 'danger')
        return redirect(url_for('dashboard'))
    extraction = conn.execute('SELECT * FROM extractions WHERE document_id = ?', (document_id,)).fetchall()
    if request.method == 'POST':
        # Save all extracted/editable keys (supports Nepali fields and future additions).
        editable_keys = [row['field_name'] for row in extraction] if extraction else []
        if not editable_keys:
            editable_keys = [
                'Name',
                'Date of Birth',
                'Gender',
                'Address',
                'Citizenship Number',
                'Document ID',
                'Institution Name',
                'Father/Mother Name',
            ]
        filled = {key: request.form.get(key, '').strip() for key in editable_keys}
        conn.execute('INSERT INTO forms (user_id, document_id, filled_data, submitted_at) VALUES (?, ?, ?, ?)',
                     (user['id'], document_id, json.dumps(filled), datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        flash('Auto-filled form submitted successfully.', 'success')
        return redirect(url_for('result', document_id=document_id))
    conn.close()
    fields = {row['field_name']: row['field_value'] for row in extraction}
    return render_template('auto_fill.html', user=user, document=document, fields=fields)


@app.route('/history')
def history():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    status_filter = request.args.get('status', '')
    search = request.args.get('q', '').strip()
    conn = get_db_connection()
    query = 'SELECT * FROM documents WHERE user_id = ?'
    params = [user['id']]
    if status_filter:
        query += ' AND status = ?'
        params.append(status_filter)
    if search:
        query += ' AND filename LIKE ?'
        params.append(f'%{search}%')
    query += ' ORDER BY uploaded_at DESC'
    docs = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('history.html', user=user, docs=docs, status_filter=status_filter, search=search)


@app.route('/document/<int:document_id>/delete', methods=['POST'])
def delete_document_route(document_id):
    if not authenticated():
        return redirect(url_for('login'))
    from database import delete_document
    user = get_current_user()
    is_admin = session.get('role') == 'admin'
    if delete_document(document_id, user['id'], is_admin):
        flash('Document deleted successfully.', 'success')
    else:
        flash('Document not found or you do not have permission to delete it.', 'danger')
    return redirect(request.referrer or url_for('history'))


@app.route('/history/delete-all', methods=['POST'])
def delete_all_documents_route():
    if not authenticated():
        return redirect(url_for('login'))
    from database import delete_all_documents
    user = get_current_user()
    is_admin = session.get('role') == 'admin'
    confirm = request.form.get('confirm', '').strip().lower()
    if confirm != 'delete':
        flash('Type DELETE to confirm removing all documents.', 'warning')
        return redirect(url_for('history'))
    count = delete_all_documents(user['id'], is_admin)
    flash(f'Deleted {count} document(s).', 'success')
    return redirect(url_for('history'))


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    settings_row = conn.execute('SELECT * FROM user_settings WHERE user_id = ?', (user['id'],)).fetchone()
    if request.method == 'POST':
        action = request.form.get('action', 'profile')
        if action == 'password':
            current = request.form.get('current_password', '')
            new_pw = request.form.get('new_password', '')
            confirm = request.form.get('confirm_password', '')
            if not verify_password(user['password'], current):
                flash('Current password is incorrect.', 'danger')
            elif new_pw != confirm:
                flash('New passwords do not match.', 'danger')
            else:
                ok, msg = validate_password_strength(new_pw)
                if not ok:
                    flash(msg, 'warning')
                else:
                    conn.execute('UPDATE users SET password = ? WHERE id = ?', (hash_password(new_pw), user['id']))
                    conn.commit()
                    flash('Password changed successfully.', 'success')
        else:
            name = request.form.get('name', '').strip()
            theme = request.form.get('theme', settings_row['theme'] if settings_row else 'dark')
            language = request.form.get('language', settings_row['language'] if settings_row else 'en')
            if name:
                conn.execute('UPDATE users SET name = ? WHERE id = ?', (name, user['id']))
                if settings_row:
                    conn.execute('UPDATE user_settings SET theme = ?, language = ? WHERE user_id = ?', (theme, language, user['id']))
                else:
                    conn.execute('INSERT INTO user_settings (user_id, theme, language, notifications_enabled) VALUES (?, ?, ?, 1)',
                                 (user['id'], theme, language))
                conn.commit()
                flash('Profile updated successfully.', 'success')
            else:
                flash('Name cannot be empty.', 'warning')
        conn.close()
        return redirect(url_for('profile'))
    conn.close()
    settings_data = {
        'theme': settings_row['theme'] if settings_row else 'dark',
        'language': settings_row['language'] if settings_row else 'en',
    }
    return render_template('profile.html', user=get_current_user(), settings=settings_data)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    
    # Get or create user settings
    settings_row = conn.execute('SELECT * FROM user_settings WHERE user_id = ?', (user['id'],)).fetchone()
    
    if request.method == 'POST':
        theme = request.form.get('theme', 'dark')
        language = request.form.get('language', 'english')
        notifications = 1 if request.form.get('notifications') else 0
        
        if settings_row:
            conn.execute('''UPDATE user_settings SET theme = ?, language = ?, notifications_enabled = ? 
                           WHERE user_id = ?''',
                        (theme, language, notifications, user['id']))
        else:
            conn.execute('''INSERT INTO user_settings (user_id, theme, language, notifications_enabled) 
                           VALUES (?, ?, ?, ?)''',
                        (user['id'], theme, language, notifications))
        
        conn.commit()
        flash('Settings updated successfully.', 'success')
    
    conn.close()
    
    settings_data = {
        'theme': settings_row['theme'] if settings_row else 'dark',
        'language': settings_row['language'] if settings_row else 'english',
        'notifications_enabled': settings_row['notifications_enabled'] if settings_row else 1
    }
    
    return render_template('settings.html', user=user, settings=settings_data)


@app.route('/alerts')
def alerts():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    is_admin = session.get('role') == 'admin'
    conn = get_db_connection()
    if is_admin:
        rows = conn.execute(
            """SELECT d.*, u.email AS user_email FROM documents d
               JOIN users u ON u.id = d.user_id
               WHERE d.status IN ('Warning', 'Rejected') ORDER BY d.uploaded_at DESC"""
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM documents WHERE user_id = ? AND status IN ('Warning', 'Rejected')
               ORDER BY uploaded_at DESC""",
            (user['id'],),
        ).fetchall()
    conn.close()
    return render_template('alerts.html', user=user, alerts=rows)


@app.route('/api-access')
def api_access():
    if not authenticated():
        return redirect(url_for('login'))
    return render_template('api_access.html', user=get_current_user())


@app.route('/admin')
def admin():
    if not authenticated() or session.get('role') != 'admin':
        flash('Admin access required.', 'danger')
        return redirect(url_for('login'))
    from utils.dashboard_stats import gather_stats, gather_chart_series, gather_doc_types, recent_documents
    user = get_current_user()
    stats = gather_stats(user['id'], is_admin=True)
    chart = gather_chart_series(user['id'], 'weekly', is_admin=True)
    doc_types = gather_doc_types(user['id'], is_admin=True)
    history = recent_documents(user['id'], 8, is_admin=True)
    conn = get_db_connection()
    users = conn.execute('SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC').fetchall()
    docs = conn.execute(
        'SELECT d.id, u.email, d.filename, d.uploaded_at, d.status, d.confidence FROM documents d '
        'JOIN users u ON d.user_id = u.id ORDER BY d.uploaded_at DESC LIMIT 20'
    ).fetchall()
    forms_count = conn.execute('SELECT COUNT(*) AS count FROM forms').fetchone()['count']
    logs = conn.execute('SELECT * FROM logs ORDER BY created_at DESC LIMIT 30').fetchall()
    conn.close()
    return render_template(
        'admin.html',
        user=user,
        users=users,
        docs=docs,
        forms_count=forms_count,
        logs=logs,
        stats=stats,
        history=history,
        chart_json=json.dumps(chart),
        doc_types_json=json.dumps(doc_types),
    )


@app.route('/reports')
def reports():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    docs = conn.execute('SELECT * FROM documents WHERE user_id = ? ORDER BY uploaded_at DESC', (user['id'],)).fetchall()
    status_counts_rows = conn.execute('SELECT status, COUNT(*) AS count FROM documents WHERE user_id = ? GROUP BY status', (user['id'],)).fetchall()
    conn.close()
    status_counts = {row['status']: row['count'] for row in status_counts_rows}
    total_docs = len(docs)
    return render_template('reports.html', user=user, docs=docs, status_counts=status_counts, total_docs=total_docs)


@app.route('/forms')
def forms():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT f.id, f.document_id, f.filled_data, f.submitted_at, d.filename, d.status
        FROM forms f
        JOIN documents d ON d.id = f.document_id
        WHERE f.user_id = ?
        ORDER BY f.submitted_at DESC
    ''', (user['id'],)).fetchall()
    conn.close()
    forms_list = []
    for row in rows:
        try:
            filled_data = json.loads(row['filled_data']) if row['filled_data'] else {}
        except Exception:
            filled_data = {}
        forms_list.append({
            'id': row['id'],
            'document_id': row['document_id'],
            'filename': row['filename'],
            'status': row['status'],
            'submitted_at': row['submitted_at'],
            'data': filled_data
        })
    return render_template('forms.html', user=user, forms=forms_list)


@app.route('/forms/<int:form_id>', methods=['GET', 'POST'])
def form_detail(form_id):
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    row = conn.execute('''
        SELECT f.id, f.document_id, f.filled_data, f.submitted_at, d.filename, d.status
        FROM forms f
        JOIN documents d ON d.id = f.document_id
        WHERE f.id = ? AND f.user_id = ?
    ''', (form_id, user['id'])).fetchone()
    if not row:
        conn.close()
        flash('Form not found.', 'danger')
        return redirect(url_for('forms'))

    try:
        filled_data = json.loads(row['filled_data']) if row['filled_data'] else {}
    except Exception:
        filled_data = {}

    if request.method == 'POST':
        updated = {
            'Name': request.form.get('Name', '').strip(),
            'Date of Birth': request.form.get('Date of Birth', '').strip(),
            'Gender': request.form.get('Gender', '').strip(),
            'Address': request.form.get('Address', '').strip(),
            'Citizenship Number': request.form.get('Citizenship Number', '').strip(),
            'Document ID': request.form.get('Document ID', '').strip(),
            'Institution Name': request.form.get('Institution Name', '').strip(),
        }
        conn.execute('UPDATE forms SET filled_data = ?, submitted_at = ? WHERE id = ?',
                     (json.dumps(updated), datetime.datetime.now().isoformat(), form_id))
        conn.commit()
        conn.close()
        flash('Submitted form updated successfully.', 'success')
        return redirect(url_for('form_detail', form_id=form_id))

    conn.close()
    return render_template('forms_detail.html', user=user, form=row, filled_data=filled_data)


@app.route('/forms/export/csv')
def export_forms_csv():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT f.id, d.filename, d.status, f.submitted_at, f.filled_data
        FROM forms f
        JOIN documents d ON d.id = f.document_id
        WHERE f.user_id = ?
        ORDER BY f.submitted_at DESC
    ''', (user['id'],)).fetchall()
    conn.close()
    sio = StringIO()
    writer = csv.writer(sio)
    writer.writerow(['Form ID', 'Document', 'Status', 'Submitted At', 'Name', 'Date of Birth', 'Address', 'Citizenship Number', 'Document ID', 'Institution Name'])
    for row in rows:
        try:
            data = json.loads(row['filled_data']) if row['filled_data'] else {}
        except Exception:
            data = {}
        writer.writerow([
            row['id'], row['filename'], row['status'], row['submitted_at'],
            data.get('Name', ''), data.get('Date of Birth', ''), data.get('Address', ''),
            data.get('Citizenship Number', ''), data.get('Document ID', ''), data.get('Institution Name', '')
        ])
    output = BytesIO(sio.getvalue().encode('utf-8'))
    output.seek(0)
    return send_file(output, mimetype='text/csv', as_attachment=True, download_name='formguard_submitted_forms.csv')


@app.route('/forms/export/pdf')
def export_forms_pdf():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT f.id, d.filename, d.status, f.submitted_at, f.filled_data
        FROM forms f
        JOIN documents d ON d.id = f.document_id
        WHERE f.user_id = ?
        ORDER BY f.submitted_at DESC
    ''', (user['id'],)).fetchall()
    conn.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 10, 'FormGuard AI Submitted Forms', ln=True, align='C')
    pdf.set_font('Arial', '', 10)
    pdf.ln(4)
    pdf.cell(0, 8, f'Generated for {user["name"]}', ln=True)
    pdf.ln(4)

    for row in rows:
        try:
            data = json.loads(row['filled_data']) if row['filled_data'] else {}
        except Exception:
            data = {}

        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 8, f'Form ID: {row["id"]} — Document: {row["filename"]}', ln=True)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, f'Status: {row["status"]} | Submitted: {row["submitted_at"]}', ln=True)
        pdf.ln(2)

        for key, value in data.items():
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(45, 7, f'{key}:', border=0)
            pdf.set_font('Arial', '', 10)
            pdf.multi_cell(0, 7, str(value))
        pdf.ln(4)

    pdf_data = pdf.output(dest='S').encode('latin1')
    output = BytesIO(pdf_data)
    output.seek(0)
    return send_file(output, mimetype='application/pdf', as_attachment=True, download_name='formguard_submitted_forms.pdf')


@app.route('/forms/<int:form_id>/export/pdf')
def export_form_pdf(form_id):
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    row = conn.execute('''
        SELECT f.id, f.submitted_at, f.filled_data, d.filename, d.status
        FROM forms f
        JOIN documents d ON d.id = f.document_id
        WHERE f.id = ? AND f.user_id = ?
    ''', (form_id, user['id'])).fetchone()
    conn.close()
    if not row:
        flash('Form not found.', 'danger')
        return redirect(url_for('forms'))

    try:
        data = json.loads(row['filled_data']) if row['filled_data'] else {}
    except Exception:
        data = {}

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 10, 'FormGuard AI Submission', ln=True, align='C')
    pdf.set_font('Arial', '', 10)
    pdf.ln(4)
    pdf.cell(0, 7, f'Form ID: {row["id"]}', ln=True)
    pdf.cell(0, 7, f'Document: {row["filename"]}', ln=True)
    pdf.cell(0, 7, f'Status: {row["status"]}', ln=True)
    pdf.cell(0, 7, f'Submitted: {row["submitted_at"]}', ln=True)
    pdf.ln(4)

    for key, value in data.items():
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(45, 7, f'{key}:', border=0)
        pdf.set_font('Arial', '', 10)
        pdf.multi_cell(0, 7, str(value))
    pdf.ln(4)

    pdf_data = pdf.output(dest='S').encode('latin1')
    output = BytesIO(pdf_data)
    output.seek(0)
    return send_file(output, mimetype='application/pdf', as_attachment=True, download_name=f'formguard_form_{row["id"]}.pdf')


@app.route('/export/csv')
def export_csv():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    docs = conn.execute('SELECT id, filename, uploaded_at, status, confidence, summary FROM documents WHERE user_id = ?', (user['id'],)).fetchall()
    conn.close()
    sio = StringIO()
    writer = csv.writer(sio)
    writer.writerow(['ID', 'Filename', 'Uploaded At', 'Status', 'Confidence', 'Summary'])
    for doc in docs:
        writer.writerow([doc['id'], doc['filename'], doc['uploaded_at'], doc['status'], doc['confidence'], doc['summary']])
    output = BytesIO(sio.getvalue().encode('utf-8'))
    output.seek(0)
    return send_file(output, mimetype='text/csv', as_attachment=True, download_name='formguard_reports.csv')


@app.route('/export/pdf')
def export_pdf():
    if not authenticated():
        return redirect(url_for('login'))
    user = get_current_user()
    conn = get_db_connection()
    docs = conn.execute('SELECT id, filename, uploaded_at, status, confidence, summary FROM documents WHERE user_id = ?', (user['id'],)).fetchall()
    conn.close()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 10, 'FormGuard AI Report', ln=True, align='C')
    pdf.set_font('Arial', '', 10)
    pdf.ln(4)
    pdf.cell(0, 8, f'Report generated for {user["name"]}', ln=True)
    pdf.ln(3)
    for doc in docs:
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 8, f'Document {doc["id"]}: {doc["filename"]}', ln=True)
        pdf.set_font('Arial', '', 10)
        pdf.cell(0, 7, f'Status: {doc["status"]} | Confidence: {doc["confidence"]}% ', ln=True)
        pdf.multi_cell(0, 6, f'Summary: {doc["summary"]}')
        pdf.ln(2)
    pdf_data = pdf.output(dest='S').encode('latin1')
    output = BytesIO(pdf_data)
    output.seek(0)
    return send_file(output, mimetype='application/pdf', as_attachment=True, download_name='formguard_reports.pdf')


@app.route('/assistant', methods=['POST'])
def assistant():
    payload = request.get_json(silent=True) or {}
    message = (payload.get('message') or '').strip()
    if not message:
        return jsonify({'reply': 'Please type a question for the assistant.'})

    user = get_current_user()
    name = user['name'] if user else 'there'
    msg = message.lower()

    if 'upload' in msg or 'file' in msg or 'document' in msg:
        reply = (
            f'Hi {name}! Use the Upload page to submit a scanned document or image. '
            'After uploading, the system runs OCR, verifies fields, and shows the results on the detail screen.'
        )
    elif 'verify' in msg or 'verification' in msg or 'verified' in msg:
        reply = (
            'Verification uses OCR and heuristic checks for name, date of birth, document IDs, and duplicate scans. '
            'If the confidence is low, review the suggested issues and upload a clearer document.'
        )
    elif 'report' in msg or 'export' in msg or 'csv' in msg or 'pdf' in msg:
        reply = (
            'The Reports page lets you export document summaries to CSV or PDF. '
            'Use the Export buttons there to download your analysis files instantly.'
        )
    elif 'form' in msg or 'submitted' in msg or 'edit' in msg:
        reply = (
            'The Forms section shows submitted forms and lets you edit extracted data. '
            'Open any form to update fields and save the corrected submission.'
        )
    elif 'login' in msg or 'register' in msg or 'password' in msg or 'account' in msg:
        reply = (
            'Account questions are handled by Login, Register, and Password Reset flows. '
            'If you need to change your password, use Forgot Password to generate a reset link.'
        )
    else:
        reply = (
            'I can help with the upload workflow, document verification, submitted forms, reports, and account actions. '
            'Try asking something like "How do I export a report?" or "How is document verification performed?"'
        )

    return jsonify({'reply': reply})


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html', user=get_current_user()), 404


if __name__ == '__main__':
    init_db()
    create_model()
    app.run(debug=True)
