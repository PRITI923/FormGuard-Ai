# FormGuard AI

**Smart Document Verification & Auto Filling System** — BIT Final Year Project.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Backend | Python Flask (REST + server-rendered pages) |
| Database | SQLite |
| OCR | Tesseract |
| ML | scikit-learn **Decision Tree Classifier** |

## Features

- Landing page (hero, about, features, 6-step process, FAQ, contact)
- Auth: register (confirm password), login, logout, forgot/reset password
- User dashboard with stats, charts, recent activity
- Upload (drag-and-drop), OCR results, AI verification, auto form fill
- Verification history with search and status filter
- Profile (theme, language EN/NE, change password)
- Admin dashboard (users, documents, logs)
- Dark / light theme toggle

## Folder Structure

```
formguard-ai/
├── frontend/          → see frontend/README.md (maps to static/)
├── backend/           → see backend/README.md
├── templates/         → HTML pages
├── static/            → CSS & JS
├── ocr/               → Tesseract helpers
├── uploads/           → stored files
├── app.py             → main entry
├── database.py
├── requirements.txt
└── formguard.db       → created on first run
```

## Setup

1. **Python 3.10+** and create a virtual environment (optional):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Tesseract OCR** — install and add to PATH ([Windows installer](https://github.com/UB-Mannheim/tesseract/wiki)).

3. **Poppler** (optional, for PDF OCR on Windows) — add `pdftoppm` to PATH.

4. **Initialize database** (creates admin user):
   ```bash
   python create_db.py
   ```

5. **Run**:
   ```bash
   python app.py
   ```

6. Open **http://127.0.0.1:5000**

### Demo admin

- Email: `admin@formguard.ai`
- Password: `admin123`

## API Examples

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/register` | JSON register |
| POST | `/api/login` | JSON login |
| POST | `/api/logout` | Logout |
| GET | `/api/history` | Document history |

Page routes: `/register`, `/login`, `/upload`, `/history`, `/verify`, `/profile`, `/admin`

## Viva Notes

1. **OCR** — `ocr/ocr.py` runs Tesseract and parses fields (name, DOB, gender, IDs, address).
2. **ML** — `backend/ml_model/verifier.py` uses a Decision Tree on 5 binary features.
3. **DB** — `users`, `documents`, `verifications`, `extractions`, `forms` tables in SQLite.
