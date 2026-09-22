# Vocaltech Marketing – Data Scrubbing Portal

Secure web portal for scrubbing call center lead files against a master Google Sheet.

## Features

- Login protected
- Drag & drop CSV / Excel upload
- Flexible phone column detection (Phone, Phone Number, phone_number, Mobile, etc.)
- Automatic creation of history tabs
- Automatic update of permanent **Results** tab
- Clean GOOD / BAD results with isolated download buttons (unique tokens so files never mix)
- Modern UI with Vocaltech branding

## Local Setup (Windows)

1. Create virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Create `.env` file from `.env.example` and fill in real values.

4. Place your Google service-account JSON in `credentials/service-account.json`.

5. Share your Master Google Sheet with the service account email (Editor access).

6. Run:
   ```
   python app.py
   ```

7. Open http://127.0.0.1:5000

## How GOOD / BAD works

- **GOOD**: Phone number is present and **not** found in the master sold list → clean leads.
- **BAD**: Phone number **is** found in the master sold list, **or** the phone cell is empty.

Each download uses a unique token so clicking “Download Good” can never return the Bad file (and vice versa).

## Production Notes

- Use Gunicorn + Nginx
- Never commit `.env` or the real service-account JSON
- Recommended platforms: Render, Railway, or a VPS

## Tech Stack

- Python + Flask
- pandas + openpyxl
- Google Sheets API v4
- Vanilla HTML / CSS / JS
