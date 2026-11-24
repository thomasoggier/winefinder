import os
from flask import Flask
import config
from db import init_db
from routes.auth import auth_bp
from routes.game import game_bp
from routes.admin import admin_bp


def create_app():
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(config.DB_ARCHIVE_FOLDER, exist_ok=True)

    app = Flask(
        __name__,
        template_folder=os.path.join(config.BASE_DIR, 'templates'),
        static_folder=os.path.join(config.BASE_DIR, 'static')
    )
    app.secret_key = config.SECRET_KEY
    app.permanent_session_lifetime = config.PERMANENT_SESSION_LIFETIME
    app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER

    @app.before_request
    def make_session_permanent():
        from flask import session
        session.permanent = True

    app.register_blueprint(auth_bp)
    app.register_blueprint(game_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        init_db()

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)