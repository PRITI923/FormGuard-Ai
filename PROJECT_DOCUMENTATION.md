"""
# FormGuard AI — Project Documentation

## Summary

FormGuard AI is a document ingestion, OCR extraction, and automated verification system that accelerates form filling and reduces manual review effort. It combines OCR (Tesseract), simple ML verification, and a lightweight Flask web UI to extract structured fields, score document authenticity, and let users review and auto-fill forms.

Purpose: speed up verification workflows, improve data quality, and provide an auditable history and analytics dashboard.

Status: research/prototype (university final-year project). Components are modular for further improvements and production hardening.

---

## Quick Features

- User accounts with registration, login, password reset
- File uploads (images and single-page PDFs)
- OCR extraction (English + Nepali support where traineddata is available)
- ML-based verifier producing `Verified` / `Warning` / `Rejected` and confidence
- Visual verification UI with extracted-field review and auto-fill
- History, reports (CSV/PDF), alerts, and dashboard analytics
- Simple REST API endpoints for integration with other tools

---

## Architecture Overview

- Frontend: Jinja2 templates + Vanilla JS, Chart.js for analytics
- Backend: Flask app serving web routes and JSON APIs
- DB: SQLite for local deployments (schema in `create_db.py`)
- OCR: Tesseract via `pytesseract`; `pdf2image` used for PDF -> image conversion
- ML verifier: lightweight classifier logic in `backend/ml_model/verifier.py`
- File storage: local filesystem under `uploads/`

Diagram (simplified): Upload -> Preprocess -> OCR -> Parse -> Verify -> Store -> Review/Report

---

## Repository Layout

- `app.py` — Flask application entry and main routes
- `create_db.py` — initialize SQLite schema and default admin
- `database.py` — DB helpers and models
- `auth.py` — authentication helpers
- `backend/` — backend modules and API routes
  - `backend/ml_model/verifier.py` — verifier logic and model wrapper
- `ocr/ocr.py` — OCR, preprocessing, parsing and Nepali/English label support
- `templates/` — Jinja2 templates for UI pages
- `static/` — CSS and JS assets
- `uploads/` — saved uploads and generated previews
- `seed_sample_uploads.py` — generate sample data for development
- `requirements.txt` — Python dependencies

---

## Quickstart (Local Development)

1) Create and activate a virtual environment

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2) Install system prerequisites

- Tesseract OCR (and `nep.traineddata` if Nepali support is needed)
- Poppler (`pdftoppm`) for PDF handling on Windows (optional but recommended)

3) Initialize the database

```powershell
python create_db.py
```

4) (Optional) Seed sample uploads

```powershell
python seed_sample_uploads.py
```

5) Run the app

```powershell
python app.py
```

Open the site at: http://127.0.0.1:5000

Default admin credentials (development only):
- Email: admin@formguard.ai
- Password: admin123

---

## Usage Notes

- Uploads: supported image formats include PNG, JPG, JPEG, WEBP, HEIC, TIFF, BMP; PDFs are converted to image pages and only the first page is processed by default.
- OCR language: set to `nep+eng` to enable Nepali + English extraction when `nep.traineddata` is installed; otherwise use `eng`.
- Verification: the ML verifier returns `status`, `confidence`, and a brief `reason`. The UI shows OCR-extracted fields for user confirmation before saving.

---

## Key Files & Functions

- `app.py` — glue code: request handling, route wiring, calls to OCR and verifier
- `ocr/ocr.py` — `extract_fields(image_path, lang='eng')` and helper preprocessors
- `backend/ml_model/verifier.py` — `verify(fields)` returns `(status, confidence, summary)`
- `backend/routes/api.py` — JSON endpoints used by the frontend and for integrations
- `create_db.py` — creates tables: `users`, `documents`, `extractions`, `verifications`, `forms`, `logs`, `user_settings`

Link to main file: [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md)

---

## Development & Testing

- Use the provided `seed_sample_uploads.py` to generate test data.
- Logs are printed to console; add a file-based logger for persistent diagnostics.
- For heavier workloads, consider moving OCR and verification into background workers (Celery/RQ) and using PostgreSQL for scaling.

Running a basic smoke test:

```powershell
python -c "import app; print('App module imported')"
python create_db.py
python seed_sample_uploads.py
```

---

## Limitations & Future Work

- OCR quality depends on image quality, skew, and noise; consider advanced preprocessing and model-based OCR for robustness.
- Multi-page PDF support and page navigation are not implemented (current flow processes the first page).
- The ML verifier is intentionally simple for prototype purposes — retraining and richer feature extraction will improve accuracy.
- Internationalization: full bilingual templates and dynamic locale selection are planned improvements.

---

## Contributing

- Create issues for bugs or feature requests.
- Fork and submit PRs; keep changes focused and include tests where possible.
- Follow existing code style and add documentation updates for new features.

---

## License & Contact

This repository is a university project. Check `README.md` for any licensing notes or contact the project owner.

For questions, contact the author(s) listed in `README.md`.

"""

