from sqlalchemy.dialects.sqlite import insert

from .extensions import db
from .models import Task


# Server-only initial data. Templates and API responses never expose this field.
INITIAL_TASKS = [
    {"slug": "sum-to-fifty", "title": "Сумма без калькулятора", "difficulty": "easy",
     "description": "Найдите сумму всех натуральных чисел от 1 до 50 включительно.", "correct_answer": "1275"},
    {"slug": "digit-sum", "title": "Цифры нового года", "difficulty": "easy",
     "description": "Найдите сумму цифр числа 2026.", "correct_answer": "10"},
    {"slug": "common-multiple", "title": "Общий знаменатель", "difficulty": "medium",
     "description": "Найдите наименьшее положительное целое число, которое делится без остатка одновременно на 6, 8 и 15.", "correct_answer": "120"},
    {"slug": "distinct-digits", "title": "Ни одной одинаковой", "difficulty": "medium",
     "description": "Сколько существует трёхзначных натуральных чисел, все цифры которых различны? Первая цифра не может быть нулём.", "correct_answer": "648"},
    {"slug": "binary-strings", "title": "Единицам нужна дистанция", "difficulty": "hard",
     "description": "Сколько существует двоичных строк длины 8, в которых нет двух соседних единиц? Строка может начинаться с нуля.", "correct_answer": "55"},
    {"slug": "grid-paths", "title": "Маршруты на решётке", "difficulty": "hard",
     "description": "Сколько различных путей ведут из точки (0, 0) в точку (4, 4), если каждый шаг разрешено делать только вправо или вверх на одну клетку?", "correct_answer": "70"},
]


def seed_tasks():
    # A stable slug makes seeding idempotent, including simultaneous startups.
    with db.engine.connect().execution_options(sqlite_write=True) as connection:
        with connection.begin():
            connection.execute(insert(Task).values(INITIAL_TASKS).on_conflict_do_nothing(index_elements=["slug"]))
