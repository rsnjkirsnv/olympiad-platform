"""Real HTTP checks with two server processes and an isolated persistent database."""
import argparse
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--directory")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        from app import create_app
        create_app({"SESSION_COOKIE_SECURE": False}, instance_path=args.directory).run(
            host="127.0.0.1", port=args.port, debug=False, threaded=True)
        return

    directory = ROOT / ".local" / "http-check" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    directory.mkdir(parents=True)
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    password = "LocalVerification123!"

    def token(session, path="/login"):
        result = session.get(base + path, timeout=30)
        result.raise_for_status()
        return re.search(r'<meta name="csrf-token" content="([^"]+)"', result.text).group(1)

    def register(session, username):
        result = session.post(base + "/register", data={"username": username, "password": password,
                              "password_confirm": password, "csrf_token": token(session)}, timeout=30)
        assert result.status_code == 200 and result.url.endswith("/tasks")

    def login(session, username):
        result = session.post(base + "/login", data={"username": username, "password": password,
                              "csrf_token": token(session)}, timeout=30)
        assert result.status_code == 200 and result.url.endswith("/profile")

    def submit(session, answer="1275"):
        result = session.post(base + "/api/tasks/1/submit", json={"answer": answer},
                              headers={"X-CSRFToken": token(session, "/tasks")}, timeout=35)
        result.raise_for_status()
        return result.json()

    def start(log):
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", "--directory", str(directory),
                                    "--port", str(port)], cwd=ROOT, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        for _ in range(80):
            if process.poll() is not None:
                raise RuntimeError(f"Server exited; see {directory / 'server.log'}")
            try:
                if requests.get(base, timeout=1).status_code == 200:
                    return process
            except requests.RequestException:
                pass
            time.sleep(0.1)
        process.terminate()
        process.wait(timeout=10)
        raise RuntimeError("Server failed to start")

    def stop(process):
        process.terminate()
        process.wait(timeout=10)

    with (directory / "server.log").open("w", encoding="utf-8") as log:
        process = start(log)
        alice, bob = requests.Session(), requests.Session()
        try:
            for path in ["/", "/register", "/login", "/tasks", "/leaderboard", "/api/tasks"]:
                assert alice.get(base + path, timeout=30).status_code == 200
            register(alice, "http_alice")
            register(bob, "http_bob")
            assert submit(alice, "999")["score"] == 0
            barrier = Barrier(6)

            def parallel(_):
                with requests.Session() as independent:
                    login(independent, "http_alice")
                    csrf = token(independent, "/tasks")
                    barrier.wait(timeout=30)
                    response = independent.post(base + "/api/tasks/1/submit", json={"answer": "1275"},
                                                headers={"X-CSRFToken": csrf}, timeout=35)
                    assert response.status_code == 200
                    return response.json()

            with ThreadPoolExecutor(max_workers=6) as executor:
                results = list(executor.map(parallel, range(6)))
            assert sum(item["awarded_points"] for item in results) == 1
            assert submit(alice)["awarded_points"] == 0
            assert alice.get(base + "/api/me", timeout=30).json()["score"] == 1
            assert alice.get(base + "/api/me/attempts", timeout=30).json()["total"] == 8
            assert bob.get(base + "/api/me/attempts", timeout=30).json()["total"] == 0
            ranking = bob.get(base + "/leaderboard", timeout=30).text
            assert ranking.index('>http_alice</strong>') < ranking.index('>http_bob</strong>')
            assert alice.post(base + "/logout", data={"csrf_token": token(alice, "/tasks")}, timeout=30).status_code == 200
            assert alice.get(base + "/api/me", timeout=30).status_code == 401
            login(alice, "http_alice")
        finally:
            stop(process)

        process = start(log)
        try:
            # The existing signed cookie still works after an actual process restart.
            assert alice.get(base + "/api/me", timeout=30).json()["score"] == 1
            assert alice.get(base + "/api/me/attempts", timeout=30).json()["total"] == 8
            assert len(alice.get(base + "/api/tasks", timeout=30).json()["tasks"]) == 6
            with requests.Session() as fresh:
                login(fresh, "http_alice")
                assert fresh.get(base + "/api/me", timeout=30).json()["score"] == 1
            assert bob.get(base + "/api/me", timeout=30).json()["score"] == 0
            print("HTTP smoke PASS: routes, 2 users, answers, 6 simultaneous requests, 1 point, 8 attempts,")
            print("isolation, leaderboard, logout/login, process restart, persistent session and database, 6 unique seeds.")
            print(f"Isolated verification data: {directory}")
        finally:
            stop(process)
            alice.close()
            bob.close()


if __name__ == "__main__":
    main()
