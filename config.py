import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "cle_secrete_degustation_vin_2026")
PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
DB_ARCHIVE_FOLDER = os.path.join(BASE_DIR, "static", "db")
DB_NAME = os.path.join(BASE_DIR, "vin.db")