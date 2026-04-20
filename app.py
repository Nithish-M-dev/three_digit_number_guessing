import json
import os
import sqlite3
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT 'A'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                attempts_used INTEGER NOT NULL,
                result TEXT NOT NULL,
                date_time TEXT NOT NULL
            )
            """
        )
        conn.commit()


class GuessItHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def end_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/participants":
            self.handle_get_participants()
            return
        if path == "/api/scores":
            self.handle_get_scores()
            return
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/participants":
            self.handle_post_participant()
            return
        if path == "/api/scores":
            self.handle_post_score()
            return
        self.end_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def handle_get_participants(self):
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT username, avatar FROM users ORDER BY LOWER(username)"
            ).fetchall()
        participants = [dict(row) for row in rows]
        self.end_json({"participants": participants, "count": len(participants)})

    def handle_get_scores(self):
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT username, attempts_used, result, date_time
                FROM scores
                ORDER BY attempts_used ASC, id ASC
                """
            ).fetchall()
        scores = [
            {
                "username": row["username"],
                "attemptsUsed": row["attempts_used"],
                "result": row["result"],
                "dateTime": row["date_time"],
            }
            for row in rows
        ]
        self.end_json({"scores": scores, "count": len(scores)})

    def handle_post_participant(self):
        try:
            payload = self.read_json()
        except json.JSONDecodeError:
            self.end_json({"error": "Invalid JSON body"}, HTTPStatus.BAD_REQUEST)
            return

        username = str(payload.get("username", "")).strip()
        avatar = str(payload.get("avatar", "")).strip() or "A"
        password = str(payload.get("password", "")).strip()

        if not username:
            self.end_json({"error": "Username is required"}, HTTPStatus.BAD_REQUEST)
            return

        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id, password FROM users WHERE LOWER(username) = LOWER(?)",
                (username,),
            ).fetchone()
            if existing:
                next_password = password or existing["password"] or ""
                conn.execute(
                    "UPDATE users SET username = ?, avatar = ?, password = ? WHERE id = ?",
                    (username, avatar, next_password, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO users (username, password, avatar) VALUES (?, ?, ?)",
                    (username, password, avatar),
                )
            conn.commit()

        self.end_json({"ok": True, "username": username, "avatar": avatar}, HTTPStatus.CREATED)

    def handle_post_score(self):
        try:
            payload = self.read_json()
        except json.JSONDecodeError:
            self.end_json({"error": "Invalid JSON body"}, HTTPStatus.BAD_REQUEST)
            return

        username = str(payload.get("username", "")).strip()
        result = str(payload.get("result", "")).strip().lower()
        date_time = str(payload.get("dateTime", "")).strip()

        try:
            attempts_used = int(payload.get("attemptsUsed", 0))
        except (TypeError, ValueError):
            attempts_used = 0

        if not username or result not in {"win", "lose"} or attempts_used <= 0:
            self.end_json({"error": "Invalid score payload"}, HTTPStatus.BAD_REQUEST)
            return

        if not date_time:
            date_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO scores (username, attempts_used, result, date_time)
                VALUES (?, ?, ?, ?)
                """,
                (username, attempts_used, result, date_time),
            )
            conn.commit()

        self.end_json({"ok": True}, HTTPStatus.CREATED)


if __name__ == "__main__":
    os.chdir(BASE_DIR)
    init_database()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), GuessItHandler)
    print("Serving on http://127.0.0.1:8000")
    server.serve_forever()
