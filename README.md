# Datadrix Assessment Portal — Technical & Aptitude Evaluation Platform

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1-black.svg)](https://flask.palletsprojects.com/)
[![Theme](https://img.shields.io/badge/Theme-Datadrix.com-cyan.svg)](https://www.datadrix.com)
[![Tests](https://img.shields.io/badge/Tests-31%20Passed-brightgreen.svg)]()

**Datadrix Assessment Portal** is an enterprise-grade online assessment application styled with the official **[Datadrix](https://www.datadrix.com)** tech design system (deep dark-navy palette `#080D1A`, `#131C2E`, `#1C273C`, tech grid background, electric blue and cyan/emerald gradient accents, and the official Datadrix logo).

### Results Policy: Reports Only
Upon exam completion or deadline expiration, the platform **strictly shields individual questions, options, and answer keys** from the post-test view. Instead, candidates and evaluators receive a comprehensive **Performance & Competency Report**, including:
1. Overall score and accuracy percentage.
2. Proficiency grading and performance commentary.
3. Correct, incorrect, and unanswered summary breakdown.
4. 4 Domain-wise performance cards with progress metrics and competency ratings (Reasoning, General Aptitude, Logical Reasoning, English Grammar).
5. Cognitive & Skill Competency Matrix detailing evaluated focus areas and outcomes.
6. Official Cryptographic Verification ID and proctoring compliance seal.

It features **20 randomized multiple-choice questions** across 4 domains, a **server-authoritative 30-minute timer**, a **pre-assessment hardware check** (camera preview and live Web Audio microphone meter), an **assessment integrity monitor** with a strict two-strike policy, idempotent transactional scoring, and complete candidate attempt isolation.

---

## Table of Contents
1. [Core Features](#1-core-features)
2. [Technology Stack](#2-technology-stack)
3. [Project Architecture](#3-project-architecture)
4. [Question Bank Structure](#4-question-bank-structure)
5. [Assessment Integrity & Two-Strike Warning Policy](#5-assessment-integrity--two-strike-warning-policy)
6. [Camera, Microphone & Privacy Notice](#6-camera-microphone--privacy-notice)
7. [Installation & Local Setup](#7-installation--local-setup)
8. [Database Initialization & Seeding](#8-database-initialization--seeding)
9. [Running the Application](#9-running-the-application)
10. [Automated Testing](#10-automated-testing)
11. [Production WSGI & Deployment Guide](#11-production-wsgi--deployment-guide)
12. [PostgreSQL Migration & Backup Procedures](#12-postgresql-migration--backup-procedures)
13. [Troubleshooting Guide](#13-troubleshooting-guide)

---

## 1. Core Features

- **Executive Light Theme**: Clean, accessible palette (`#F8FAFC` slate background, `#FFFFFF` cards, `#2563EB` primary) with typography powered by Inter.
- **Candidate Registration & Validation**:
  - Full Name, Email, and Mobile number validation on both client and server.
  - Server-side normalization (whitespace trimming, title casing, lowercase emails, standard international phone digits).
  - Anti double-click protection preventing accidental duplicate assessment creations.
- **Dedicated Pre-Assessment Device Check**:
  - Live video preview stream via WebRTC `getUserMedia`.
  - Live microphone test utilizing the Web Audio API (`AudioContext` and `AnalyserNode`) with an interactive volume bar and sound-detection verification.
  - Browser compatibility inspection (`WebRTC`, `AudioContext`, `Page Visibility API`, `Fullscreen API`).
  - Gated CTA: "Start Test" is unlocked only once hardware permissions are granted and audio input is detected.
- **Timed Assessment (30 Minutes)**:
  - Strict server-authoritative countdown timer stored in the database (`deadline = start_time + 30m`).
  - Remaining time synchronized with the backend; page reloads or reconnects cannot reset or extend the timer.
  - Visual urgency states: Amber badge at 5 minutes; pulsing red warning at 1 minute.
  - Automatic submission upon deadline expiry; answer modifications after the deadline are strictly rejected with HTTP 400.
- **Interactive Question Palette**:
  - 20-question navigation grid with 5 real-time states: *Not Visited*, *Visited Unanswered*, *Answered*, *Marked for Review*, and *Answered & Marked for Review*.
  - Section progress indicators and overall completion counters.
  - Seamless background autosave of answer selections and review tags (`POST /api/assessment/<attempt_id>/answer`).
  - Submission confirmation modal detailing answered, unanswered, and marked-for-review counts.
- **Assessment Integrity System**:
  - Page Visibility API (`visibilitychange`), window `blur`, and fullscreen exit monitoring.
  - 2-second debouncing window avoiding duplicate counts from simultaneous browser events.
  - **Strike 1**: Warning modal explaining regulations and requesting return to exam.
  - **Strike 2**: Immediate abort; attempt is voided (`status = 'aborted'`), scores invalidated, and the candidate must retake with a brand new randomized question set.
- **Comprehensive Results & Explanations**:
  - Total score out of 20 and accuracy percentage out of 100%.
  - Correct, incorrect, and unanswered breakdown.
  - 4 section-wise performance scorecards with progress bars.
  - Full question review table with candidate selections, correct answers, and thorough pedagogical explanations.
- **Strict Data Security & Confidentiality**:
  - Server-side session isolation: candidate IDs stored in signed HTTP-only cookies; candidates cannot view or modify other candidates' exams or results (HTTP 403).
  - Unguessable UUID v4 attempt identifiers.
  - Correct answers and answer explanations are kept on the server and never leaked to the client during active assessments.

---

## 2. Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.10+ / Flask 3.1 |
| **ORM & DB** | SQLAlchemy 2.0 / Flask-SQLAlchemy (SQLite development, PostgreSQL production) |
| **Forms & Security** | Flask-WTF 1.3, WTForms 3.3, email-validator 2.4, CSRFProtect |
| **Frontend** | HTML5, CSS3 Custom Properties, ES6 JavaScript |
| **UI Framework** | Bootstrap 5.3.3 + Bootstrap Icons 1.11 |
| **Audio Processing** | Web Audio API (`AudioContext`, `AnalyserNode`) |
| **Video Proctoring** | WebRTC MediaStream API (`navigator.mediaDevices.getUserMedia`) |
| **Production WSGI** | Gunicorn (Linux/Containers) / Waitress (Windows/Cross-platform) |
| **Testing** | pytest 9.2 (30 automated unit & integration tests) |

---

## 3. Project Architecture

```
apexassess/
├── app/
│   ├── __init__.py               # Flask application factory (create_app)
│   ├── config.py                 # Configuration classes (Dev, Testing, Prod)
│   ├── extensions.py             # db (SQLAlchemy) and csrf (CSRFProtect)
│   ├── forms.py                  # CandidateRegistrationForm with validators
│   ├── models/
│   │   ├── __init__.py           # Exported models
│   │   ├── candidate.py          # Candidate entity
│   │   ├── question.py           # Question bank entity
│   │   └── assessment.py         # AssessmentAttempt, AttemptQuestion, AssessmentEvent
│   ├── routes/
│   │   ├── __init__.py           # Exported blueprints
│   │   ├── main.py               # Landing, registration, device check routes
│   │   ├── assessment.py         # Exam interface, answer autosave, violation, submit
│   │   └── results.py            # Scorecard, review table, aborted view
│   ├── services/
│   │   ├── __init__.py
│   │   ├── question_service.py   # Seeding, random 5/section generation, review payload
│   │   ├── scoring_service.py    # Idempotent scoring, section breakdown calculations
│   │   ├── integrity_service.py  # Violation debouncing & two-strike enforcement
│   │   └── timer_service.py      # Server-authoritative remaining time & auto-expire
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css         # Executive light design system tokens & components
│   │   └── js/
│   │       ├── registration.js   # Client validation & double-click guard
│   │       ├── device_check.js   # WebRTC camera preview & Web Audio microphone meter
│   │       ├── timer.js          # Synchronized countdown timer with warnings
│   │       ├── integrity.js      # Page visibility, window blur & strike tracking
│   │       └── assessment.js     # Question navigation, autosave & submission modal
│   └── templates/
│       ├── base.html             # Layout, CDN assets, navbar, footer & CSRF meta
│       ├── index.html            # Registration landing with 4 informational cards
│       ├── device_check.html     # Pre-assessment camera & microphone verification
│       ├── assessment.html       # Distraction-free active assessment interface
│       ├── result.html           # Scorecard, section progress & answer review table
│       ├── aborted.html          # Two-strike integrity abort screen with retake action
│       └── errors/               # Standardized error pages (400, 403, 404, 500)
├── seed/
│   └── questions.json            # 100 verified MCQs (25 per domain) with answer keys
├── tests/
│   ├── conftest.py               # Test app, client, sample candidate & fixtures
│   ├── test_registration.py      # Form validation & candidate creation tests
│   ├── test_assessment.py        # Question sampling, option checks & answer saves
│   ├── test_timer.py             # 30-min duration, expiration & deadline tests
│   ├── test_integrity.py         # 1st strike warning, 2nd strike abort & retake tests
│   ├── test_scoring.py           # 20-pt scoring, section breakdown & idempotency tests
│   └── test_security.py          # Cross-candidate access blocking & answer shielding
├── .env.example                  # Environment variable blueprint
├── .gitignore                    # Version control exclusions
├── gunicorn_config.py            # Linux production WSGI configuration
├── pytest.ini                    # Pytest configuration
├── requirements.txt              # Production and development dependencies
├── run.py                        # Local development runner
└── wsgi.py                       # Production WSGI entry point
```

---

## 4. Question Bank Structure

The platform includes a curated repository of **100 verified questions** (`seed/questions.json`) partitioned into four sections:

1. **Reasoning (25 questions, `REA-001` to `REA-025`)**:
   - Number and letter series, pattern recognition, coding-decoding, direction sense, blood relations, and ranking/ordering.
2. **General Aptitude (25 questions, `APT-001` to `APT-025`)**:
   - Percentages, profit & loss, ratios & proportions, averages, time & work, speed time distance, and arithmetic.
3. **Logical Reasoning (25 questions, `LOG-001` to `LOG-025`)**:
   - Syllogisms, statement and conclusion, analogies, seating arrangements, deductions, and classification/odd-one-out.
4. **English Grammar (25 questions, `ENG-001` to `ENG-025`)**:
   - Subject-verb agreement, tenses, articles & prepositions, error identification, sentence correction, and vocabulary in context.

When a candidate initiates an assessment attempt, the server randomly samples **exactly 5 questions from each of the 4 sections** (20 total), ensuring that no assessment attempt has identical questions.

---

## 5. Assessment Integrity & Two-Strike Warning Policy

To maintain exam credibility without invasive spyware:

1. **Monitored Browser Events**:
   - `document.visibilitychange` via the Page Visibility API.
   - `window.onblur` (switching away to another program or clicking outside).
   - Fullscreen exit events via the Fullscreen API.
2. **Debouncing Window**:
   - Multiple browser events often trigger synchronously when leaving a screen (e.g., `blur` followed by `visibilitychange`).
   - The server and client apply a 2.0-second sliding debounce filter so that a single user action is not counted twice.
3. **Two-Strike Enforcement**:
   - **Strike 1 (Warning)**: An uncloseable modal is displayed on the screen. The attempt continues and a `VIOLATION_WARNING` audit event is logged with timestamp.
   - **Strike 2 (Termination)**: The attempt is instantly aborted (`status = 'aborted'`), answers are voided, a `VIOLATION_ABORT` audit event is logged, and the candidate is redirected to `/aborted/<attempt_id>`.
4. **Clean Retake Workflow**:
   - Candidates with voided attempts can click **Retake Assessment**, which generates a new attempt record with fresh randomized questions and a new 30-minute timer. Prior attempts are retained in the database for administrative audits.

---

## 6. Camera, Microphone & Privacy Notice

- **Hardware Checks**:
  - The pre-assessment screen requires camera and microphone permissions before enabling the test.
  - Web Audio API computes root-mean-square audio input and renders a real-time responsive volume meter.
- **Assessment PiP Preview**:
  - During the exam, a miniature camera preview is pinned in the header bar.
  - If a device is disconnected or the media track ends, a warning banner alerts the candidate and logs a `DEVICE_DISCONNECTED` event (which is audited without triggering a screen-switch abort strike).
- **Privacy Notice**:
  > **Zero Server Recording**: The camera and microphone streams are processed exclusively within the local browser runtime for proctoring verification. No video recordings, audio recordings, or biometric signatures are stored on or uploaded to any server.

---

## 7. Installation & Local Setup

### Prerequisites
- Python 3.10, 3.11, 3.12, 3.13, or 3.14
- Git

### 1. Clone or Open Workspace
```bash
cd "c:\Users\Dell\Desktop\datadrix test"
```

### 2. Create and Activate a Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
# Windows PowerShell
Copy-Item .env.example .env

# macOS / Linux
cp .env.example .env
```

---

## 8. Database Initialization & Seeding

The application automatically creates database tables and seeds the 100 questions upon first startup. You can also trigger database management via Flask CLI:

```bash
# Initialize SQLite database schema
flask init-db

# Seed or update the 100-question question bank
flask seed-db
```

---

## 9. Running the Application

### Development Server
```bash
python run.py
```
Open [http://localhost:5000](http://localhost:5000) in your web browser.

### Windows WSGI Server (Waitress)
```bash
python wsgi.py
```
Serves the production WSGI application on port 8080.

---

## 10. Automated Testing

The project includes **30 comprehensive automated tests** written with `pytest`, covering all validation, scoring, integrity, timer, and security constraints.

### Run Test Suite
```bash
pytest -v
```

### Test Coverage Highlights
- `tests/test_registration.py`: Full name formatting, email regex, mobile phone digits, consent checkbox, and session verification.
- `tests/test_assessment.py`: 5 questions per section, 20 total questions, option integrity, answer autosaving, review flag toggling, and answer concealment.
- `tests/test_timer.py`: 30-minute duration, non-resetting timer on reconnect, server-authoritative deadline expiration, and rejection of answers after time expires.
- `tests/test_integrity.py`: 1st strike warning dialog, 2.0s debouncing, 2nd strike immediate abort, audit event logs, and fresh retake generation.
- `tests/test_scoring.py`: 1 mark per correct answer, 0 for incorrect/unanswered (no negative marking), section-wise scores, and idempotent submission handling.
- `tests/test_security.py`: Cross-candidate attempt isolation (HTTP 403), unauthenticated access blocking (HTTP 401), and shielding of answer explanations.

---

## 11. Production WSGI & Deployment Guide

### Linux / Docker / Cloud Deployment (Gunicorn)
Run using the supplied `gunicorn_config.py`:
```bash
gunicorn -c gunicorn_config.py wsgi:application
```

### Deploying to Render / Railway / Heroku
1. **Set Environment Variables**:
   - `FLASK_ENV`: `production`
   - `SECRET_KEY`: Generate a cryptographically secure key: `python -c "import secrets; print(secrets.token_hex(32))"`
   - `DATABASE_URL`: Your hosted PostgreSQL connection URI (e.g. `postgresql://user:password@host:5432/dbname`)
   - `SESSION_COOKIE_SECURE`: `True`
2. **Build Command**:
   ```bash
   pip install -r requirements.txt && flask init-db && flask seed-db
   ```
3. **Start Command**:
   ```bash
   gunicorn -c gunicorn_config.py wsgi:application
   ```

### HTTPS Requirement for WebRTC Camera and Microphone
Modern web browsers (Chrome, Edge, Firefox, Safari) **strictly enforce** that `navigator.mediaDevices.getUserMedia` is only available in **Secure Contexts**:
- Local development: `http://localhost:5000` or `http://127.0.0.1:5000` is automatically treated as secure.
- Production hosting: You **must** configure an SSL/TLS certificate (e.g. through Let's Encrypt, Cloudflare, or your cloud provider's automatic SSL). Accessing the site over unencrypted `http://<domain>` will cause camera and microphone permissions to be blocked by browser security.

---

## 12. PostgreSQL Migration & Backup Procedures

### Migrating from SQLite to PostgreSQL
1. Install PostgreSQL adapter:
   ```bash
   pip install psycopg2-binary
   ```
2. Set the `DATABASE_URL` environment variable:
   ```bash
   DATABASE_URL=postgresql://dbuser:dbpassword@localhost:5432/assessment_db
   ```
3. Run the database initialization and seed command:
   ```bash
   flask init-db
   flask seed-db
   ```

### Database Backup
- **SQLite**:
  ```bash
  sqlite3 assessment.db ".backup 'backup_$(date +%Y%m%d_%H%M%S).db'"
  ```
- **PostgreSQL**:
  ```bash
  pg_dump -U dbuser -d assessment_db -F c -b -v -f "apexassess_backup_$(date +%Y%m%d_%H%M%S).dump"
  ```

---

## 13. Troubleshooting Guide

| Issue | Cause | Resolution |
|---|---|---|
| **Camera / Mic Denied** | Browser blocked media permission | Click the padlock or site settings icon next to the URL bar, change Camera & Microphone to "Allow", and reload. |
| **Media Devices Undefined** | Site opened via plain HTTP on a non-localhost IP | WebRTC requires HTTPS or `localhost`. Access via `http://localhost:5000` or deploy behind SSL. |
| **CSRF Token Missing** | Client submitted without CSRF header | Ensure all custom fetch requests include `"X-CSRFToken": document.querySelector('meta[name="csrf-token"]').getAttribute("content")`. |
| **403 Forbidden on Results** | Attempting to access another candidate's URL | Sessions are isolated. Log in or register as the candidate who completed the assessment. |
| **Submissions Closed** | 30-minute timer elapsed | The server automatically scores whatever answers were saved up to the deadline. |

---

## License
MIT License. Built for enterprise and academic assessment environments.
