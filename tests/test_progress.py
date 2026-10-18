from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, select

from app import create_app
from app.extensions import db
from app.models import Attempt, SolvedTask, Task, User
from conftest import AuthActions, csrf_token


def test_unique_points_all_attempts_and_relogin(auth, client):
    auth.register()
    assert auth.submit("999").json["score"] == 0
    assert auth.submit().json["awarded_points"] == 1
    assert auth.submit().json["awarded_points"] == 0
    history = client.get("/api/me/attempts").json
    assert history["total"] == 3
    assert [item["is_correct"] for item in history["attempts"]] == [True, True, False]
    assert all(item["created_at"].endswith("Z") for item in history["attempts"])
    assert client.get("/api/me").json["solved_count"] == 1
    auth.logout()
    auth.login()
    assert client.get("/api/me").json["score"] == 1
    assert client.get("/api/me/attempts").json["total"] == 3


def test_personal_data_isolation(app, auth, client):
    auth.register("alice")
    auth.submit()
    bob = app.test_client()
    bob_auth = AuthActions(bob)
    bob_auth.register("bob")
    assert bob.get("/api/me").json["score"] == 0
    assert bob.get("/api/me/attempts").json["attempts"] == []
    assert "1275" not in bob.get("/history").text
    bob_auth.submit("333")
    assert client.get("/api/me/attempts").json["total"] == 1
    assert client.get("/api/me/attempts").json["attempts"][0]["submitted_answer"] == "1275"


def test_leaderboard_includes_zero_and_stable_ties(auth, client, app):
    auth.register("zeta")
    auth.logout()
    auth.register("bob")
    auth.submit()
    auth.logout()
    auth.register("alice")
    auth.submit()
    with app.app_context():
        from app.services import leaderboard_rows
        assert [(row.username, row.score) for row in leaderboard_rows()] == [("alice", 1), ("bob", 1), ("zeta", 0)]
    html = client.get("/leaderboard").text
    assert html.index('>alice</strong>') < html.index('>bob</strong>') < html.index('>zeta</strong>')
    assert "это вы" in html


def test_parallel_submissions_use_independent_connections(app, auth):
    auth.register()
    count = 8
    barrier = Barrier(count)

    def worker(_):
        with app.test_client() as independent_client:
            actions = AuthActions(independent_client)
            assert actions.login().status_code == 302
            token = csrf_token(independent_client, "/tasks")
            barrier.wait(timeout=30)
            response = independent_client.post("/api/tasks/1/submit", json={"answer": "1275"},
                                               headers={"X-CSRFToken": token})
            return response.status_code, response.json

    with ThreadPoolExecutor(max_workers=count) as executor:
        responses = list(executor.map(worker, range(count)))
    assert all(status == 200 for status, _ in responses)
    assert all(body["is_correct"] and body["score"] == 1 for _, body in responses)
    assert sum(body["awarded_points"] for _, body in responses) == 1
    with app.app_context():
        assert db.session.scalar(select(func.count(SolvedTask.id))) == 1
        assert db.session.scalar(select(func.count(Attempt.id))) == count
        assert all(db.session.scalars(select(Attempt.is_correct)).all())


def test_persistence_and_idempotent_seeding_after_new_app(app, auth, tmp_path):
    auth.register()
    auth.submit()
    auth.submit("999")
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    second = create_app({"TESTING": True, "SECRET_KEY": app.config["SECRET_KEY"], "SESSION_COOKIE_SECURE": False},
                        instance_path=tmp_path)
    client = second.test_client()
    assert AuthActions(client).login().status_code == 302
    assert client.get("/api/me").json["score"] == 1
    assert client.get("/api/me/attempts").json["total"] == 2
    with second.app_context():
        assert db.session.scalar(select(func.count(Task.id))) == 6
        assert db.session.scalar(select(func.count(func.distinct(Task.slug)))) == 6
        assert db.session.scalar(select(func.count(User.id))) == 1
        db.session.remove()
        db.engine.dispose()


def test_history_pagination(auth, client):
    auth.register()
    for _ in range(23):
        auth.submit("1")
    first = client.get("/api/me/attempts").json
    second = client.get("/api/me/attempts?page=2").json
    assert len(first["attempts"]) == 20
    assert len(second["attempts"]) == 3
    assert first["total"] == second["total"] == 23
    assert not {item["id"] for item in first["attempts"]} & {item["id"] for item in second["attempts"]}
    assert client.get("/history?page=2").status_code == 200
    assert "Страница 2 из 2" in client.get("/history?page=2").text
