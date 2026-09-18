import os
import re
import uuid
import io
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

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file"
]


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


# ---------- Google Services ----------
def get_credentials():
    return service_account.Credentials.from_service_account_file(
        app.config["GOOGLE_CREDENTIALS_PATH"],
        scopes=SCOPES
    )


def get_sheets_service():
    return build("sheets", "v4", credentials=get_credentials())


def get_drive_service():
    return build("drive", "v3", credentials=get_credentials())


def fetch_sold_phones(service, sheet_id: str) -> set:
    """Fetch phone numbers from the FIRST sheet only."""
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="A:Z"
    ).execute()
    values = result.get("values", [])
    if not values:
        return set()

    header = [str(h).strip().lower() for h in values[0]]
    phone_idx = 0

    possible = ["phone", "phone number", "phone_number", "mobile", "cell", "telephone", "contact"]
    for i, h in enumerate(header):
        if any(p in h for p in possible):
            phone_idx = i
            break

    phones = set()
    for row in values[1:]:
        if len(row) > phone_idx and str(row[phone_idx]).strip():
            cleaned = re.sub(r"\D", "", str(row[phone_idx]))
            if cleaned:
                phones.add(cleaned)
    return phones


def create_new_spreadsheet(sheets_service, drive_service, title: str, df: pd.DataFrame) -> str:
    """
    Create a brand new Google Spreadsheet, write the full data into it,
    make it accessible via link, and return the shareable URL.
    """
    # 1. Create empty spreadsheet
    spreadsheet_body = {
        "properties": {
            "title": title
        }
    }
    spreadsheet = sheets_service.spreadsheets().create(
        body=spreadsheet_body,
        fields="spreadsheetId,spreadsheetUrl"
    ).execute()

    spreadsheet_id = spreadsheet.get("spreadsheetId")
    spreadsheet_url = spreadsheet.get("spreadsheetUrl")

    # 2. Prepare data
    values = [df.columns.tolist()]
    for row in df.values.tolist():
        clean_row = []
        for cell in row:
            if pd.isna(cell):
                clean_row.append("")
            else:
                clean_row.append(str(cell))
        values.append(clean_row)

    # 3. Write data
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="A1",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()

    # 4. Make the file accessible to anyone with the link
    drive_service.permissions().create(
        fileId=spreadsheet_id,
        body={
            "type": "anyone",
            "role": "reader"
        }
    ).execute()

    return spreadsheet_url


def log_result_to_sheet(service, sheet_id: str, filename: str, good_count: int, bad_count: int, total: int, new_sheet_url: str):
    """Append a summary row to the permanent 'Results' tab."""
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    existing_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]

    if "Results" not in existing_titles:
        body = {
            "requests": [{
                "addSheet": {
                    "properties": {"title": "Results"}
                }
            }]
        }
        service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()

        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="'Results'!A1",
            valueInputOption="RAW",
            body={"values": [["Timestamp", "Filename", "Good", "Bad", "Total", "New Spreadsheet Link"]]}
        ).execute()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [[timestamp, filename, good_count, bad_count, total, new_sheet_url]]

    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="'Results'!A:F",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": row}
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
        original_bytes = file.read()
        file.seek(0)

        filename = secure_filename(file.filename)
        ext = filename.rsplit(".", 1)[-1].lower()

        if ext == "csv":
            df = pd.read_csv(io.BytesIO(original_bytes))
        elif ext in ("xlsx", "xls"):
            df = pd.read_excel(io.BytesIO(original_bytes))
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

        sheets_service = get_sheets_service()
        drive_service = get_drive_service()

        sold_phones = fetch_sold_phones(sheets_service, sheet_id)

        mask_good = ~df["_normalized_phone"].isin(sold_phones) & (df["_normalized_phone"] != "")
        good_df = df[mask_good].drop(columns=["_normalized_phone"])
        bad_df = df[~mask_good].drop(columns=["_normalized_phone"])

        # Create a completely new Google Spreadsheet for this file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_title = f"Scrub_{os.path.splitext(filename)[0]}_{timestamp}"[:100]
        new_sheet_url = create_new_spreadsheet(
            sheets_service,
            drive_service,
            new_title,
            df.drop(columns=["_normalized_phone"])
        )

        # Log summary + link into Results tab of main sheet
        log_result_to_sheet(
            sheets_service,
            sheet_id,
            filename,
            len(good_df),
            len(bad_df),
            len(df),
            new_sheet_url
        )

        # Save temporary CSV files for download
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
        return jsonify({"success": False, "error": f"Google API error: {e}"}), 500
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
