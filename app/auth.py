import re
import unicodedata

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import User

auth = Blueprint("auth", __name__)
USERNAME_PATTERN = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9_]{3,32}\Z")


def username_values(value):
    name = unicodedata.normalize("NFKC", value).strip()
    return name, name.casefold()


@auth.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("pages.tasks"))
    error = None
    username = ""
    if request.method == "POST":
        username, key = username_values(request.form.get("username", ""))
        password = request.form.get("password", "")
        confirm = request.form.get("password_confirm", "")
        if not USERNAME_PATTERN.fullmatch(username):
            error = "Логин: от 3 до 32 символов, русские или латинские буквы, цифры и знак _."
        elif not 8 <= len(password) <= 128:
            error = "Пароль должен содержать от 8 до 128 символов."
        elif password != confirm:
            error = "Пароли не совпадают."
        else:
            user = User(username=username, username_key=key)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                error = "Этот логин уже занят. Выберите другой."
                return render_template("register.html", error=error, username=username), 409
            session.clear()
            login_user(user)
            session.permanent = True
            flash("Аккаунт создан. Начнём с первой задачи?", "success")
            return redirect(url_for("pages.tasks"))
    return render_template("register.html", error=error, username=username), 400 if error else 200


@auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("pages.tasks"))
    error = None
    username = ""
    if request.method == "POST":
        username, key = username_values(request.form.get("username", ""))
        password = request.form.get("password", "")
        user = db.session.scalar(select(User).where(User.username_key == key)) if len(key) <= 64 else None
        if not user or not 8 <= len(password) <= 128 or not user.check_password(password):
            error = "Неверный логин или пароль."
        else:
            session.clear()
            login_user(user)
            session.permanent = True
            # No untrusted next URL: logging in always leads to the user's account.
            return redirect(url_for("pages.profile"))
    return render_template("login.html", error=error, username=username), 401 if error else 200


@auth.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Вы вышли из аккаунта. Прогресс сохранён.", "info")
    return redirect(url_for("pages.index"))
