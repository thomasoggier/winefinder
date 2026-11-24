import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "cle_secrete_degustation_vin_2026")
PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

DATA_DIR = os.environ.get("APP_DATA_DIR", BASE_DIR)
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(DATA_DIR, "static", "uploads"))
DB_ARCHIVE_FOLDER = os.environ.get("DB_ARCHIVE_FOLDER", os.path.join(DATA_DIR, "static", "db"))
DB_NAME = os.environ.get("DB_NAME", os.path.join(DATA_DIR, "vin.db"))