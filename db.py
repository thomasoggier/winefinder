import os
import random
import sqlite3
from datetime import datetime
from flask import current_app, request
from werkzeug.utils import secure_filename
import config


def get_db():
    conn = sqlite3.connect(config.DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                votes_submitted INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                phase TEXT DEFAULT 'TASTING', -- TASTING, BLIND_STEP1, BLIND_STEP2, VOTING, RESULTS
                results_reveal TEXT DEFAULT 'all', -- bottom_to_top_3, all
                person_a_id INTEGER,
                person_b_id INTEGER
            );
            INSERT OR IGNORE INTO game_state (id, phase, results_reveal) VALUES (1, 'TASTING', 'all');

            CREATE TABLE IF NOT EXISTS wines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                year TEXT,
                region TEXT,
                image_path TEXT,
                temp_code TEXT,
                carafe_number INTEGER
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                wine_id INTEGER,
                color TEXT,
                nose TEXT,
                palate TEXT,
                free_notes TEXT,
                note_mode TEXT DEFAULT 'guided',
                rating INTEGER,
                UNIQUE(user_id, wine_id)
            );
            CREATE TABLE IF NOT EXISTS votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                carafe_number INTEGER,
                guessed_wine_id INTEGER,
                UNIQUE(user_id, carafe_number)
            );
        ''')
        user_cols = [row['name'] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
        if 'votes_submitted' not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN votes_submitted INTEGER DEFAULT 0")
            conn.execute("UPDATE users SET votes_submitted = 1 WHERE id IN (SELECT DISTINCT user_id FROM votes)")

        note_cols = [row['name'] for row in conn.execute("PRAGMA table_info(notes)").fetchall()]
        if 'free_notes' not in note_cols:
            conn.execute("ALTER TABLE notes ADD COLUMN free_notes TEXT")
        if 'note_mode' not in note_cols:
            conn.execute("ALTER TABLE notes ADD COLUMN note_mode TEXT DEFAULT 'guided'")

        state_cols = [row['name'] for row in conn.execute("PRAGMA table_info(game_state)").fetchall()]
        if 'results_reveal' not in state_cols:
            conn.execute("ALTER TABLE game_state ADD COLUMN results_reveal TEXT DEFAULT 'all'")
        conn.commit()


def archive_and_reset_database():
    os.makedirs(config.DB_ARCHIVE_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archived_path = os.path.join(config.DB_ARCHIVE_FOLDER, f"vin_{timestamp}.db")

    if os.path.exists(config.DB_NAME):
        src_conn = sqlite3.connect(config.DB_NAME, timeout=10)
        dst_conn = sqlite3.connect(archived_path)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

    conn = sqlite3.connect(config.DB_NAME, timeout=10)
    try:
        conn.executescript('''
            PRAGMA foreign_keys = OFF;
            DROP TABLE IF EXISTS votes;
            DROP TABLE IF EXISTS notes;
            DROP TABLE IF EXISTS wines;
            DROP TABLE IF EXISTS game_state;
            DROP TABLE IF EXISTS users;
            PRAGMA foreign_keys = ON;
        ''')
        conn.commit()
    finally:
        conn.close()

    init_db()
    return archived_path


def delete_photo_file(rel_path):
    if rel_path:
        full_path = os.path.join(current_app.static_folder, rel_path)
        if os.path.isfile(full_path):
            try:
                os.remove(full_path)
            except OSError:
                pass


def save_uploaded_wine_photo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    raw_name = secure_filename(file_storage.filename)
    _, ext = os.path.splitext(raw_name)
    if not ext:
        ext = ".jpg"
    filename = f"{random.randint(1000, 9999)}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext.lower()}"
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    file_storage.save(os.path.join(config.UPLOAD_FOLDER, filename))
    return f"uploads/{filename}"


def extract_photo_from_request():
    for field_name in ('camera_photo', 'gallery_photo', 'photo'):
        f = request.files.get(field_name)
        if f and f.filename:
            return f
    return None


def are_wines_in_carafes(wines):
    if len(wines) < 2:
        return False
    carafe_nums = [w['carafe_number'] for w in wines if w['carafe_number'] is not None]
    return len(carafe_nums) == len(wines) and len(set(carafe_nums)) == len(wines)