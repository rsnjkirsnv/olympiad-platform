from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utc_now():
    """SQLite stores naive datetimes; all stored timestamps represent UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), nullable=False)
    username_key = db.Column(db.String(64), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Task(db.Model):
    __tablename__ = "tasks"
    __table_args__ = (
        db.CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="valid_difficulty"),
    )

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), nullable=False, unique=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    difficulty = db.Column(db.String(12), nullable=False, index=True)
    correct_answer = db.Column(db.String(64), nullable=False)

    def public_dict(self):
        # Explicit allowlist: never serialize the model or its __dict__.
        return {"id": self.id, "title": self.title, "description": self.description,
                "difficulty": self.difficulty}


class Attempt(db.Model):
    __tablename__ = "attempts"
    __table_args__ = (db.Index("ix_attempts_user_time", "user_id", "created_at", "id"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False, index=True)
    submitted_answer = db.Column(db.String(64), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    task = db.relationship("Task")


class SolvedTask(db.Model):
    __tablename__ = "solved_tasks"
    __table_args__ = (db.UniqueConstraint("user_id", "task_id", name="uq_solved_user_task"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False, index=True)
    solved_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    task = db.relationship("Task")
