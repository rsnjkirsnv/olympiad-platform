import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import User
from conftest import csrf_token


def test_register_two_users_and_hash_passwords(app, auth):
    assert auth.register().status_code == 302
    assert auth.logout().status_code == 302
    assert auth.register("bob").status_code == 302
    with app.app_context():
        users = db.session.scalars(select(User).order_by(User.id)).all()
        assert [user.username for user in users] == ["alice", "bob"]
        assert all(user.password_hash != "SecretPass123" and user.check_password("SecretPass123") for user in users)


def test_duplicate_username_is_case_insensitive(auth, app):
    auth.register("Alice")
    auth.logout()
    response = auth.register("aLiCe")
    assert response.status_code == 409
    assert "уже занят" in response.text
    with app.app_context():
        assert len(db.session.scalars(select(User)).all()) == 1


def test_login_logout_and_session_refresh(auth, client):
    auth.register()
    assert auth.logout().status_code == 302
    assert client.get("/api/me").status_code == 401
    assert auth.login(password="incorrect-pass").status_code == 401
    assert auth.login().status_code == 302
    assert client.get("/profile").status_code == 200
    assert client.get("/api/me").json["username"] == "alice"
    assert client.get("/api/me").json["username"] == "alice"


@pytest.mark.parametrize("username,password", [("ab", "SecretPass123"), ("a" * 33, "SecretPass123"),
    ("bad name", "SecretPass123"), ("name", "short"), ("name", "x" * 129), ("';DROP TABLE users;--", "SecretPass123")])
def test_invalid_registration(client, username, password):
    response = client.post("/register", data={"username": username, "password": password,
                           "password_confirm": password, "csrf_token": csrf_token(client)})
    assert response.status_code == 400
    assert client.get("/api/me").status_code == 401


def test_password_confirmation(client):
    response = client.post("/register", data={"username": "alice", "password": "SecretPass123",
                           "password_confirm": "another-password", "csrf_token": csrf_token(client)})
    assert response.status_code == 400
    assert "не совпадают" in response.text


def test_cyrillic_username(auth, client):
    assert auth.register("Юный_Математик").status_code == 302
    auth.logout()
    assert auth.login("юный_математик").status_code == 302
    assert client.get("/api/me").json["username"] == "Юный_Математик"


def test_open_redirect_is_not_followed(auth, client):
    auth.register()
    auth.logout()
    response = client.post("/login?next=https://evil.example", data={"username": "alice",
                           "password": "SecretPass123", "csrf_token": csrf_token(client)})
    assert response.location == "/profile"
