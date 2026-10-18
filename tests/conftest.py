import re

import pytest

from app import create_app
from app.extensions import db


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "SECRET_KEY": "test-only-secret-key-with-at-least-32-characters",
                              "SESSION_COOKIE_SECURE": False}, instance_path=tmp_path)
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_token(client, path="/login"):
    response = client.get(path)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))
    assert token, f"Missing CSRF token on {path}"
    return token.group(1)


class AuthActions:
    def __init__(self, client):
        self.client = client

    def register(self, username="alice", password="SecretPass123"):
        return self.client.post("/register", data={"username": username, "password": password,
                                "password_confirm": password, "csrf_token": csrf_token(self.client)})

    def login(self, username="alice", password="SecretPass123"):
        return self.client.post("/login", data={"username": username, "password": password,
                                "csrf_token": csrf_token(self.client)})

    def logout(self):
        return self.client.post("/logout", data={"csrf_token": csrf_token(self.client, "/tasks")})

    def submit(self, answer="1275", task_id=1, **extra):
        return self.client.post(f"/api/tasks/{task_id}/submit", json={"answer": answer, **extra},
                                headers={"X-CSRFToken": csrf_token(self.client, "/tasks")})


@pytest.fixture
def auth(client):
    return AuthActions(client)
