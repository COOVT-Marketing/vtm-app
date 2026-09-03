import os
import re
import uuid
from datetime import datetime
from functools import wraps

import pandas as pd
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_file, jsonify
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from werkzeug.utils import secure_filename

from config import Config

app = Flask(__name__)
app.config.from_object(Config)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs("temp_downloads", exist_ok=True)

# ---------- Auth ----------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if (username == app.config["ADMIN_USERNAME"] and
                password == app.config["ADMIN_PASSWORD"]):
            session["authenticated"] = True
            session.permanent = True
            return redirect(url_for("dashboard"))
        flash("Invalid username or password", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- Google Sheets Helpers ----------
def get_sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        app.config["GOOGLE_CREDENTIALS_PATH"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)

def sanitize_sheet_title(filename: str) -> str:
    name = os.path.splitext(filename)[0]
    name = re.sub(r"[^\w\s\-]", "", name)[:80].strip()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{name}_{timestamp}"[:100]

def get_or_create_database_tab(service, sheet_id: str) -> str:
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    existing_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]

    if "Database" in existing_titles:
        return "Database"

    body = {
        "requests": [{
            "addSheet": {
                "properties": {"title": "Database"}
            }
        }]
    }
    service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()

    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="'Database'!A1",
        valueInputOption="RAW",
        body={"values": [["Phone"]]}
    ).execute()
    return "Database"

def append_phones_to_database(service, sheet_id: str, phones: set):
    if not phones:
        return

    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="'Database'!A:A"
    ).execute()
    values = result.get("values", [])

    existing = set()
    for row in values[1:]:
        if row and str(row[0]).strip():
            cleaned = re.sub(r"\D", "", str(row[0]))
            if cleaned:
                existing.add(cleaned)

    new_phones = sorted(phones - existing)
    if not new_phones:
        return

    body = {"values": [[p] for p in new_phones]}
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="'Database'!A:A",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body=body
    ).execute()

def fetch_sold_phones(service, sheet_id: str) -> set:
    """Fetch phone numbers from the FIRST sheet only."""
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="A:Z"          # first sheet
    ).execute()
    values = result.get("values", [])
    if not values:
        return set()

    # Try to find a phone-like header
    header = [str(h).strip().lower() for h in values[0]]
    phone_idx = None
    possible = ["phone", "phone number", "phone_number", "mobile", "cell", "telephone", "contact"]

    for i, h in enumerate(header):
        if any(p in h for p in possible):
            phone_idx = i
            break

    # If no header found, assume first column is phone
    if phone_idx is None:
        phone_idx = 0

    phones = set()
    for row in values[1:]:
        if len(row) > phone_idx and str(row[phone_idx]).strip():
            cleaned = re.sub(r"\D", "", str(row[phone_idx]))
            if cleaned:
                phones.add(cleaned)
    return phones

def create_log_tab(service, sheet_id: str, title: str, df: pd.DataFrame):
    body = {
        "requests": [{
            "addSheet": {
                "properties": {"title": title}
            }
        }]
    }
    service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()

    values = [df.columns.tolist()] + df.astype(str).fillna("").values.tolist()
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{title}'!A1",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()

# ---------- Main Routes ----------
@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html")

@app.route("/process", methods=["POST"])
@login_required
def process_file():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Empty filename"}), 400

    sheet_id = app.config["MASTER_SHEET_ID"]
    if not sheet_id:
        return jsonify({"success": False, "error": "Master Sheet ID is not configured on the server"}), 500

    try:
        filename = secure_filename(file.filename)
        ext = filename.rsplit(".", 1)[-1].lower()

        if ext == "csv":
            df = pd.read_csv(file)
        elif ext in ("xlsx", "xls"):
            df = pd.read_excel(file)
        else:
            return jsonify({"success": False, "error": "Only CSV or Excel files are supported"}), 400

        if df.empty:
            return jsonify({"success": False, "error": "File is empty"}), 400

        # Flexible phone column detection
        POSSIBLE_PHONE_NAMES = [
            "phone", "phone number", "phone_number", "phonenumber", "phone no", "phone no.",
            "mobile", "mobile number", "mobile_number", "mobilenumber",
            "cell", "cell phone", "cellphone", "cell_number",
            "telephone", "tel", "contact", "contact number", "contact_number"
        ]

        actual_phone_col = None
        col_map = {}
        for col in df.columns:
            normalized = str(col).strip().lower().replace("_", " ").replace("-", " ")
            col_map[normalized] = col

        for name in POSSIBLE_PHONE_NAMES:
            key = name.lower().replace("_", " ")
            if key in col_map:
                actual_phone_col = col_map[key]
                break

        if actual_phone_col is None:
            return jsonify({
                "success": False,
                "error": f"No phone column found. Looking for: Phone, Phone Number, phone_number, Mobile, etc. Columns present: {list(df.columns)}"
            }), 400

        df["_normalized_phone"] = (
            df[actual_phone_col]
            .astype(str)
            .str.replace(r"\D", "", regex=True)
        )

        service = get_sheets_service()
        sold_phones = fetch_sold_phones(service, sheet_id)

        mask_good = ~df["_normalized_phone"].isin(sold_phones) & (df["_normalized_phone"] != "")
        good_df = df[mask_good].drop(columns=["_normalized_phone"])
        bad_df = df[~mask_good].drop(columns=["_normalized_phone"])

        # 1. Create history tab only
        tab_title = sanitize_sheet_title(filename)
        create_log_tab(service, sheet_id, tab_title, df.drop(columns=["_normalized_phone"]))

        # 2. Save temporary CSV files for download
        unique_id = str(uuid.uuid4())[:8]
        good_path = os.path.join("temp_downloads", f"good_{unique_id}.csv")
        bad_path = os.path.join("temp_downloads", f"bad_{unique_id}.csv")

        good_df.to_csv(good_path, index=False)
        bad_df.to_csv(bad_path, index=False)

        session["good_file"] = good_path
        session["bad_file"] = bad_path

        return jsonify({
            "success": True,
            "good_count": len(good_df),
            "bad_count": len(bad_df),
            "total": len(df)
        })

    except HttpError as e:
        return jsonify({"success": False, "error": f"Google Sheets API error: {e}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/download/<kind>")
@login_required
def download(kind):
    if kind not in ("good", "bad"):
        return "Invalid", 400

    file_path = session.get(f"{kind}_file")
    if not file_path or not os.path.exists(file_path):
        flash("No data available. Please process a file first.", "error")
        return redirect(url_for("dashboard"))

    filename = f"{kind}_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(
        file_path,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
