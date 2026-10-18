from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select
from werkzeug.exceptions import BadRequest, NotFound, UnsupportedMediaType

from .extensions import db
from .models import Task
from .services import DIFFICULTIES, attempts_for, leaderboard_rows, record_attempt, solved_for, validate_answer

pages = Blueprint("pages", __name__)
api = Blueprint("api", __name__, url_prefix="/api")


def find_task(task_id):
    if not 1 <= task_id <= 9223372036854775807:
        raise NotFound("Задача не найдена.")
    return db.get_or_404(Task, task_id, description="Задача не найдена.")


def parse_page():
    if set(request.args) - {"page"}:
        raise BadRequest("Неизвестные параметры запроса.")
    value = request.args.get("page", "1")
    if len(value) > 6 or not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 100000:
        raise BadRequest("Некорректный номер страницы.")
    return int(value)


@pages.get("/")
def index():
    count = db.session.scalar(select(func.count(Task.id)))
    return render_template("index.html", task_count=count)


@pages.get("/tasks")
def tasks():
    difficulty = request.args.get("difficulty", "all")
    if difficulty not in {"all", *DIFFICULTIES}:
        raise BadRequest("Неизвестный уровень сложности.")
    statement = select(Task).order_by(Task.id)
    if difficulty != "all":
        statement = statement.where(Task.difficulty == difficulty)
    items = db.session.scalars(statement).all()
    solved = solved_for(current_user.id) if current_user.is_authenticated else []
    return render_template("tasks.html", tasks=items, difficulty=difficulty,
                           solved_ids={item.task_id for item in solved}, score=len(solved))


@pages.get("/profile")
@login_required
def profile():
    solved = solved_for(current_user.id)
    total = db.session.scalar(select(func.count(Task.id)))
    recent = attempts_for(current_user.id)
    return render_template("profile.html", solved=solved, total=total, recent=recent.items[:5],
                           attempt_count=recent.total)


@pages.get("/history")
@login_required
def history():
    return render_template("history.html", pagination=attempts_for(current_user.id, parse_page()))


@pages.get("/leaderboard")
def leaderboard():
    return render_template("leaderboard.html", leaders=leaderboard_rows())


@pages.post("/tasks/<int:task_id>/submit")
@login_required
def submit_form(task_id):
    task = find_task(task_id)
    if set(request.form) - {"answer", "csrf_token"}:
        raise BadRequest("Допустимо передать только ответ.")
    submitted, numeric = validate_answer(request.form.get("answer"))
    result = record_attempt(current_user.id, task, submitted, numeric)
    flash(result["message"], "success" if result["is_correct"] else "error")
    return redirect(url_for("pages.tasks", _anchor=f"task-{task_id}"), code=303)


@api.get("/tasks")
def task_list():
    items = db.session.scalars(select(Task).order_by(Task.id)).all()
    return jsonify(tasks=[task.public_dict() for task in items])


@api.post("/tasks/<int:task_id>/submit")
@login_required
def submit(task_id):
    task = find_task(task_id)
    if not request.is_json:
        raise UnsupportedMediaType("Отправьте JSON с полем answer.")
    try:
        payload = request.get_json()
    except BadRequest:
        raise BadRequest("Некорректный JSON.") from None
    if not isinstance(payload, dict) or set(payload) != {"answer"}:
        raise BadRequest("Передайте объект JSON с единственным полем answer.")
    submitted, numeric = validate_answer(payload["answer"])
    return jsonify(record_attempt(current_user.id, task, submitted, numeric))


@api.get("/me")
@login_required
def me():
    if request.args:
        raise BadRequest("Параметры пользователя передавать не нужно.")
    solved = solved_for(current_user.id)
    return jsonify(username=current_user.username, score=len(solved), solved_count=len(solved),
                   solved_tasks=[{"task": item.task.public_dict(), "solved_at": item.solved_at.isoformat() + "Z"}
                                 for item in solved])


@api.get("/me/attempts")
@login_required
def attempts():
    pagination = attempts_for(current_user.id, parse_page())
    return jsonify(page=pagination.page, pages=pagination.pages, total=pagination.total,
                   attempts=[{"id": item.id, "task": item.task.public_dict(),
                              "submitted_answer": item.submitted_answer, "is_correct": item.is_correct,
                              "created_at": item.created_at.isoformat() + "Z"} for item in pagination.items])
