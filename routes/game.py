import io
import random
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from db import get_db
from routes.auth import login_required
from services.results import inspect_user_votes, get_pending_voters, compute_results_data
from services.pdf_export import build_results_pdf_bytes

game_bp = Blueprint("game", __name__)


@game_bp.route('/')
@login_required
def index():
    db = get_db()
    state = db.execute('SELECT * FROM game_state WHERE id = 1').fetchone()
    phase = state['phase']
    uid = session['user_id']

    if phase == 'TASTING':
        return redirect(url_for('game.tasting'))
    elif phase == 'BLIND_STEP1':
        if uid == state['person_a_id']:
            return redirect(url_for('game.blind_task'))
        person_a = db.execute('SELECT username FROM users WHERE id = ?', (state['person_a_id'],)).fetchone()
        name_a = person_a['username'] if person_a else "la Personne A"
        return render_template('base.html', message=f"{name_a} est en train de remplir les carafes (Étape 1/2). Patientez un instant...")
    elif phase == 'BLIND_STEP2':
        if uid == state['person_b_id']:
            return redirect(url_for('game.blind_task'))
        person_b = db.execute('SELECT username FROM users WHERE id = ?', (state['person_b_id'],)).fetchone()
        name_b = person_b['username'] if person_b else "la Personne B"
        return render_template('base.html', message=f"{name_b} est en train de numéroter les carafes (Étape 2/2). Bientôt prêt !")
    elif phase == 'VOTING':
        return redirect(url_for('game.voting'))
    else:
        return redirect(url_for('game.results'))


@game_bp.route('/share')
@login_required
def share():
    default_url = request.host_url.rstrip('/')
    return render_template('share.html', default_url=default_url)


@game_bp.route('/blind-task', methods=['GET', 'POST'])
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
            return redirect(url_for('game.index'))

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
            return redirect(url_for('game.voting'))

        wines = list(db.execute('SELECT * FROM wines').fetchall())
        random.shuffle(wines)
        return render_template('blind_task.html', role='B', wines=wines)

    return redirect(url_for('game.index'))


@game_bp.route('/tasting', methods=['GET', 'POST'])
@login_required
def tasting():
    db = get_db()
    phase = db.execute('SELECT phase FROM game_state WHERE id = 1').fetchone()['phase']
    if phase != 'TASTING':
        return redirect(url_for('game.index'))

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


@game_bp.route('/api/save_note', methods=['POST'])
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


@game_bp.route('/voting', methods=['GET', 'POST'])
@login_required
def voting():
    db = get_db()
    phase = db.execute('SELECT phase FROM game_state WHERE id = 1').fetchone()['phase']
    if phase != 'VOTING':
        return redirect(url_for('game.index'))

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
            return redirect(url_for('game.voting'))

    user_row = db.execute('SELECT id, username, votes_submitted FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    user_votes_rows = db.execute('SELECT * FROM votes WHERE user_id = ?', (session['user_id'],)).fetchall()
    expected_carafes = set(carafes)
    expected_wine_ids = {w['id'] for w in wines if w['carafe_number'] is not None}
    is_vote_validated, _ = inspect_user_votes(user_row, user_votes_rows, expected_carafes, expected_wine_ids)

    pending_voters, _ = get_pending_voters(db)
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


@game_bp.route('/api/save_vote', methods=['POST'])
@login_required
def api_save_vote():
    data = request.get_json(silent=True) or {}
    wine_id = data.get('wine_id')
    carafe = data.get('carafe')
    if not wine_id:
        return jsonify({'status': 'error', 'message': 'wine_id manquant'}), 400

    db = get_db()
    state = db.execute('SELECT phase FROM game_state WHERE id = 1').fetchone()
    if not state or state['phase'] != 'VOTING':
        return jsonify({'status': 'error', 'message': 'Phase de vote fermée'}), 400

    user_row = db.execute('SELECT votes_submitted FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    if user_row and user_row['votes_submitted']:
        return jsonify({'status': 'locked'}), 200

    wine_id = int(wine_id)
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


@game_bp.route('/results')
@login_required
def results():
    db = get_db()
    state = db.execute('SELECT * FROM game_state WHERE id = 1').fetchone()
    if state['phase'] != 'RESULTS':
        return redirect(url_for('game.index'))

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


@game_bp.route('/results/pdf')
@login_required
def export_results_pdf():
    db = get_db()
    state = db.execute('SELECT * FROM game_state WHERE id = 1').fetchone()
    results_reveal = state['results_reveal'] or 'all'

    if state['phase'] != 'RESULTS' or results_reveal != 'all':
        flash("L'export PDF n'est disponible qu'une fois la partie terminée et tous les résultats révélés.", "error")
        return redirect(url_for('game.index'))

    wines, leaderboard, carafe_details, wine_stats, stats, _ = compute_results_data(db)
    pdf_bytes = build_results_pdf_bytes(wines, leaderboard, carafe_details, wine_stats, stats)
    filename = f"resultats_degustation_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )