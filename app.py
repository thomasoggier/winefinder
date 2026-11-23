import io
import os
import random
import string
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static')
)
app.secret_key = 'cle_secrete_degustation_vin_2026'
app.permanent_session_lifetime = timedelta(hours=24)

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
DB_NAME = os.path.join(BASE_DIR, 'vin.db')


def get_db():
    conn = sqlite3.connect(DB_NAME)
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


def are_wines_in_carafes(wines):
    if len(wines) < 2:
        return False
    carafe_nums = [w['carafe_number'] for w in wines if w['carafe_number'] is not None]
    return len(carafe_nums) == len(wines) and len(set(carafe_nums)) == len(wines)


def inspect_user_votes(user_row, u_votes, expected_carafes, expected_wine_ids):
    expected_count = len(expected_carafes)
    filtered = [
        v for v in u_votes
        if v['carafe_number'] in expected_carafes and v['guessed_wine_id'] in expected_wine_ids
    ]
    valid_carafes = {v['carafe_number'] for v in filtered}
    valid_guessed_wines = {v['guessed_wine_id'] for v in filtered}
    saved_count = len(valid_carafes)

    has_complete_unique_votes = (
        expected_count > 0
        and len(filtered) == expected_count
        and len(valid_carafes) == expected_count
        and len(valid_guessed_wines) == expected_count
    )
    is_validated = bool(user_row['votes_submitted']) and has_complete_unique_votes
    return is_validated, saved_count


def get_pending_voters(db):
    users = db.execute('SELECT id, username, votes_submitted FROM users ORDER BY username').fetchall()
    wines = db.execute('SELECT id, carafe_number FROM wines WHERE carafe_number IS NOT NULL').fetchall()
    expected_carafes = {w['carafe_number'] for w in wines}
    expected_wine_ids = {w['id'] for w in wines}
    expected_count = len(expected_carafes)

    if not users or expected_count == 0:
        return [], expected_count

    votes = db.execute('SELECT user_id, carafe_number, guessed_wine_id FROM votes').fetchall()
    votes_by_user = {}
    for v in votes:
        votes_by_user.setdefault(v['user_id'], []).append(v)

    pending = []
    for u in users:
        u_votes = votes_by_user.get(u['id'], [])
        is_validated, saved_count = inspect_user_votes(u, u_votes, expected_carafes, expected_wine_ids)
        if not is_validated:
            pending.append({
                'id': u['id'],
                'username': u['username'],
                'voted_count': saved_count,
                'expected_count': expected_count
            })

    return pending, expected_count


def compute_results_data(db, uid=None):
    wines = db.execute('SELECT * FROM wines WHERE carafe_number IS NOT NULL ORDER BY carafe_number').fetchall()
    users = db.execute('SELECT * FROM users ORDER BY username').fetchall()
    votes = db.execute('SELECT * FROM votes').fetchall()
    notes = db.execute('SELECT * FROM notes').fetchall()

    wine_by_id = {w['id']: w for w in wines}
    votes_lookup = {(v['user_id'], v['carafe_number']): v['guessed_wine_id'] for v in votes}
    user_votes_by_wine = {
        v['guessed_wine_id']: v['carafe_number']
        for v in votes
        if uid is not None and v['user_id'] == uid and v['guessed_wine_id']
    }
    my_notes_by_wine = {
        n['wine_id']: dict(n)
        for n in notes
        if uid is not None and n['user_id'] == uid
    }

    total_players = len(users)
    total_wines = len(wines)

    correct_counts_by_carafe = {}
    weight_by_carafe = {}
    for w in wines:
        c_num = w['carafe_number']
        c_count = sum(1 for u in users if votes_lookup.get((u['id'], c_num)) == w['id'])
        correct_counts_by_carafe[c_num] = c_count
        if total_players > 0 and c_count > 0:
            weight_by_carafe[c_num] = round(total_players / c_count, 2)
        else:
            weight_by_carafe[c_num] = 0.0

    leaderboard = []
    for u in users:
        score = 0
        weighted_score = 0.0
        for w in wines:
            c_num = w['carafe_number']
            if votes_lookup.get((u['id'], c_num)) == w['id']:
                score += 1
                weighted_score += weight_by_carafe[c_num]
        leaderboard.append({
            'user_id': u['id'],
            'username': u['username'],
            'score': score,
            'weighted_score': round(weighted_score, 2),
            'total': total_wines,
            'is_me': (uid is not None and u['id'] == uid)
        })

    leaderboard.sort(key=lambda x: (-x['score'], -x['weighted_score'], x['username'].lower()))
    for idx, entry in enumerate(leaderboard, start=1):
        entry['rank'] = idx

    carafe_details = []
    wine_stats = []
    my_notes_review = []

    for w in wines:
        carafe_num = w['carafe_number']
        correct_count = correct_counts_by_carafe[carafe_num]
        weight = weight_by_carafe[carafe_num]
        success_rate = round((correct_count / total_players) * 100) if total_players > 0 else 0

        wine_notes = [n['rating'] for n in notes if n['wine_id'] == w['id'] and n['rating'] is not None]
        avg_rating = round(sum(wine_notes) / len(wine_notes), 1) if wine_notes else None

        player_guesses = []
        for u in users:
            guessed_id = votes_lookup.get((u['id'], carafe_num))
            guessed_wine = wine_by_id.get(guessed_id)
            if guessed_wine:
                is_correct = (guessed_id == w['id'])
                player_guesses.append({
                    'username': u['username'],
                    'guessed_name': guessed_wine['name'],
                    'guessed_year': guessed_wine['year'],
                    'status': 'correct' if is_correct else 'wrong',
                    'is_me': (u['id'] == uid)
                })
            else:
                player_guesses.append({
                    'username': u['username'],
                    'guessed_name': 'Aucun vote',
                    'guessed_year': '',
                    'status': 'missing',
                    'is_me': (u['id'] == uid)
                })

        carafe_details.append({
            'carafe_number': carafe_num,
            'actual_wine': w,
            'guesses': player_guesses,
            'correct_count': correct_count,
            'total_players': total_players,
            'success_rate': success_rate,
            'weight': weight
        })

        wine_stats.append({
            'carafe_number': carafe_num,
            'name': w['name'],
            'year': w['year'],
            'correct_count': correct_count,
            'total_players': total_players,
            'success_rate': success_rate,
            'weight': weight,
            'avg_rating': avg_rating
        })

        guessed_carafe_for_this_wine = user_votes_by_wine.get(w['id'])
        my_notes_review.append({
            'wine': w,
            'note': my_notes_by_wine.get(w['id'], {}),
            'guessed_carafe': guessed_carafe_for_this_wine,
            'found_it': (guessed_carafe_for_this_wine == carafe_num)
        })

    hardest_wine = min(wine_stats, key=lambda x: (x['correct_count'], -x['carafe_number'])) if wine_stats else None
    easiest_wine = max(wine_stats, key=lambda x: (x['correct_count'], -x['carafe_number'])) if wine_stats else None

    total_possible_votes = total_players * total_wines
    total_correct_votes = sum(x['correct_count'] for x in wine_stats)
    global_success_rate = round((total_correct_votes / total_possible_votes) * 100) if total_possible_votes > 0 else 0

    stats = {
        'total_players': total_players,
        'total_wines': total_wines,
        'global_success_rate': global_success_rate,
        'total_correct_votes': total_correct_votes,
        'total_possible_votes': total_possible_votes,
        'hardest_wine': hardest_wine,
        'easiest_wine': easiest_wine
    }

    return wines, leaderboard, carafe_details, wine_stats, stats, my_notes_review


def _pdf_safe_text(text):
    if text is None:
        return ""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def build_results_pdf_bytes(wines, leaderboard, carafe_details, wine_stats, stats):
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    if HAS_FPDF:
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        pdf.set_fill_color(76, 5, 25)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 12, _pdf_safe_text("Blind Wine - Résultats Globaux"), ln=True, align="C", fill=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 6, _pdf_safe_text(f"Exporté le {date_str}"), ln=True, align="C")
        pdf.ln(3)

        pdf.set_text_color(76, 5, 25)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe_text("1. Statistiques de la soirée"), ln=True)
        pdf.set_text_color(30, 30, 30)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _pdf_safe_text(
            f"Participants : {stats['total_players']}   |   Carafes : {stats['total_wines']}   |   "
            f"Réussite globale : {stats['global_success_rate']}% ({stats['total_correct_votes']}/{stats['total_possible_votes']})"
        ), ln=True)
        if stats['hardest_wine']:
            hw = stats['hardest_wine']
            pdf.cell(0, 6, _pdf_safe_text(
                f"Vin le plus piégeux : Carafe N°{hw['carafe_number']} - {hw['name']} ({hw['correct_count']}/{hw['total_players']} trouvés)"
            ), ln=True)
        if stats['easiest_wine']:
            ew = stats['easiest_wine']
            pdf.cell(0, 6, _pdf_safe_text(
                f"Vin le plus reconnu : Carafe N°{ew['carafe_number']} - {ew['name']} ({ew['correct_count']}/{ew['total_players']} trouvés)"
            ), ln=True)
        pdf.ln(4)

        pdf.set_text_color(76, 5, 25)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe_text("2. Classement des nez"), ln=True)

        pdf.set_fill_color(245, 240, 240)
        pdf.set_text_color(40, 40, 40)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(20, 8, _pdf_safe_text("Rang"), border=1, align="C", fill=True)
        pdf.cell(85, 8, _pdf_safe_text("Joueur"), border=1, fill=True)
        pdf.cell(40, 8, _pdf_safe_text("Vins trouvés"), border=1, align="C", fill=True)
        pdf.cell(45, 8, _pdf_safe_text("Score pondéré"), border=1, align="C", fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 10)
        for p in leaderboard:
            rank_label = "1er" if p['rank'] == 1 else f"{p['rank']}e"
            pdf.cell(20, 7, _pdf_safe_text(rank_label), border=1, align="C")
            pdf.cell(85, 7, _pdf_safe_text(p['username']), border=1)
            pdf.cell(40, 7, _pdf_safe_text(f"{p['score']} / {p['total']}"), border=1, align="C")
            pdf.cell(45, 7, _pdf_safe_text(f"{p['weighted_score']} pts"), border=1, align="C")
            pdf.ln()
        pdf.ln(4)

        pdf.set_text_color(76, 5, 25)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe_text("3. La vérité sur les carafes"), ln=True)

        pdf.set_fill_color(245, 240, 240)
        pdf.set_text_color(40, 40, 40)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(22, 7, _pdf_safe_text("Carafe"), border=1, align="C", fill=True)
        pdf.cell(88, 7, _pdf_safe_text("Vin (Millésime / Région)"), border=1, fill=True)
        pdf.cell(28, 7, _pdf_safe_text("Trouvé"), border=1, align="C", fill=True)
        pdf.cell(26, 7, _pdf_safe_text("Note moy."), border=1, align="C", fill=True)
        pdf.cell(26, 7, _pdf_safe_text("Poids"), border=1, align="C", fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 9)
        for ws in wine_stats:
            w_obj = next((x for x in wines if x['carafe_number'] == ws['carafe_number']), None)
            extra = []
            if ws['year']:
                extra.append(str(ws['year']))
            if w_obj and w_obj['region']:
                extra.append(str(w_obj['region']))
            label = ws['name'] + (f" ({' - '.join(extra)})" if extra else "")
            avg_str = f"{ws['avg_rating']}/10" if ws['avg_rating'] is not None else "-"
            pdf.cell(22, 7, _pdf_safe_text(f"N°{ws['carafe_number']}"), border=1, align="C")
            pdf.cell(88, 7, _pdf_safe_text(label[:52]), border=1)
            pdf.cell(28, 7, _pdf_safe_text(f"{ws['correct_count']}/{ws['total_players']} ({ws['success_rate']}%)"), border=1, align="C")
            pdf.cell(26, 7, _pdf_safe_text(avg_str), border=1, align="C")
            pdf.cell(26, 7, _pdf_safe_text(f"{ws['weight']} pts"), border=1, align="C")
            pdf.ln()
        pdf.ln(5)

        pdf.set_text_color(76, 5, 25)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _pdf_safe_text("4. Détail des pronostics par carafe"), ln=True)

        for item in carafe_details:
            w = item['actual_wine']
            title = f"Carafe N°{item['carafe_number']} : {w['name']}" + (f" ({w['year']})" if w['year'] else "")
            pdf.set_fill_color(45, 45, 45)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 7, _pdf_safe_text(f"  {title}  -  Poids : {item['weight']} pts"), ln=True, fill=True)

            pdf.set_text_color(30, 30, 30)
            pdf.set_font("Helvetica", "", 9)
            for g in item['guesses']:
                guess_label = g['guessed_name'] + (f" ({g['guessed_year']})" if g['guessed_year'] else "")
                status_label = "Juste" if g['status'] == 'correct' else ("Faux" if g['status'] == 'wrong' else "Sans vote")
                pdf.cell(45, 6, _pdf_safe_text(g['username']), border=1)
                pdf.cell(115, 6, _pdf_safe_text(guess_label[:65]), border=1)
                pdf.cell(30, 6, _pdf_safe_text(status_label), border=1, align="C")
                pdf.ln()
            pdf.ln(2)

        raw = pdf.output()
        return bytes(raw) if isinstance(raw, (bytes, bytearray)) else raw.encode("latin-1")

    lines = [
        f"BLIND WINE - RESULTATS GLOBAUX ({date_str})",
        "=" * 60,
        f"Participants: {stats['total_players']} | Carafes: {stats['total_wines']} | Reussite: {stats['global_success_rate']}%",
        "",
        "CLASSEMENT GENERAL :",
    ]
    for p in leaderboard:
        lines.append(f"  #{p['rank']} {p['username']} : {p['score']}/{p['total']} ({p['weighted_score']} pts)")
    lines.append("")
    lines.append("VERITE SUR LES CARAFES :")
    for ws in wine_stats:
        lines.append(f"  Carafe N°{ws['carafe_number']} -> {ws['name']} ({ws['correct_count']}/{ws['total_players']}, poids {ws['weight']} pts)")
    lines.append("")
    lines.append("DETAIL PAR CARAFE :")
    for item in carafe_details:
        lines.append(f"  [Carafe N°{item['carafe_number']} - {item['actual_wine']['name']}]")
        for g in item['guesses']:
            st = "JUSTE" if g['status'] == 'correct' else ("FAUX" if g['status'] == 'wrong' else "SANS VOTE")
            lines.append(f"    - {g['username']} : {g['guessed_name']} [{st}]")

    def _esc(s):
        return _pdf_safe_text(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    pages_lines = [lines[i:i + 48] for i in range(0, len(lines), 48)] or [["Aucun resultat"]]
    objects = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    page_ids = []
    next_id = 4
    page_objs = []
    for plines in pages_lines:
        content_ops = ["BT", "/F1 10 Tf", "40 800 Td", "14 TL"]
        for ln in plines:
            content_ops.append(f"({_esc(ln)}) Tj T*")
        content_ops.append("ET")
        stream = "\n".join(content_ops).encode("latin-1", "replace")
        p_id = next_id
        c_id = next_id + 1
        next_id += 2
        page_ids.append(p_id)
        page_objs.append(
            f"{p_id} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {c_id} 0 R >> endobj\n".encode("ascii")
        )
        page_objs.append(
            f"{c_id} 0 obj << /Length {len(stream)} >> stream\n".encode("ascii") + stream + b"\nendstream endobj\n"
        )

    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"2 0 obj << /Type /Pages /Kids [{kids_str}] /Count {len(page_ids)} >> endobj\n".encode("ascii"))
    objects.append(b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
    objects.extend(page_objs)

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(buf.tell())
        buf.write(obj)
    xref_pos = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buf.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        buf.write(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.write(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return buf.getvalue()


@app.before_request
def make_session_permanent():
    session.permanent = True


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            flash("Accès réservé à l'administrateur.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


@app.route('/')
@login_required
def index():
    db = get_db()
    state = db.execute('SELECT * FROM game_state WHERE id = 1').fetchone()
    phase = state['phase']
    uid = session['user_id']

    if phase == 'TASTING':
        return redirect(url_for('tasting'))
    elif phase == 'BLIND_STEP1':
        if uid == state['person_a_id']:
            return redirect(url_for('blind_task'))
        person_a = db.execute('SELECT username FROM users WHERE id = ?', (state['person_a_id'],)).fetchone()
        name_a = person_a['username'] if person_a else "la Personne A"
        return render_template('base.html', message=f"{name_a} est en train de remplir les carafes (Étape 1/2). Patientez un instant...")
    elif phase == 'BLIND_STEP2':
        if uid == state['person_b_id']:
            return redirect(url_for('blind_task'))
        person_b = db.execute('SELECT username FROM users WHERE id = ?', (state['person_b_id'],)).fetchone()
        name_b = person_b['username'] if person_b else "la Personne B"
        return render_template('base.html', message=f"{name_b} est en train de numéroter les carafes (Étape 2/2). Bientôt prêt !")
    elif phase == 'VOTING':
        return redirect(url_for('voting'))
    else:
        return redirect(url_for('results'))


@app.route('/share')
@login_required
def share():
    default_url = request.host_url.rstrip('/')
    return render_template('share.html', default_url=default_url)


@app.route('/blind-task', methods=['GET', 'POST'])
@login_required
def blind_task():
    db = get_db()
    state = db.execute('SELECT * FROM game_state WHERE id = 1').fetchone()
    phase = state['phase']
    uid = session['user_id']

    if phase == 'BLIND_STEP1' and uid == state['person_a_id']:
        if request.method == 'POST' and request.form.get('action') == 'finish_step1':
            wines = db.execute('SELECT id FROM wines').fetchall()
            numbers = list(range(1, len(wines) + 1))
            random.shuffle(numbers)
            for w, num in zip(wines, numbers):
                db.execute('UPDATE wines SET carafe_number = ? WHERE id = ?', (num, w['id']))
            db.execute("UPDATE game_state SET phase = 'BLIND_STEP2' WHERE id = 1")
            db.commit()
            flash("Merci ! Le relais a été passé automatiquement à la Personne B.", "success")
            return redirect(url_for('index'))

        wines = db.execute('SELECT * FROM wines').fetchall()
        person_b = db.execute('SELECT username FROM users WHERE id = ?', (state['person_b_id'],)).fetchone()
        return render_template(
            'blind_task.html',
            role='A',
            wines=wines,
            next_person=person_b['username'] if person_b else 'Personne B'
        )

    elif phase == 'BLIND_STEP2' and uid == state['person_b_id']:
        if request.method == 'POST' and request.form.get('action') == 'finish_step2':
            db.execute("UPDATE wines SET temp_code = NULL")
            db.execute("UPDATE game_state SET phase = 'VOTING' WHERE id = 1")
            db.commit()
            flash("Carafes verrouillées ! Les votes à l'aveugle sont ouverts pour tout le monde.", "success")
            return redirect(url_for('voting'))

        wines = list(db.execute('SELECT * FROM wines').fetchall())
        random.shuffle(wines)
        return render_template('blind_task.html', role='B', wines=wines)

    return redirect(url_for('index'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        action = request.form.get('action')
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        db = get_db()

        if action == 'register':
            if not username or not password:
                flash("Veuillez renseigner un pseudo et un mot de passe.", "error")
            else:
                existing = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
                if existing:
                    flash("Ce nom d'utilisateur existe déjà.", "error")
                else:
                    user_count = db.execute('SELECT COUNT(*) as c FROM users').fetchone()['c']
                    is_admin = 1 if user_count == 0 else 0
                    hashed = generate_password_hash(password)
                    cur = db.execute(
                        'INSERT INTO users (username, password, is_admin, votes_submitted) VALUES (?, ?, ?, 0)',
                        (username, hashed, is_admin)
                    )
                    db.commit()
                    session['user_id'] = cur.lastrowid
                    session['username'] = username
                    session['is_admin'] = is_admin
                    return redirect(url_for('index'))
        else:
            user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['is_admin'] = user['is_admin']
                return redirect(url_for('index'))
            flash("Identifiants incorrects.", "error")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/tasting', methods=['GET', 'POST'])
@login_required
def tasting():
    db = get_db()
    phase = db.execute('SELECT phase FROM game_state WHERE id = 1').fetchone()['phase']
    if phase != 'TASTING':
        return redirect(url_for('index'))

    if request.method == 'POST':
        wine_id = request.form.get('wine_id')
        color = request.form.get('color', '')
        nose = request.form.get('nose', '')
        palate = request.form.get('palate', '')
        free_notes = request.form.get('free_notes', '')
        note_mode = request.form.get('note_mode', 'guided')
        rating = request.form.get('rating', 7)
        db.execute('''
            INSERT INTO notes (user_id, wine_id, color, nose, palate, free_notes, note_mode, rating)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, wine_id) DO UPDATE SET
                color=excluded.color,
                nose=excluded.nose,
                palate=excluded.palate,
                free_notes=excluded.free_notes,
                note_mode=excluded.note_mode,
                rating=excluded.rating
        ''', (session['user_id'], wine_id, color, nose, palate, free_notes, note_mode, rating))
        db.commit()
        flash("Notes enregistrées !", "success")

    wines = db.execute('SELECT * FROM wines').fetchall()
    notes_rows = db.execute('SELECT * FROM notes WHERE user_id = ?', (session['user_id'],)).fetchall()
    notes = {n['wine_id']: dict(n) for n in notes_rows}
    return render_template('tasting.html', wines=wines, notes=notes)


@app.route('/api/save_note', methods=['POST'])
@login_required
def api_save_note():
    data = request.get_json(silent=True) or {}
    wine_id = data.get('wine_id')
    if not wine_id:
        return jsonify({'status': 'error', 'message': 'wine_id manquant'}), 400

    db = get_db()
    existing = db.execute(
        'SELECT * FROM notes WHERE user_id = ? AND wine_id = ?',
        (session['user_id'], wine_id)
    ).fetchone()

    color = data['color'] if 'color' in data else (existing['color'] if existing else '')
    nose = data['nose'] if 'nose' in data else (existing['nose'] if existing else '')
    palate = data['palate'] if 'palate' in data else (existing['palate'] if existing else '')
    free_notes = data['free_notes'] if 'free_notes' in data else (existing['free_notes'] if existing else '')
    note_mode = data['note_mode'] if 'note_mode' in data else (existing['note_mode'] if existing else 'guided')
    rating = data['rating'] if 'rating' in data else (existing['rating'] if existing else 7)

    db.execute('''
        INSERT INTO notes (user_id, wine_id, color, nose, palate, free_notes, note_mode, rating)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, wine_id) DO UPDATE SET
            color=excluded.color,
            nose=excluded.nose,
            palate=excluded.palate,
            free_notes=excluded.free_notes,
            note_mode=excluded.note_mode,
            rating=excluded.rating
    ''', (session['user_id'], wine_id, color, nose, palate, free_notes, note_mode, rating))
    db.commit()
    return jsonify({'status': 'ok'})


@app.route('/voting', methods=['GET', 'POST'])
@login_required
def voting():
    db = get_db()
    phase = db.execute('SELECT phase FROM game_state WHERE id = 1').fetchone()['phase']
    if phase != 'VOTING':
        return redirect(url_for('index'))

    wines = db.execute('SELECT * FROM wines').fetchall()
    carafes = sorted([w['carafe_number'] for w in wines if w['carafe_number'] is not None])

    validation_errors = []
    error_wine_ids = set()
    error_carafes = set()
    submitted_wine_to_carafe = None

    if request.method == 'POST':
        assignments = {}
        missing_wines = []

        for w in wines:
            c_val = (request.form.get(f"wine_{w['id']}") or '').strip()
            if c_val:
                c_num = int(c_val)
                assignments[w['id']] = c_num
            else:
                missing_wines.append(w)

        submitted_wine_to_carafe = dict(assignments)

        carafe_to_wines = {}
        for w in wines:
            c_num = assignments.get(w['id'])
            if c_num is not None:
                carafe_to_wines.setdefault(c_num, []).append(w)

        for c_num, w_list in carafe_to_wines.items():
            if len(w_list) > 1:
                error_carafes.add(c_num)
                wine_names = ", ".join(item['name'] for item in w_list)
                for item in w_list:
                    error_wine_ids.add(item['id'])
                validation_errors.append(
                    f"Doublon sur la Carafe N°{c_num} : assignée à plusieurs vins ({wine_names})."
                )

        if missing_wines:
            for w in missing_wines:
                error_wine_ids.add(w['id'])
            missing_names = ", ".join(w['name'] for w in missing_wines)
            validation_errors.append(
                f"Carafe manquante pour : {missing_names}."
            )

        if not validation_errors:
            db.execute('DELETE FROM votes WHERE user_id = ?', (session['user_id'],))
            for wine_id, carafe_num in assignments.items():
                db.execute('''
                    INSERT INTO votes (user_id, carafe_number, guessed_wine_id)
                    VALUES (?, ?, ?)
                ''', (session['user_id'], carafe_num, wine_id))
            db.execute('UPDATE users SET votes_submitted = 1 WHERE id = ?', (session['user_id'],))
            db.commit()
            flash("Vos assignations de carafes sont enregistrées et validées !", "success")
            return redirect(url_for('voting'))

    user_row = db.execute('SELECT id, username, votes_submitted FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    user_votes_rows = db.execute('SELECT * FROM votes WHERE user_id = ?', (session['user_id'],)).fetchall()
    expected_carafes = set(carafes)
    expected_wine_ids = {w['id'] for w in wines if w['carafe_number'] is not None}
    is_vote_validated, _ = inspect_user_votes(user_row, user_votes_rows, expected_carafes, expected_wine_ids)

    pending_voters, expected_votes_count = get_pending_voters(db)
    all_users = db.execute('SELECT id FROM users').fetchall()
    total_players = len(all_users)
    validated_players_count = max(0, total_players - len(pending_voters))

    notes_rows = db.execute('SELECT * FROM notes WHERE user_id = ?', (session['user_id'],)).fetchall()
    notes_by_wine = {n['wine_id']: dict(n) for n in notes_rows}

    if submitted_wine_to_carafe is not None:
        wine_to_carafe = submitted_wine_to_carafe
    else:
        wine_to_carafe = {v['guessed_wine_id']: v['carafe_number'] for v in user_votes_rows if v['guessed_wine_id']}

    cards = []
    for w in wines:
        assigned_c = wine_to_carafe.get(w['id'])
        has_error = (w['id'] in error_wine_ids) or (assigned_c in error_carafes)
        cards.append({
            'wine': w,
            'note': notes_by_wine.get(w['id'], {}),
            'assigned_carafe': assigned_c,
            'has_error': has_error,
            'is_missing': (submitted_wine_to_carafe is not None and assigned_c is None),
            'is_duplicate_carafe': (assigned_c in error_carafes)
        })

    return render_template(
        'voting.html',
        cards=cards,
        carafes=carafes,
        validation_errors=validation_errors,
        error_carafes=sorted(error_carafes),
        is_vote_validated=is_vote_validated,
        pending_voters=pending_voters,
        total_players=total_players,
        validated_players_count=validated_players_count
    )


@app.route('/api/save_vote', methods=['POST'])
@login_required
def api_save_vote():
    data = request.get_json(silent=True) or {}
    wine_id = data.get('wine_id')
    carafe = data.get('carafe')
    if not wine_id:
        return jsonify({'status': 'error', 'message': 'wine_id manquant'}), 400

    wine_id = int(wine_id)
    db = get_db()

    db.execute('DELETE FROM votes WHERE user_id = ? AND guessed_wine_id = ?', (session['user_id'], wine_id))
    if carafe:
        carafe_num = int(carafe)
        db.execute('DELETE FROM votes WHERE user_id = ? AND carafe_number = ?', (session['user_id'], carafe_num))
        db.execute('''
            INSERT INTO votes (user_id, carafe_number, guessed_wine_id)
            VALUES (?, ?, ?)
        ''', (session['user_id'], carafe_num, wine_id))

    db.commit()
    return jsonify({'status': 'ok'})


@app.route('/results')
@login_required
def results():
    db = get_db()
    state = db.execute('SELECT * FROM game_state WHERE id = 1').fetchone()
    if state['phase'] != 'RESULTS':
        return redirect(url_for('index'))

    results_reveal = state['results_reveal'] or 'all'
    top_3_hidden = (results_reveal == 'bottom_to_top_3')
    uid = session['user_id']

    wines, leaderboard, carafe_details, wine_stats, stats, my_notes_review = compute_results_data(db, uid=uid)
    total_players = stats['total_players']

    my_position = None
    leader = leaderboard[0] if leaderboard else None
    for idx, entry in enumerate(leaderboard, start=1):
        entry['is_top_3'] = (idx <= 3)
        entry['is_hidden_podium'] = (top_3_hidden and idx <= 3)
        if entry['is_me']:
            gap_score = (leader['score'] - entry['score']) if leader else 0
            gap_weighted = round((leader['weighted_score'] - entry['weighted_score']), 2) if leader else 0.0
            my_position = {
                'rank': idx,
                'is_top_3': (idx <= 3),
                'is_hidden_podium': (top_3_hidden and idx <= 3),
                'total_players': total_players,
                'score': entry['score'],
                'weighted_score': entry['weighted_score'],
                'total': entry['total'],
                'username': entry['username'],
                'gap_score': gap_score,
                'gap_weighted': gap_weighted
            }

    return render_template(
        'results.html',
        results_reveal=results_reveal,
        top_3_hidden=top_3_hidden,
        wines=wines,
        leaderboard=leaderboard,
        my_position=my_position,
        carafe_details=carafe_details,
        wine_stats=wine_stats,
        stats=stats,
        my_notes_review=my_notes_review
    )


@app.route('/results/pdf')
@login_required
def export_results_pdf():
    db = get_db()
    state = db.execute('SELECT * FROM game_state WHERE id = 1').fetchone()
    results_reveal = state['results_reveal'] or 'all'

    if state['phase'] != 'RESULTS' or results_reveal != 'all':
        flash("L'export PDF n'est disponible qu'une fois la partie terminée et tous les résultats révélés.", "error")
        return redirect(url_for('index'))

    wines, leaderboard, carafe_details, wine_stats, stats, _ = compute_results_data(db)
    pdf_bytes = build_results_pdf_bytes(wines, leaderboard, carafe_details, wine_stats, stats)
    filename = f"resultats_degustation_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


# --- ROUTES ADMINISTRATION ---

@app.route('/admin', methods=['GET', 'POST'])
@login_required
@admin_required
def admin():
    db = get_db()
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add_wine':
            current_phase = db.execute('SELECT phase FROM game_state WHERE id = 1').fetchone()['phase']
            if current_phase in ('VOTING', 'RESULTS'):
                flash("Impossible d'ajouter une bouteille : les votes ont déjà commencé.", "error")
            else:
                name = (request.form.get('name') or '').strip()
                year = (request.form.get('year') or '').strip()
                region = (request.form.get('region') or '').strip()
                file = request.files.get('photo')
                image_path = None
                if file and file.filename:
                    filename = secure_filename(f"{random.randint(1000,9999)}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_path = f"uploads/{filename}"
                if name:
                    db.execute(
                        'INSERT INTO wines (name, year, region, image_path) VALUES (?, ?, ?, ?)',
                        (name, year, region, image_path)
                    )
                    db.commit()
                    flash("Bouteille ajoutée à la dégustation !", "success")

        elif action == 'delete_wine':
            wine_id = request.form.get('wine_id')
            db.execute('DELETE FROM wines WHERE id = ?', (wine_id,))
            db.execute('DELETE FROM notes WHERE wine_id = ?', (wine_id,))
            db.execute('DELETE FROM votes WHERE guessed_wine_id = ?', (wine_id,))
            db.commit()

        elif action == 'delete_user':
            target_id = request.form.get('user_id')
            if target_id:
                target_id_int = int(target_id)
                target_user = db.execute('SELECT id, username, is_admin FROM users WHERE id = ?', (target_id_int,)).fetchone()
                if not target_user:
                    flash("Concurrent introuvable.", "error")
                elif target_user['id'] == session.get('user_id'):
                    flash("Vous ne pouvez pas supprimer votre propre compte connecté.", "error")
                else:
                    admin_count = db.execute('SELECT COUNT(*) as c FROM users WHERE is_admin = 1').fetchone()['c']
                    if target_user['is_admin'] and admin_count <= 1:
                        flash("Impossible de supprimer le dernier administrateur.", "error")
                    else:
                        db.execute('DELETE FROM votes WHERE user_id = ?', (target_id_int,))
                        db.execute('DELETE FROM notes WHERE user_id = ?', (target_id_int,))
                        db.execute(
                            'UPDATE game_state SET person_a_id = CASE WHEN person_a_id = ? THEN NULL ELSE person_a_id END, '
                            'person_b_id = CASE WHEN person_b_id = ? THEN NULL ELSE person_b_id END WHERE id = 1',
                            (target_id_int, target_id_int)
                        )
                        db.execute('DELETE FROM users WHERE id = ?', (target_id_int,))
                        db.commit()
                        flash(f"Concurrent « {target_user['username']} » supprimé.", "success")

        elif action == 'assign_roles':
            person_a_id = request.form.get('person_a_id')
            person_b_id = request.form.get('person_b_id')
            if not person_a_id or not person_b_id:
                flash("Veuillez sélectionner une Personne A et une Personne B.", "error")
            elif person_a_id == person_b_id:
                flash("La Personne A et la Personne B doivent être deux joueurs différents !", "error")
            else:
                db.execute(
                    'UPDATE game_state SET person_a_id = ?, person_b_id = ? WHERE id = 1',
                    (int(person_a_id), int(person_b_id))
                )
                db.commit()
                flash("Rôles Personne A et Personne B enregistrés !", "success")

        elif action == 'start_blind_step1':
            state = db.execute('SELECT * FROM game_state WHERE id = 1').fetchone()
            wines = db.execute('SELECT id FROM wines').fetchall()
            if len(wines) < 2:
                flash("Ajoutez au moins 2 vins avant de lancer la mise en carafe.", "error")
            elif not state['person_a_id'] or not state['person_b_id'] or state['person_a_id'] == state['person_b_id']:
                flash("Assignez deux joueurs distincts (Personne A et Personne B) avant de lancer l'Étape 1.", "error")
            else:
                codes = random.sample(
                    [f"CODE-{''.join(random.choices(string.ascii_uppercase, k=3))}" for _ in range(max(100, len(wines) * 10))],
                    len(wines)
                )
                for w, code in zip(wines, codes):
                    db.execute('UPDATE wines SET temp_code = ?, carafe_number = NULL WHERE id = ?', (code, w['id']))
                db.execute("UPDATE game_state SET phase = 'BLIND_STEP1' WHERE id = 1")
                db.commit()
                return redirect(url_for('index'))

        elif action == 'force_step2':
            wines = db.execute('SELECT id FROM wines').fetchall()
            if len(wines) < 2:
                flash("Ajoutez au moins 2 vins avant de passer à l'Étape 2.", "error")
            else:
                numbers = list(range(1, len(wines) + 1))
                random.shuffle(numbers)
                for w, num in zip(wines, numbers):
                    db.execute('UPDATE wines SET carafe_number = ? WHERE id = ?', (num, w['id']))
                db.execute("UPDATE game_state SET phase = 'BLIND_STEP2' WHERE id = 1")
                db.commit()

        elif action == 'force_voting':
            wines = db.execute('SELECT * FROM wines').fetchall()
            if not are_wines_in_carafes(wines):
                flash("Impossible de passer en mode vote : tous les vins n'ont pas encore été mis en carafe.", "error")
            else:
                db.execute("UPDATE wines SET temp_code = NULL")
                db.execute("UPDATE game_state SET phase = 'VOTING' WHERE id = 1")
                db.commit()
                flash("Retour en mode vote (phase VOTING) activé.", "success")

        elif action == 'unvalidate_user_votes':
            target_user_id = request.form.get('user_id')
            if target_user_id:
                u_row = db.execute('SELECT username FROM users WHERE id = ?', (int(target_user_id),)).fetchone()
                db.execute('UPDATE users SET votes_submitted = 0 WHERE id = ?', (int(target_user_id),))
                db.execute("UPDATE game_state SET phase = 'VOTING' WHERE id = 1")
                db.commit()
                pseudo = u_row['username'] if u_row else "ce joueur"
                flash(f"Validation retirée pour {pseudo} (ses votes restent enregistrés) : retour en mode vote.", "success")

        elif action in ('reveal_bottom_to_top3', 'reveal_top_3'):
            wines = db.execute('SELECT * FROM wines').fetchall()
            pending_voters, expected_count = get_pending_voters(db)
            if not are_wines_in_carafes(wines) or expected_count == 0:
                flash("Les vins ne sont pas tous mis en carafe : impossible d'afficher les résultats.", "error")
            elif pending_voters:
                names = ", ".join(
                    f"{p['username']} ({p['voted_count']}/{p['expected_count']})"
                    for p in pending_voters
                )
                flash(
                    f"Tout le monde n'a pas encore voté et validé tous ses choix ! En attente : {names}.",
                    "error"
                )
            else:
                reveal_mode = 'bottom_to_top_3' if action == 'reveal_bottom_to_top3' else 'all'
                db.execute(
                    "UPDATE game_state SET phase = 'RESULTS', results_reveal = ? WHERE id = 1",
                    (reveal_mode,)
                )
                db.commit()
                if reveal_mode == 'bottom_to_top_3':
                    flash("Tous les votes sont validés ! Résultats ouverts des derniers jusqu'au 4e (Top 3 secret).", "success")
                else:
                    flash("Tous les votes sont validés ! Le classement complet (Top 3 inclus) est révélé.", "success")

        elif action == 'reset_game':
            db.execute("DELETE FROM votes")
            db.execute("DELETE FROM notes")
            db.execute("DELETE FROM wines")
            db.execute("UPDATE users SET votes_submitted = 0")
            db.execute("UPDATE game_state SET phase = 'TASTING', results_reveal = 'all', person_a_id = NULL, person_b_id = NULL WHERE id = 1")
            db.commit()
            flash("Partie réinitialisée.", "success")

        return redirect(url_for('admin'))

    state = db.execute('SELECT * FROM game_state WHERE id = 1').fetchone()
    wines = db.execute('SELECT * FROM wines').fetchall()
    users = db.execute('SELECT * FROM users ORDER BY username').fetchall()
    users_map = {u['id']: u['username'] for u in users}

    can_add_wine = state['phase'] not in ('VOTING', 'RESULTS')
    has_enough_wines = len(wines) >= 2
    roles_ready = bool(
        state['person_a_id'] and state['person_b_id'] and state['person_a_id'] != state['person_b_id']
    )
    carafes_ready = are_wines_in_carafes(wines)

    can_start_step1 = has_enough_wines and roles_ready
    can_force_step2 = has_enough_wines
    can_force_voting = carafes_ready

    expected_carafes = {w['carafe_number'] for w in wines if w['carafe_number'] is not None}
    expected_wine_ids = {w['id'] for w in wines if w['carafe_number'] is not None}
    expected_votes_count = len(expected_carafes)

    all_votes = db.execute('SELECT user_id, carafe_number, guessed_wine_id FROM votes').fetchall()
    votes_by_user = {}
    for v in all_votes:
        votes_by_user.setdefault(v['user_id'], []).append(v)

    progress = []
    all_votes_validated = (len(users) > 0 and expected_votes_count > 0 and carafes_ready)
    for u in users:
        notes_count = db.execute('SELECT COUNT(*) as c FROM notes WHERE user_id = ?', (u['id'],)).fetchone()['c']
        u_votes = votes_by_user.get(u['id'], [])
        is_validated, saved_count = inspect_user_votes(u, u_votes, expected_carafes, expected_wine_ids)
        if not is_validated:
            all_votes_validated = False

        progress.append({
            'user_id': u['id'],
            'username': u['username'],
            'is_admin': u['is_admin'],
            'is_current_user': (u['id'] == session.get('user_id')),
            'notes_done': notes_count,
            'votes_done': saved_count,
            'expected_votes': expected_votes_count,
            'votes_validated': is_validated,
            'total_wines': len(wines)
        })

    can_reveal_results = carafes_ready and all_votes_validated
    can_export_pdf = (state['phase'] == 'RESULTS' and (state['results_reveal'] or 'all') == 'all')

    return render_template(
        'admin.html',
        state=state,
        phase=state['phase'],
        results_reveal=state['results_reveal'] or 'all',
        wines=wines,
        users=users,
        users_map=users_map,
        progress=progress,
        can_add_wine=can_add_wine,
        carafes_ready=carafes_ready,
        can_start_step1=can_start_step1,
        can_force_step2=can_force_step2,
        can_force_voting=can_force_voting,
        all_votes_validated=all_votes_validated,
        can_reveal_results=can_reveal_results,
        can_export_pdf=can_export_pdf
    )

@app.route('/admin/db')
@login_required
@admin_required
def admin_db_view():
    db = get_db()
    table_rows = db.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()

    tables = []
    for t in table_rows:
        t_name = t['name']
        cols = [c['name'] for c in db.execute(f"PRAGMA table_info({t_name})").fetchall()]
        rows = [dict(r) for r in db.execute(f"SELECT * FROM {t_name}").fetchall()]
        # Masquer le hash du mot de passe si souhaité
        if t_name == 'users' and 'password' in cols:
            cols = [c for c in cols if c != 'password']
            for r in rows:
                r.pop('password', None)
        tables.append({
            'name': t_name,
            'sql': t['sql'],
            'cols': cols,
            'rows': rows
        })

    return render_template('admin_db.html', tables=tables)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)