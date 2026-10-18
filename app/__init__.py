import os
import secrets
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from werkzeug.exceptions import HTTPException

from .extensions import csrf, db, login_manager

ROOT = Path(__file__).resolve().parent.parent


def local_secret(instance_path):
    path = Path(instance_path) / ".secret_key"
    try:
        with path.open("x", encoding="utf-8") as file:
            key = secrets.token_hex(32)
            file.write(key)
            return key
    except FileExistsError:
        key = path.read_text(encoding="utf-8").strip()
        if len(key) < 32:
            raise RuntimeError("Файл instance/.secret_key повреждён. Восстановите секретный ключ.") from None
        return key


def create_app(test_config=None, *, instance_path=None):
    load_dotenv(ROOT / ".env")
    app = Flask(__name__, instance_path=str(instance_path or ROOT / "instance"))
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI="sqlite:///olympiad.db",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"timeout": 30}},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        MAX_CONTENT_LENGTH=16 * 1024,
        MAX_FORM_MEMORY_SIZE=16 * 1024,
        MAX_FORM_PARTS=20,
        WTF_CSRF_TIME_LIMIT=7200,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = local_secret(app.instance_path)
    if len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("SECRET_KEY должен содержать не менее 32 символов.")

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.session_protection = "strong"

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api/"):
            return jsonify(error="Для этого действия войдите в аккаунт."), 401
        return redirect(url_for("auth.login"))

    @app.before_request
    def authenticate_api():
        # Give an anonymous API caller a clear 401 before checking CSRF.
        if request.path.startswith("/api/") and not (request.path == "/api/tasks" and request.method == "GET"):
            if not current_user.is_authenticated:
                return unauthorized()

    csrf.init_app(app)

    from .auth import auth
    from .routes import api, pages
    from .seed import seed_tasks
    from .services import DIFFICULTIES
    app.register_blueprint(auth)
    app.register_blueprint(pages)
    app.register_blueprint(api)

    @app.context_processor
    def template_globals():
        return {"difficulties": DIFFICULTIES}

    @app.template_filter("moscow_time")
    def moscow_time(value):
        return (value + timedelta(hours=3)).strftime("%d.%m.%Y · %H:%M")

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def error_response(message, status):
        if request.path.startswith("/api/"):
            return jsonify(error=message), status
        return render_template("error.html", message=message, status=status), status

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return error_response("Срок действия формы истёк или отсутствует защитный токен. Обновите страницу и попробуйте снова.", 400)

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {404: "Страница или задача не найдена.", 405: "Этот метод запроса не поддерживается.",
                    413: "Запрос слишком большой.", 500: "Не удалось обработать запрос. Попробуйте позже."}
        message = messages.get(error.code, error.description)
        return error_response(message, error.code)

    @app.errorhandler(OperationalError)
    def database_error(error):
        db.session.rollback()
        app.logger.exception("Database request failed")
        return error_response("База данных временно занята. Попробуйте ещё раз немного позже.", 503)

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return error_response("Не удалось обработать запрос. Попробуйте позже.", 500)

    with app.app_context():
        engine = db.engine

        @event.listens_for(engine, "connect")
        def sqlite_connect(connection, record):
            # Explicit SQLAlchemy transaction management, consistent on Python 3.11+.
            connection.isolation_level = None
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        @event.listens_for(engine, "begin")
        def sqlite_begin(connection):
            mode = "BEGIN IMMEDIATE" if connection.get_execution_options().get("sqlite_write") else "BEGIN"
            connection.exec_driver_sql(mode)

        # WAL must be configured outside a transaction.
        raw = engine.raw_connection()
        try:
            raw.cursor().execute("PRAGMA journal_mode=WAL")
        finally:
            raw.close()
        db.create_all()
        seed_tasks()
    return app
