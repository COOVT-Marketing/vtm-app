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

# In-memory map of download tokens → file path (survives within process lifetime)
# Keyed by unique token so Good and Bad never mix, even across concurrent users.
_download_files = {}


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


def fetch_sold_phones(service, sheet_id: str) -> set:
    """Fetch phone numbers from the FIRST sheet only (the master sold list)."""
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range="A:Z"
    ).execute()
    values = result.get("values", [])
    if not values:
        return set()

    header = [str(h).strip().lower() for h in values[0]]
    phone_idx = None
    possible = ["phone", "phone number", "phone_number", "mobile", "cell", "telephone", "contact"]
    for i, h in enumerate(header):
        if any(p in h for p in possible):
            phone_idx = i
            break
    # Fall back to first column only if no header match
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
    """Create a new tab and write the full uploaded file into it."""
    body = {
        "requests": [{
            "addSheet": {
                "properties": {
                    "title": title
                }
            }
        }]
    }
    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body=body
    ).execute()

    values = [df.columns.tolist()]
    for row in df.values.tolist():
        clean_row = []
        for cell in row:
            if pd.isna(cell):
                clean_row.append("")
            else:
                clean_row.append(str(cell))
        values.append(clean_row)

    safe_title = title.replace("'", "''")
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{safe_title}'!A1",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()


def log_result_to_sheet(service, sheet_id: str, filename: str, good_count: int, bad_count: int, total: int, tab_title: str):
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
        # Header row
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="'Results'!A1",
            valueInputOption="RAW",
            body={"values": [["Timestamp", "Filename", "Good", "Bad", "Total", "History Tab"]]}
        ).execute()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [[timestamp, filename, good_count, bad_count, total, tab_title]]
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
        filename = secure_filename(file.filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
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

        # Normalize phones to digits only
        df["_normalized_phone"] = (
            df[actual_phone_col]
            .astype(str)
            .str.replace(r"\D", "", regex=True)
            .str.strip()
        )

        service = get_sheets_service()
        sold_phones = fetch_sold_phones(service, sheet_id)

        # GOOD = phone present AND not in the sold list
        # BAD  = phone is in the sold list OR phone is empty/missing
        mask_good = (
            (df["_normalized_phone"] != "") &
            (~df["_normalized_phone"].isin(sold_phones))
        )
        good_df = df.loc[mask_good].drop(columns=["_normalized_phone"]).copy()
        bad_df = df.loc[~mask_good].drop(columns=["_normalized_phone"]).copy()

        # 1. Create new history tab with full original file (no helper column)
        tab_title = sanitize_sheet_title(filename)
        create_log_tab(
            service,
            sheet_id,
            tab_title,
            df.drop(columns=["_normalized_phone"])
        )

        # 2. Log summary into permanent Results tab
        log_result_to_sheet(
            service,
            sheet_id,
            filename,
            len(good_df),
            len(bad_df),
            len(df),
            tab_title
        )

        # 3. Save temporary CSV files for download – unique tokens so Good/Bad never mix
        good_token = str(uuid.uuid4())
        bad_token = str(uuid.uuid4())
        good_path = os.path.join("temp_downloads", f"good_{good_token}.csv")
        bad_path = os.path.join("temp_downloads", f"bad_{bad_token}.csv")

        good_df.to_csv(good_path, index=False)
        bad_df.to_csv(bad_path, index=False)

        # Register tokens → paths (in-memory + session for convenience)
        _download_files[good_token] = good_path
        _download_files[bad_token] = bad_path
        session["good_token"] = good_token
        session["bad_token"] = bad_token

        return jsonify({
            "success": True,
            "good_count": len(good_df),
            "bad_count": len(bad_df),
            "total": len(df),
            "good_download": url_for("download", kind="good", token=good_token),
            "bad_download": url_for("download", kind="bad", token=bad_token)
        })

    except HttpError as e:
        return jsonify({"success": False, "error": f"Google Sheets API error: {e}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/download/<kind>/<token>")
@login_required
def download(kind, token):
    """Download only the requested kind (good or bad). Token guarantees isolation."""
    if kind not in ("good", "bad"):
        return "Invalid download type", 400

    # Prefer the token map (most reliable); fall back to session if needed
    file_path = _download_files.get(token)
    if not file_path:
        # Legacy fallback for older session-based links
        file_path = session.get(f"{kind}_file")

    if not file_path or not os.path.exists(file_path):
        flash("No data available for this download. Please process a file first.", "error")
        return redirect(url_for("dashboard"))

    # Safety: make sure the token matches the expected kind prefix
    basename = os.path.basename(file_path)
    if kind == "good" and not basename.startswith("good_"):
        flash("Download mismatch detected. Please re-process the file.", "error")
        return redirect(url_for("dashboard"))
    if kind == "bad" and not basename.startswith("bad_"):
        flash("Download mismatch detected. Please re-process the file.", "error")
        return redirect(url_for("dashboard"))

    filename = f"{kind}_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(
        file_path,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )


# Keep a simple legacy route so old bookmarks still work (uses last session tokens)
@app.route("/download/<kind>")
@login_required
def download_legacy(kind):
    if kind not in ("good", "bad"):
        return "Invalid", 400
    token = session.get(f"{kind}_token")
    if token:
        return redirect(url_for("download", kind=kind, token=token))
    flash("No data available. Please process a file first.", "error")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
