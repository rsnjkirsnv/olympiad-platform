import re
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import joinedload
from werkzeug.exceptions import BadRequest

from .extensions import db
from .models import Attempt, SolvedTask, Task, User

DIFFICULTIES = {"easy": "Лёгкая", "medium": "Средняя", "hard": "Сложная"}
ANSWER_PATTERN = re.compile(r"[+-]?[0-9]+(?:[.,][0-9]+)?\Z")


def validate_answer(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise BadRequest("Введите числовой ответ.")
    value = str(value)
    if len(value) > 64:
        raise BadRequest("Ответ не должен быть длиннее 64 символов.")
    answer = value.strip()
    if not answer or not ANSWER_PATTERN.fullmatch(answer):
        raise BadRequest("Введите число: например, 42 или 42,5. Формулы и степени не поддерживаются.")
    return answer, Decimal(answer.replace(",", "."))


def record_attempt(user_id, task, submitted_answer, numeric_answer):
    correct = numeric_answer == Decimal(task.correct_answer)
    awarded = False
    # A dedicated connection acquires the writer lock before any reads. WAL lets
    # request/authentication reads continue; busy_timeout handles competing writers.
    # Solved status and attempt commit together, or both are rolled back.
    with db.engine.connect().execution_options(sqlite_write=True) as connection:
        with connection.begin():
            if correct:
                statement = insert(SolvedTask).values(user_id=user_id, task_id=task.id)
                result = connection.execute(statement.on_conflict_do_nothing(index_elements=["user_id", "task_id"]))
                awarded = result.rowcount == 1
            connection.execute(insert(Attempt).values(user_id=user_id, task_id=task.id,
                                                     submitted_answer=submitted_answer, is_correct=correct))
            score = connection.scalar(select(func.count(SolvedTask.id)).where(SolvedTask.user_id == user_id))
    if correct:
        message = "Верно! +1 балл за новое решение." if awarded else "Верно! Эта задача уже решена, баллы сохранены."
    else:
        message = "Неверно. Попробуйте ещё раз — у вас получится!"
    return {"is_correct": correct, "awarded_points": int(awarded), "score": score, "message": message}


def solved_for(user_id):
    return db.session.scalars(select(SolvedTask).options(joinedload(SolvedTask.task))
                              .where(SolvedTask.user_id == user_id)
                              .order_by(SolvedTask.solved_at.desc(), SolvedTask.id.desc())).all()


def attempts_for(user_id, page=1):
    statement = select(Attempt).options(joinedload(Attempt.task)).where(Attempt.user_id == user_id)
    return db.paginate(statement.order_by(Attempt.created_at.desc(), Attempt.id.desc()),
                       page=page, per_page=20, max_per_page=20, error_out=False)


def leaderboard_rows():
    # Aggregate independently: joining raw attempts and solutions would multiply
    # both counts for users who have solved more than one task.
    solutions = (select(SolvedTask.user_id, func.count(SolvedTask.id).label("score"))
                 .group_by(SolvedTask.user_id).subquery())
    attempts = (select(
        Attempt.user_id,
        func.count(Attempt.id).label("attempt_count"),
        func.sum(case((Attempt.is_correct.is_(True), 1), else_=0)).label("correct_count"),
        func.sum(case((Attempt.is_correct.is_(False), 1), else_=0)).label("incorrect_count"),
    ).group_by(Attempt.user_id).subquery())
    score = func.coalesce(solutions.c.score, 0).label("score")
    statement = (select(
        User.id, User.username, score,
        func.coalesce(attempts.c.attempt_count, 0).label("attempt_count"),
        func.coalesce(attempts.c.correct_count, 0).label("correct_count"),
        func.coalesce(attempts.c.incorrect_count, 0).label("incorrect_count"),
    ).outerjoin(solutions, solutions.c.user_id == User.id)
      .outerjoin(attempts, attempts.c.user_id == User.id)
      .order_by(score.desc(), User.username_key.asc(), User.id.asc()))
    return db.session.execute(statement).all()
