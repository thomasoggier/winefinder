from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db

auth_bp = Blueprint("auth", __name__)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            flash("Accès réservé à l'administrateur.", "error")
            return redirect(url_for('game.index'))
        return f(*args, **kwargs)
    return decorated


@auth_bp.route('/login', methods=['GET', 'POST'])
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
                    return redirect(url_for('game.index'))
        else:
            user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['is_admin'] = user['is_admin']
                return redirect(url_for('game.index'))
            flash("Identifiants incorrects.", "error")
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))