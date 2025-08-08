# BSE Order Announcements Tracker

Track and analyze corporate order announcements from the Bombay Stock Exchange (BSE). Modern React + Vite frontend, Flask + Selenium backend.

## Features

- Real-time scraping with progress updates
- Date-based analysis with validation
- Clean dashboard with responsive, accessible UI
- Stats and summaries of detected order wins
- Production-ready configs and security hygiene

## Tech Stack

- Frontend: React 18, Vite
- Styling: Vanilla CSS, glassmorphism, responsive
- Backend: Flask, Selenium, Requests, PyPDF2/pdfminer.six (optional)
- Build: Vite + Terser
- Deploy: Vercel/Netlify (frontend), Railway/Render/VM (backend)

## Quick Start

### Backend
Requirements: Python 3.10+, Chrome/Chromium available

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env  # if you keep an example file
# or create .env from values below

python server.py  # dev run; use gunicorn in prod