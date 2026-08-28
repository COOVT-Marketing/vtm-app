import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-insecure-key-change-me")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
    MASTER_SHEET_ID = os.getenv("MASTER_SHEET_ID")
    
    # Automatically switch to Render's secret mount path if it exists
    RENDER_SECRET_PATH = "/etc/secrets/service-account.json"
    if os.path.exists(RENDER_SECRET_PATH):
        GOOGLE_CREDENTIALS_PATH = RENDER_SECRET_PATH
    else:
        GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service-account.json")
        
    PHONE_COLUMN = os.getenv("PHONE_COLUMN", "Phone")
    UPLOAD_FOLDER = "uploads"
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # 32 MB
