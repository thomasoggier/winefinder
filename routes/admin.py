import os
import random
import string
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import config
from db import (
    get_db,
    archive_and_reset_database,
    delete_photo_file,
    save_uploaded_wine_photo,
    extract_photo_from_request,
    are_wines_in_carafes,
)
from routes.auth import login_required, admin_required
from services.results import inspect_user_votes, get_pending_voters

admin_bp = Blueprint("admin", __name__)


@admin_bp.route('/admin', methods=['GET', 'POST'])
@login_required
@admin_required
def admin():
    db = get_db()
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add_wine':
            current_phase = db.execute('SELECT phase FROM game_state WHERE id = 1').fetchone()['phase']
            wines_now = db.execute('SELECT * FROM wines').fetchall()
            if current_phase in ('BLIND_STEP1', 'BLIND_STEP2', 'VOTING', 'RESULTS') or are_wines_in_carafes(wines_now):
                flash("Impossible d'ajouter une bouteille : la mise en carafe a déjà commencé.", "error")
            else:
                name = (request.form.get('name') or '').strip()
                year = (request.form.get('year') or '').strip()
                region = (request.form.get('region') or '').strip()
                uploaded_file = extract_photo_from_request()
                image_path = save_uploaded_wine_photo(uploaded_file)
                if name:
                    db.execute(
                        'INSERT INTO wines (name, year, region, image_path) VALUES (?, ?, ?, ?)',
                        (name, year, region, image_path)
                    )
                    db.commit()
                    flash("Bouteille ajoutée à la dégustation !", "success")

        elif action == 'edit_wine':
            current_phase = db.execute('SELECT phase FROM game_state WHERE id = 1').fetchone()['phase']
            if current_phase in ('VOTING', 'RESULTS'):
                flash("Impossible de modifier une bouteille : les votes ont déjà commencé.", "error")
            else:
                wine_id = request.form.get('wine_id')
                wine_row = db.execute('SELECT * FROM wines WHERE id = ?', (wine_id,)).fetchone()
                if not wine_row:
                    flash("Bouteille introuvable.", "error")
                else:
                    name = (request.form.get('name') or '').strip()
                    year = (request.form.get('year') or '').strip()
                    region = (request.form.get('region') or '').strip()
                    remove_photo = bool(request.form.get('remove_photo'))
                    uploaded_file = extract_photo_from_request()

                    if not name:
                        flash("Le nom du vin est obligatoire.", "error")
                    else:
                        image_path = wine_row['image_path']
                        new_image_path = save_uploaded_wine_photo(uploaded_file)
                        if new_image_path:
                            delete_photo_file(image_path)
                            image_path = new_image_path
                        elif remove_photo:
                            delete_photo_file(image_path)
                            image_path = None

                        db.execute(
                            'UPDATE wines SET name = ?, year = ?, region = ?, image_path = ? WHERE id = ?',
                            (name, year, region, image_path, wine_id)
                        )
                        db.commit()
                        flash("Bouteille mise à jour !", "success")

        elif action == 'delete_wine':
            wine_id = request.form.get('wine_id')
            wine_row = db.execute('SELECT image_path FROM wines WHERE id = ?', (wine_id,)).fetchone()
            if wine_row:
                delete_photo_file(wine_row['image_path'])
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
                    [''.join(random.choices(string.ascii_uppercase, k=3)) for _ in range(max(100, len(wines) * 10))],
                    len(wines)
                )
                for w, code in zip(wines, codes):
                    db.execute('UPDATE wines SET temp_code = ?, carafe_number = NULL WHERE id = ?', (code, w['id']))
                db.execute("UPDATE game_state SET phase = 'BLIND_STEP1' WHERE id = 1")
                db.commit()
                return redirect(url_for('game.index'))

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

        elif action == 'step_back_phase':
            current_phase = db.execute('SELECT phase FROM game_state WHERE id = 1').fetchone()['phase']
            if current_phase == 'RESULTS':
                db.execute("UPDATE game_state SET phase = 'VOTING' WHERE id = 1")
                db.commit()
                flash("Retour en phase de vote (VOTING).", "success")
            elif current_phase == 'VOTING':
                db.execute("UPDATE users SET votes_submitted = 0")
                db.execute("UPDATE game_state SET phase = 'BLIND_STEP2' WHERE id = 1")
                db.commit()
                flash("Retour à l'Étape 2 de mise en carafe (BLIND_STEP2).", "success")
            elif current_phase == 'BLIND_STEP2':
                db.execute("UPDATE wines SET carafe_number = NULL")
                db.execute("UPDATE game_state SET phase = 'BLIND_STEP1' WHERE id = 1")
                db.commit()
                flash("Retour à l'Étape 1 de mise en carafe (BLIND_STEP1).", "success")
            elif current_phase == 'BLIND_STEP1':
                db.execute("UPDATE wines SET temp_code = NULL, carafe_number = NULL")
                db.execute("UPDATE game_state SET phase = 'TASTING' WHERE id = 1")
                db.commit()
                flash("Retour à la phase de dégustation (TASTING).", "success")
            else:
                flash("Vous êtes déjà à la première étape (TASTING).", "error")

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

        elif action == 'finish_game':
            db.close()
            archived_path = archive_and_reset_database()
            session.clear()
            flash(
                f"Partie terminée ! Base sauvegardée dans {os.path.relpath(archived_path, config.BASE_DIR)} et nouvelle base vide créée.",
                "success"
            )
            return redirect(url_for('auth.login'))

        elif action == 'reset_game':
            db.execute("DELETE FROM votes")
            db.execute("DELETE FROM notes")
            db.execute("DELETE FROM wines")
            db.execute("UPDATE users SET votes_submitted = 0")
            db.execute("UPDATE game_state SET phase = 'TASTING', results_reveal = 'all', person_a_id = NULL, person_b_id = NULL WHERE id = 1")
            db.commit()
            flash("Partie réinitialisée.", "success")

        return redirect(url_for('admin.admin'))

    state = db.execute('SELECT * FROM game_state WHERE id = 1').fetchone()
    wines = db.execute('SELECT * FROM wines').fetchall()
    users = db.execute('SELECT * FROM users ORDER BY username').fetchall()
    users_map = {u['id']: u['username'] for u in users}

    carafes_ready = are_wines_in_carafes(wines)
    carafing_started = (
        state['phase'] in ('BLIND_STEP1', 'BLIND_STEP2', 'VOTING', 'RESULTS')
        or carafes_ready
    )
    carafing_completed = (
        carafes_ready
        or state['phase'] in ('VOTING', 'RESULTS')
    )

    can_add_wine = not carafing_started
    can_edit_wine = state['phase'] not in ('VOTING', 'RESULTS')
    can_step_back = state['phase'] in ('BLIND_STEP1', 'BLIND_STEP2', 'VOTING', 'RESULTS')

    prev_phase_labels = {
        'RESULTS': 'Mode vote (VOTING)',
        'VOTING': 'Mise en carafe - Étape 2',
        'BLIND_STEP2': 'Mise en carafe - Étape 1',
        'BLIND_STEP1': 'Dégustation (TASTING)'
    }
    prev_phase_label = prev_phase_labels.get(state['phase'])

    has_enough_wines = len(wines) >= 2
    roles_ready = bool(
        state['person_a_id'] and state['person_b_id'] and state['person_a_id'] != state['person_b_id']
    )

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

    archived_dbs = []
    if os.path.isdir(config.DB_ARCHIVE_FOLDER):
        archived_dbs = sorted(
            [f for f in os.listdir(config.DB_ARCHIVE_FOLDER) if f.endswith('.db')],
            reverse=True
        )

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
        can_edit_wine=can_edit_wine,
        carafing_completed=carafing_completed,
        can_step_back=can_step_back,
        prev_phase_label=prev_phase_label,
        carafes_ready=carafes_ready,
        can_start_step1=can_start_step1,
        can_force_step2=can_force_step2,
        can_force_voting=can_force_voting,
        all_votes_validated=all_votes_validated,
        can_reveal_results=can_reveal_results,
        can_export_pdf=can_export_pdf,
        archived_dbs=archived_dbs
    )