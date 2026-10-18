import pytest

from conftest import csrf_token


def test_catalog_and_all_difficulties(client):
    response = client.get("/api/tasks")
    assert response.status_code == 200
    tasks = response.json["tasks"]
    assert len(tasks) == 6
    assert {item["difficulty"] for item in tasks} == {"easy", "medium", "hard"}
    assert client.get("/tasks").status_code == 200
    assert client.get("/tasks?difficulty=easy").text.count('class="task-card ') == 2
    assert client.get("/tasks?difficulty=unknown").status_code == 400


@pytest.mark.parametrize("task_id,answer", [(1, "1275"), (2, "10"), (3, "120"), (4, "648"), (5, "55"), (6, "70")])
def test_correct_answers(auth, task_id, answer):
    auth.register()
    response = auth.submit(answer, task_id)
    assert response.status_code == 200
    assert response.json["is_correct"] is True
    assert response.json["awarded_points"] == response.json["score"] == 1


def test_wrong_answer(auth, client):
    auth.register()
    response = auth.submit("999")
    assert response.json["is_correct"] is False
    assert response.json["awarded_points"] == response.json["score"] == 0
    assert client.get("/api/me/attempts").json["total"] == 1


@pytest.mark.parametrize("answer", ["  +01275 ", "1275.0", "1275,00", 1275, 1275.0])
def test_numeric_normalization(auth, answer):
    auth.register()
    assert auth.submit(answer).json["is_correct"] is True


@pytest.mark.parametrize("answer", ["", "  ", None, True, False, [], {}, "NaN", "Infinity", "1e900", "x" * 65,
                                  "0" * 65, "1/0", "<script>alert(1)</script>", "１２７５", "1\x00275"])
def test_bad_answers_are_not_recorded(auth, client, answer):
    auth.register()
    response = auth.submit(answer)
    assert response.status_code == 400
    assert "error" in response.json
    assert client.get("/api/me/attempts").json["total"] == 0


@pytest.mark.parametrize("payload", [{}, {"answer": "1275", "user_id": 2}, {"answer": "1275", "score": 999},
                                   {"answer": "999", "is_correct": True}, [], None, "1275"])
def test_invalid_json_structure(auth, client, payload):
    auth.register()
    response = client.post("/api/tasks/1/submit", json=payload, content_type="application/json",
                           headers={"X-CSRFToken": csrf_token(client, "/tasks")})
    assert response.status_code == 400
    assert client.get("/api/me").json["score"] == 0


def test_invalid_json_and_content_type(auth, client):
    auth.register()
    headers = {"X-CSRFToken": csrf_token(client, "/tasks")}
    response = client.post("/api/tasks/1/submit", data='{broken:', content_type="application/json", headers=headers)
    assert response.status_code == 400
    assert "JSON" in response.json["error"]
    assert client.post("/api/tasks/1/submit", data="answer=1275", headers=headers).status_code == 415


@pytest.mark.parametrize("task_id", [0, 99999, 9223372036854775808])
def test_missing_task(auth, client, task_id):
    auth.register()
    assert auth.submit(task_id=task_id).status_code == 404
    assert client.get("/api/me/attempts").json["total"] == 0


def test_submit_without_javascript(auth, client):
    auth.register()
    response = client.post("/tasks/1/submit", data={"answer": "1275", "csrf_token": csrf_token(client, "/tasks")})
    assert response.status_code == 303
    assert "Верно" in client.get(response.location).text
    assert client.get("/api/me").json["score"] == 1
