import pytest
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app import create_app
from app.extensions import db
from app.models import Attempt, SolvedTask, Task, User
from conftest import csrf_token


def test_anonymous_access(client):
    assert client.post("/api/tasks/1/submit", json={"answer": "1275"}).status_code == 401
    for route in ["/api/me", "/api/me/attempts"]:
        assert client.get(route).status_code == 401
    for route in ["/profile", "/history"]:
        assert client.get(route).status_code == 302


def test_csrf_for_all_mutations(client, auth):
    assert client.post("/register", data={"username": "alice", "password": "SecretPass123"}).status_code == 400
    assert client.post("/login", data={"username": "alice", "password": "SecretPass123"}).status_code == 400
    auth.register()
    assert client.post("/api/tasks/1/submit", json={"answer": "1275"}).status_code == 400
    assert client.post("/api/tasks/1/submit", json={"answer": "1275"}, headers={"X-CSRFToken": "invalid"}).status_code == 400
    assert client.post("/tasks/1/submit", data={"answer": "1275"}).status_code == 400
    assert client.post("/logout").status_code == 400
    assert client.get("/logout").status_code == 405
    assert client.get("/api/me").json["score"] == 0


def test_answers_and_password_hashes_not_exposed(app, client, auth):
    auth.register()
    with app.app_context():
        task = db.session.get(Task, 1)
        task.correct_answer = "938475610293847"
        password_hash = db.session.scalar(select(User.password_hash))
        db.session.commit()
    for path in ["/", "/tasks", "/api/tasks", "/profile", "/history", "/api/me", "/api/me/attempts", "/leaderboard"]:
        response = client.get(path)
        assert "938475610293847" not in response.text
        assert "correct_answer" not in response.text
        assert "password_hash" not in response.text
        assert password_hash not in response.text
    auth.submit("938475610293847")
    assert "correct_answer" not in client.get("/api/me").text
    assert "correct_answer" not in client.get("/api/me/attempts").text
    assert set(client.get("/api/tasks").json["tasks"][0]) == {"id", "title", "description", "difficulty"}


def test_no_score_or_other_user_endpoints(auth, client):
    auth.register()
    headers = {"X-CSRFToken": csrf_token(client, "/tasks")}
    for method, path in [("post", "/api/me"), ("patch", "/api/me"), ("put", "/api/users/2/score"),
                         ("post", "/api/score"), ("post", "/api/me/attempts")]:
        response = getattr(client, method)(path, json={"score": 999, "user_id": 2}, headers=headers)
        assert response.status_code in {404, 405}
    for path in ["/api/users/2/attempts", "/api/me/attempts/2", "/profile/2"]:
        assert client.get(path).status_code == 404
    assert client.get("/api/me?user_id=2").status_code == 400
    assert client.get("/api/me/attempts?user_id=2").status_code == 400
    assert client.get("/history?user_id=2").status_code == 400
    assert client.get("/api/me").json["score"] == 0


@pytest.mark.parametrize("page", ["0", "-1", "abc", "1.5", "999999999999999999999", "١"])
def test_invalid_pagination(auth, client, page):
    auth.register()
    assert client.get("/api/me/attempts", query_string={"page": page}).status_code == 400


def test_xss_and_sql_injection(client, auth, app):
    payload = '<script>alert("x")</script>'
    response = client.post("/register", data={"username": payload, "password": "SecretPass123",
                           "password_confirm": "SecretPass123", "csrf_token": csrf_token(client)})
    assert response.status_code == 400
    assert payload not in response.text
    assert "&lt;script&gt;" in response.text
    auth.register()
    assert auth.submit("' OR 1=1 --").status_code == 400
    # Even unexpected legacy database content remains escaped in history.
    with app.app_context():
        db.session.add(Attempt(user_id=1, task_id=1, submitted_answer=payload, is_correct=False))
        db.session.commit()
    assert payload not in client.get("/history").text
    assert "&lt;script&gt;" in client.get("/history").text


def test_cookie_flags_and_security_headers(client, auth, tmp_path):
    response = auth.register()
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure;" not in cookie
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    secure = create_app({"TESTING": True, "SECRET_KEY": "s" * 64, "SESSION_COOKIE_SECURE": True},
                        instance_path=tmp_path / "https")
    try:
        result = secure.test_client().get("/login", base_url="https://localhost")
        assert "Secure;" in result.headers["Set-Cookie"]
        assert "Strict-Transport-Security" in result.headers
    finally:
        with secure.app_context():
            db.session.remove()
            db.engine.dispose()


def test_database_constraints_and_pragmas(app, auth):
    auth.register()
    auth.submit()
    with app.app_context():
        assert db.session.scalar(text("PRAGMA foreign_keys")) == 1
        assert db.session.scalar(text("PRAGMA busy_timeout")) == 30000
        assert db.session.scalar(text("PRAGMA journal_mode")) == "wal"
        with pytest.raises(IntegrityError):
            db.session.execute(insert(SolvedTask).values(user_id=1, task_id=1))
        db.session.rollback()
        with pytest.raises(IntegrityError):
            db.session.execute(insert(Attempt).values(user_id=9999, task_id=1, submitted_answer="1", is_correct=False))
        db.session.rollback()


def test_atomic_rollback_if_attempt_insert_fails(app, auth):
    auth.register()
    with app.app_context():
        engine = db.engine

    def fail_attempt(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO attempts"):
            raise OperationalError("private SQL debug details", {}, Exception("database unavailable"))

    event.listen(engine, "before_cursor_execute", fail_attempt)
    try:
        response = auth.submit()
        assert response.status_code == 503
        assert "private SQL" not in response.text
    finally:
        event.remove(engine, "before_cursor_execute", fail_attempt)
    with app.app_context():
        assert db.session.scalar(select(func.count(SolvedTask.id))) == 0
        assert db.session.scalar(select(func.count(Attempt.id))) == 0
    assert auth.submit().json["score"] == 1


def test_request_size_limit(auth, client):
    auth.register()
    response = client.post("/api/tasks/1/submit", data='{"answer":"' + "1" * 17000 + '"}',
                           content_type="application/json", headers={"X-CSRFToken": csrf_token(client, "/tasks")})
    assert response.status_code == 413


def test_local_secret_survives_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    first = create_app({"TESTING": True}, instance_path=tmp_path)
    key = first.secret_key
    with first.app_context():
        db.engine.dispose()
    second = create_app({"TESTING": True}, instance_path=tmp_path)
    assert len(key) >= 32 and key == second.secret_key
    with second.app_context():
        db.engine.dispose()
