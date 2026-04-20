from __future__ import annotations

import os
import random
import sqlite3
import logging
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

import bcrypt
from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash as check_legacy_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", BASE_DIR / "database.db"))
ENVIRONMENT = os.getenv("FLASK_ENV", "development")

DIFFICULTIES = {
    "easy": {"label": "Easy", "attempts": 12, "time_limit": 180, "multiplier": 1.0},
    "medium": {"label": "Medium", "attempts": 9, "time_limit": 120, "multiplier": 1.4},
    "hard": {"label": "Hard", "attempts": 7, "time_limit": 75, "multiplier": 1.9},
}
MODE_LABELS = {
    "classic": "Classic",
    "timer": "Timer Rush",
    "daily": "Daily Challenge",
    "practice": "Practice",
}
DEFAULT_AVATAR = "Ace"
AVATAR_OPTIONS = ["Ace", "Nova", "Orbit", "Pixel", "Blaze", "Echo"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("guessit")


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
    app.config["DEBUG"] = ENVIRONMENT == "development"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.getenv("FLASK_ENV") == "production"

    @app.before_request
    def load_current_user() -> None:
        g.user = None
        user_id = session.get("user_id")
        if user_id:
            g.user = fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
        app.logger.info("request path=%s method=%s user_id=%s", request.path, request.method, user_id)

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "current_user": g.user,
            "difficulty_options": DIFFICULTIES,
            "avatar_options": AVATAR_OPTIONS,
            "mode_labels": MODE_LABELS,
        }

    @app.route("/")
    def home() -> str:
        if not g.user:
            return redirect(url_for("login_page"))
        return render_template("home.html")

    @app.route("/login")
    def login_page() -> str:
        if g.user:
            return redirect(url_for("home"))
        return render_template("login.html")

    @app.route("/register")
    def register_page() -> str:
        if g.user:
            return redirect(url_for("home"))
        return render_template("register.html")

    @app.route("/forgot-password")
    def forgot_password_page() -> str:
        return render_template("forgot.html")

    @app.route("/game")
    @login_required
    def game_page() -> str:
        return render_template("game.html")

    @app.route("/practice")
    @login_required
    def practice_page() -> str:
        return render_template("practice.html")

    @app.route("/training")
    @login_required
    def training_page() -> str:
        return render_template("training.html")

    @app.route("/scoreboard")
    @login_required
    def scoreboard_page() -> str:
        return render_template("scoreboard.html")

    @app.route("/profile")
    @login_required
    def profile_page() -> str:
        return render_template("profile.html")

    @app.route("/history")
    @login_required
    def history_page() -> str:
        return render_template("history.html")

    @app.route("/healthz")
    def healthcheck() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.route("/api/register", methods=["POST"])
    def api_register():
        payload = get_request_data()
        username = normalize_username(payload.get("username"))
        password = str(payload.get("password", ""))
        avatar = sanitize_avatar(payload.get("avatar"))
        if len(username) < 3:
            return error_response("Username must be at least 3 characters long.")
        if len(password) < 8:
            return error_response("Password must be at least 8 characters long.")
        if fetch_one("SELECT id FROM users WHERE username = ?", (username,)):
            return error_response("Username already exists.", 409)

        password_hash = hash_password(password)
        user_columns = table_columns("users")
        with get_connection() as conn:
            if "password" in user_columns:
                cur = conn.execute(
                    """
                    INSERT INTO users (username, password, password_hash, avatar, created_at, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (username, password_hash, password_hash, avatar),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO users (username, password_hash, avatar, created_at, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (username, password_hash, avatar),
                )
            user_id = cur.lastrowid
            conn.commit()

        session.clear()
        session["user_id"] = user_id
        session["active_game_id"] = None
        return jsonify(
            {"message": "Account created successfully.", "user": serialize_user(fetch_user(user_id))}
        ), 201

    @app.route("/api/login", methods=["POST"])
    def api_login():
        payload = get_request_data()
        username = normalize_username(payload.get("username"))
        password = str(payload.get("password", ""))
        user = fetch_one("SELECT * FROM users WHERE username = ?", (username,))
        if not user or not verify_password(user, password):
            return error_response("Invalid username or password.", 401)

        with get_connection() as conn:
            conn.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],))
            conn.commit()

        session.clear()
        session["user_id"] = user["id"]
        session["active_game_id"] = None
        return jsonify({"message": "Login successful.", "user": serialize_user(fetch_user(user["id"]))})

    @app.route("/api/forgot-password", methods=["POST"])
    def api_forgot_password():
        payload = get_request_data()
        username = normalize_username(payload.get("username"))
        password = str(payload.get("password", ""))
        confirm_password = str(payload.get("confirmPassword", ""))
        if len(username) < 3:
            return error_response("Username must be at least 3 characters long.")
        if len(password) < 8:
            return error_response("Password must be at least 8 characters long.")
        if password != confirm_password:
            return error_response("Password confirmation does not match.")

        user = fetch_one("SELECT id FROM users WHERE username = ?", (username,))
        if not user:
            return error_response("Username not found.", 404)

        new_password_hash = hash_password(password)
        user_columns = table_columns("users")
        with get_connection() as conn:
            if "password" in user_columns:
                conn.execute(
                    """
                    UPDATE users
                    SET password = ?, password_hash = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (new_password_hash, new_password_hash, user["id"]),
                )
            else:
                conn.execute(
                    "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_password_hash, user["id"]),
                )
            conn.commit()

        session.clear()
        return jsonify({"message": "Password updated successfully. Please sign in."})

    @app.route("/api/logout", methods=["POST"])
    @login_required
    def api_logout():
        session.clear()
        return jsonify({"message": "Logged out."})

    @app.route("/api/me")
    def api_me():
        if not g.user:
            return jsonify({"authenticated": False, "user": None})
        active_game = fetch_active_game(g.user["id"])
        return jsonify(
            {
                "authenticated": True,
                "user": serialize_user(g.user),
                "activeGame": serialize_game(active_game) if active_game else None,
            }
        )

    @app.route("/api/profile/avatar", methods=["POST"])
    @login_required
    def api_update_avatar():
        payload = get_request_data()
        avatar = sanitize_avatar(payload.get("avatar"))
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET avatar = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (avatar, g.user["id"]),
            )
            conn.commit()
        return jsonify({"message": "Avatar updated.", "user": serialize_user(fetch_user(g.user["id"]))})

    @app.route("/api/participants")
    @login_required
    def api_participants():
        rows = fetch_all("SELECT username, avatar, created_at FROM users ORDER BY LOWER(username) ASC")
        return jsonify({"participants": [dict(row) for row in rows]})

    @app.route("/api/game/start", methods=["POST"])
    @login_required
    def api_game_start():
        payload = get_request_data()
        difficulty = str(payload.get("difficulty", "medium")).lower()
        mode = str(payload.get("mode", "classic")).lower()
        force_restart = bool(payload.get("forceRestart"))
        if difficulty not in DIFFICULTIES:
            return error_response("Invalid difficulty.")
        if mode not in MODE_LABELS:
            return error_response("Invalid mode.")

        existing = fetch_active_game(g.user["id"])
        if existing and not force_restart:
            return jsonify({"message": "Resuming active game.", "game": serialize_game(existing)})
        if existing and force_restart:
            end_game(existing["id"], "abandoned", existing["attempts_used"])

        config = DIFFICULTIES[difficulty]
        secret_number = generate_secret_number(daily_seed(mode) if mode == "daily" else None)
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO game_history (
                    user_id, secret_number, difficulty, mode, max_attempts, attempts_used,
                    status, hint_count, started_at, time_limit_seconds, is_daily, challenge_date, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, 'active', 0, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    g.user["id"],
                    secret_number,
                    difficulty,
                    mode,
                    config["attempts"],
                    now_utc().isoformat(),
                    config["time_limit"] if mode == "timer" else None,
                    1 if mode == "daily" else 0,
                    date.today().isoformat() if mode == "daily" else None,
                ),
            )
            game_id = cur.lastrowid
            conn.commit()
        session["active_game_id"] = game_id
        game = fetch_game(game_id, g.user["id"])
        return jsonify({"message": "Game started.", "game": serialize_game(game)})

    @app.route("/api/game/guess", methods=["POST"])
    @login_required
    def api_game_guess():
        payload = get_request_data()
        guess = str(payload.get("guess", "")).strip()
        game = fetch_active_game(g.user["id"])
        if not game:
            return error_response("No active game. Start a new one first.", 404)

        validation_error = validate_guess(guess)
        if validation_error:
            return error_response(validation_error)

        expiry = check_game_expiry(game)
        if expiry:
            final_game = finalize_game(game, "lose")
            expiry["game"] = serialize_game(final_game)
            expiry["attempts"] = fetch_attempt_payload(final_game["id"])
            return jsonify(expiry), 410

        attempts_used = game["attempts_used"] + 1
        exact_matches, partial_matches = score_guess(guess, game["secret_number"])
        direction_hint = direction_for_guess(guess, game["secret_number"])
        ai_hint = build_ai_hint(game, exact_matches, partial_matches, direction_hint)

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO guess_attempts (
                    game_id, attempt_number, guess_value, exact_matches, partial_matches,
                    direction_hint, ai_hint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (game["id"], attempts_used, guess, exact_matches, partial_matches, direction_hint, ai_hint),
            )
            conn.execute(
                "UPDATE game_history SET attempts_used = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (attempts_used, game["id"]),
            )
            conn.commit()

        updated_game = fetch_game(game["id"], g.user["id"])
        result = "active"
        message = "Keep going."
        if guess == updated_game["secret_number"]:
            result = "win"
            message = "Exact match. You cracked it."
            updated_game = finalize_game(updated_game, "win")
        elif attempts_used >= updated_game["max_attempts"]:
            result = "lose"
            message = "No attempts remaining."
            updated_game = finalize_game(updated_game, "lose")

        return jsonify(
            {
                "message": message,
                "result": result,
                "feedback": {
                    "exactMatches": exact_matches,
                    "partialMatches": partial_matches,
                    "direction": direction_hint,
                    "aiHint": ai_hint,
                },
                "game": serialize_game(updated_game),
                "attempts": fetch_attempt_payload(updated_game["id"]),
            }
        )

    @app.route("/api/game/replay", methods=["POST"])
    @login_required
    def api_game_replay():
        payload = get_request_data()
        active = fetch_active_game(g.user["id"])
        if active:
            end_game(active["id"], "abandoned", active["attempts_used"])
        payload["forceRestart"] = True
        request._cached_json = {False: payload, True: payload}
        return api_game_start()

    @app.route("/api/game/current")
    @login_required
    def api_game_current():
        game = fetch_active_game(g.user["id"])
        if not game:
            return jsonify({"game": None, "attempts": []})
        expiry = check_game_expiry(game)
        if expiry:
            final_game = finalize_game(game, "lose")
            return jsonify({"game": serialize_game(final_game), "attempts": fetch_attempt_payload(final_game["id"]), "timedOut": True})
        return jsonify({"game": serialize_game(game), "attempts": fetch_attempt_payload(game["id"])})

    @app.route("/api/scoreboard")
    @login_required
    def api_scoreboard():
        difficulty = request.args.get("difficulty", "").strip().lower()
        where = ["s.result = 'win'"]
        params: list[Any] = []
        if difficulty in DIFFICULTIES:
            where.append("s.difficulty = ?")
            params.append(difficulty)
        rows = fetch_all(
            f"""
            SELECT s.id, u.username, u.avatar, s.difficulty, s.mode, s.attempts_used, s.max_attempts,
                   s.elapsed_seconds, s.score_value, s.created_at
            FROM scores s
            JOIN users u ON u.id = s.user_id
            WHERE {' AND '.join(where)}
            ORDER BY s.score_value DESC, s.attempts_used ASC, s.elapsed_seconds ASC, s.created_at DESC
            LIMIT 25
            """,
            tuple(params),
        )
        return jsonify({"entries": [serialize_score(row) for row in rows]})

    @app.route("/api/history")
    @login_required
    def api_history():
        rows = fetch_all(
            """
            SELECT id, difficulty, mode, status, attempts_used, max_attempts, ended_at, started_at, secret_number
            FROM game_history
            WHERE user_id = ? AND status IN ('win', 'lose')
            ORDER BY COALESCE(ended_at, started_at) DESC
            LIMIT 20
            """,
            (g.user["id"],),
        )
        history = []
        for row in rows:
            item = dict(row)
            item["attempts"] = fetch_attempt_payload(row["id"])
            history.append(item)
        return jsonify({"history": history})

    @app.route("/api/stats")
    @login_required
    def api_stats():
        overview = fetch_one(
            """
            SELECT
                COUNT(*) AS total_games,
                SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN status = 'lose' THEN 1 ELSE 0 END) AS losses,
                AVG(CASE WHEN status = 'win' THEN attempts_used END) AS average_attempts
            FROM game_history
            WHERE user_id = ? AND status IN ('win', 'lose')
            """,
            (g.user["id"],),
        )
        best_by_difficulty = fetch_all(
            """
            SELECT difficulty, MAX(score_value) AS best_score
            FROM scores
            WHERE user_id = ?
            GROUP BY difficulty
            ORDER BY best_score DESC
            """,
            (g.user["id"],),
        )
        recent_games = fetch_all(
            """
            SELECT difficulty, mode, status, attempts_used, max_attempts, ended_at
            FROM game_history
            WHERE user_id = ? AND status IN ('win', 'lose')
            ORDER BY COALESCE(ended_at, started_at) DESC
            LIMIT 8
            """,
            (g.user["id"],),
        )
        daily_result = fetch_one(
            """
            SELECT status, attempts_used, ended_at
            FROM game_history
            WHERE user_id = ? AND is_daily = 1 AND challenge_date = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (g.user["id"], date.today().isoformat()),
        )
        history_rows = fetch_all(
            """
            SELECT status, difficulty, mode, attempts_used, ended_at, started_at
            FROM game_history
            WHERE user_id = ? AND status IN ('win', 'lose')
            ORDER BY COALESCE(ended_at, started_at) ASC
            """,
            (g.user["id"],),
        )
        streaks = calculate_streaks(history_rows)
        achievements = build_achievements(
            total_games=int(overview["total_games"] or 0),
            wins=int(overview["wins"] or 0),
            average_attempts=float(overview["average_attempts"] or 0),
            streaks=streaks,
            history_rows=history_rows,
            daily_result=daily_result,
        )
        return jsonify(
            {
                "overview": {
                    "totalGames": int(overview["total_games"] or 0),
                    "wins": int(overview["wins"] or 0),
                    "losses": int(overview["losses"] or 0),
                    "averageAttempts": round(float(overview["average_attempts"] or 0), 2),
                },
                "bestByDifficulty": [dict(row) for row in best_by_difficulty],
                "recentGames": [dict(row) for row in recent_games],
                "dailyChallenge": dict(daily_result) if daily_result else None,
                "streaks": streaks,
                "achievements": achievements,
            }
        )

    @app.route("/api/daily-challenge")
    @login_required
    def api_daily_challenge():
        today = date.today().isoformat()
        existing = fetch_one(
            """
            SELECT * FROM game_history
            WHERE user_id = ? AND is_daily = 1 AND challenge_date = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (g.user["id"], today),
        )
        secret = generate_secret_number(daily_seed("daily"))
        return jsonify(
            {
                "date": today,
                "difficulty": "hard",
                "mode": "daily",
                "previewHint": daily_preview_hint(secret),
                "alreadyCompleted": bool(existing and existing["status"] in ("win", "lose")),
                "hasActiveRun": bool(existing and existing["status"] == "active"),
            }
        )

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return error_response("Not found.", 404)
        return render_template("404.html"), 404

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        app.logger.exception("unhandled_error path=%s method=%s", request.path, request.method)
        if request.path.startswith("/api/"):
            return error_response("Internal server error. Check server logs for details.", 500)
        return render_template("500.html"), 500

    return app


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return error_response("Authentication required.", 401)
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)

    return wrapped


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_connection() -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    except sqlite3.Error as exc:
        logger.exception("database_connection_failed path=%s", DATABASE_PATH)
        raise RuntimeError(f"Database connection failed for {DATABASE_PATH}") from exc


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    try:
        with get_connection() as conn:
            return conn.execute(query, params).fetchone()
    except sqlite3.Error as exc:
        logger.exception("fetch_one_failed query=%s params=%s", query, params)
        raise RuntimeError("Database read failed.") from exc


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    try:
        with get_connection() as conn:
            return conn.execute(query, params).fetchall()
    except sqlite3.Error as exc:
        logger.exception("fetch_all_failed query=%s params=%s", query, params)
        raise RuntimeError("Database read failed.") from exc


def fetch_user(user_id: int) -> sqlite3.Row:
    user = fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user:
        abort(404)
    return user


def fetch_game(game_id: int, user_id: int) -> sqlite3.Row | None:
    return fetch_one("SELECT * FROM game_history WHERE id = ? AND user_id = ?", (game_id, user_id))


def fetch_active_game(user_id: int) -> sqlite3.Row | None:
    game_id = session.get("active_game_id")
    if game_id:
        game = fetch_game(game_id, user_id)
        if game and game["status"] == "active":
            return game
    game = fetch_one(
        "SELECT * FROM game_history WHERE user_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    if game:
        session["active_game_id"] = game["id"]
    return game


def fetch_attempts(game_id: int) -> list[sqlite3.Row]:
    return fetch_all(
        """
        SELECT attempt_number, guess_value, exact_matches, partial_matches, direction_hint, ai_hint, created_at
        FROM guess_attempts
        WHERE game_id = ?
        ORDER BY attempt_number ASC
        """,
        (game_id,),
    )


def fetch_attempt_payload(game_id: int) -> list[dict[str, Any]]:
    return [serialize_attempt(row) for row in fetch_attempts(game_id)]


def table_columns(table: str) -> set[str]:
    with get_connection() as conn:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def get_request_data() -> dict[str, Any]:
    if request.is_json:
        return request.get_json(silent=True) or {}
    if request.form:
        return {key: request.form.get(key, "") for key in request.form.keys()}
    return {}


def normalize_username(raw: Any) -> str:
    return str(raw or "").strip().lower()


def sanitize_avatar(raw: Any) -> str:
    value = str(raw or "").strip()
    return value if value in AVATAR_OPTIONS else DEFAULT_AVATAR


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(user: sqlite3.Row, password: str) -> bool:
    stored = user["password_hash"] or ""
    if stored.startswith("$2"):
        return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
    if stored and check_legacy_password_hash(stored, password):
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (hash_password(password), user["id"]),
            )
            conn.commit()
        return True
    return False

def generate_secret_number(seed_value: str | None = None) -> str:
    rng = random.Random(seed_value) if seed_value else random.SystemRandom()
    return "".join(rng.sample(list("0123456789"), 3))


def daily_seed(mode: str) -> str:
    return f"{mode}:{date.today().isoformat()}:{os.getenv('DAILY_SALT', 'guessit')}"


def validate_guess(guess: str) -> str | None:
    if len(guess) != 3 or not guess.isdigit():
        return "Enter a three-digit number."
    if len(set(guess)) != 3:
        return "Use three unique digits for every guess."
    return None


def score_guess(guess: str, secret: str) -> tuple[int, int]:
    exact = sum(1 for index, digit in enumerate(guess) if secret[index] == digit)
    partial = sum(1 for digit in guess if digit in secret) - exact
    return exact, partial


def direction_for_guess(guess: str, secret: str) -> str:
    if int(guess) < int(secret):
        return "higher"
    if int(guess) > int(secret):
        return "lower"
    return "correct"


def parse_dt(raw: str | None) -> datetime:
    if not raw:
        return now_utc()
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def calculate_elapsed_seconds(game: sqlite3.Row) -> int:
    start = parse_dt(game["started_at"])
    end = parse_dt(game["ended_at"]) if game["ended_at"] else now_utc()
    return max(0, int((end - start).total_seconds()))


def check_game_expiry(game: sqlite3.Row) -> dict[str, Any] | None:
    if game["mode"] != "timer" or not game["time_limit_seconds"]:
        return None
    elapsed = calculate_elapsed_seconds(game)
    if elapsed <= game["time_limit_seconds"]:
        return None
    return {
        "message": "Timer expired.",
        "result": "lose",
        "feedback": {
            "exactMatches": 0,
            "partialMatches": 0,
            "direction": "timeout",
            "aiHint": "The timer ran out. Start a fresh run and narrow the range earlier.",
        },
        "timedOut": True,
    }


def build_ai_hint(game: sqlite3.Row, exact: int, partial: int, direction: str) -> str:
    attempts_left = game["max_attempts"] - (game["attempts_used"] + 1)
    if exact == 3:
        return "All three digits are correct and already aligned."
    if exact == 0 and partial == 0:
        return "None of those digits belong to the answer. Replace all three."
    if exact == 0 and partial > 0:
        return f"{partial} digit(s) belong to the secret, but all are misplaced."
    if exact > 0 and partial == 0:
        return f"{exact} digit(s) are locked in place. Keep those positions stable."
    if attempts_left <= 2:
        return f"Only {attempts_left} attempt(s) left. Change one slot at a time and aim {direction}."
    return f"You have {exact} exact and {partial} misplaced digits. Aim {direction} next."


def calculate_streaks(history_rows: list[sqlite3.Row]) -> dict[str, int]:
    current_win = 0
    best_win = 0
    running_win = 0
    for row in history_rows:
        if row["status"] == "win":
            running_win += 1
            best_win = max(best_win, running_win)
        else:
            running_win = 0
    for row in reversed(history_rows):
        if row["status"] == "win":
            current_win += 1
        else:
            break
    return {
        "currentWinStreak": current_win,
        "bestWinStreak": best_win,
    }


def build_achievements(
    total_games: int,
    wins: int,
    average_attempts: float,
    streaks: dict[str, int],
    history_rows: list[sqlite3.Row],
    daily_result: sqlite3.Row | None,
) -> list[dict[str, Any]]:
    hard_wins = sum(1 for row in history_rows if row["status"] == "win" and row["difficulty"] == "hard")
    timer_wins = sum(1 for row in history_rows if row["status"] == "win" and row["mode"] == "timer")
    efficient_wins = sum(1 for row in history_rows if row["status"] == "win" and row["attempts_used"] <= 3)
    unlocked = [
        {
            "key": "rookie",
            "label": "Rookie",
            "description": "Finish your first match.",
            "earned": total_games >= 1,
        },
        {
            "key": "hot_streak",
            "label": "Hot Streak",
            "description": "Win 3 games in a row.",
            "earned": streaks["bestWinStreak"] >= 3,
        },
        {
            "key": "cold_reader",
            "label": "Cold Reader",
            "description": "Win in 3 attempts or fewer.",
            "earned": efficient_wins >= 1,
        },
        {
            "key": "night_shift",
            "label": "Night Shift",
            "description": "Beat Timer Rush once.",
            "earned": timer_wins >= 1,
        },
        {
            "key": "hard_target",
            "label": "Hard Target",
            "description": "Win 5 hard-mode games.",
            "earned": hard_wins >= 5,
        },
        {
            "key": "daily_lock",
            "label": "Daily Lock",
            "description": "Complete today's daily challenge.",
            "earned": bool(daily_result and daily_result["status"] in ("win", "lose")),
        },
        {
            "key": "clean_solver",
            "label": "Clean Solver",
            "description": "Keep your average winning attempts under 4.5.",
            "earned": wins >= 3 and average_attempts > 0 and average_attempts <= 4.5,
        },
    ]
    return unlocked


def daily_preview_hint(secret: str) -> str:
    even_digits = sum(int(digit) % 2 == 0 for digit in secret)
    return f"Today's challenge contains {even_digits} even digit(s)."


def calculate_score(game: sqlite3.Row, elapsed_seconds: int) -> int:
    config = DIFFICULTIES[game["difficulty"]]
    base_score = int(1000 * config["multiplier"])
    attempts_bonus = max(0, game["max_attempts"] - game["attempts_used"]) * 55
    time_cap = config["time_limit"] or 180
    speed_bonus = max(0, time_cap - min(elapsed_seconds, time_cap)) * 2
    mode_bonus = 150 if game["mode"] == "timer" else 180 if game["mode"] == "daily" else 0
    return base_score + attempts_bonus + speed_bonus + mode_bonus


def end_game(game_id: int, status: str, attempts_used: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE game_history
            SET status = ?, attempts_used = ?, ended_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, attempts_used, game_id),
        )
        conn.commit()


def finalize_game(game: sqlite3.Row, result: str) -> sqlite3.Row:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE game_history
            SET status = ?, ended_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (result, game["id"]),
        )
        conn.commit()
    final_game = fetch_game(game["id"], game["user_id"])
    elapsed_seconds = calculate_elapsed_seconds(final_game)
    with get_connection() as conn:
        conn.execute("UPDATE game_history SET elapsed_seconds = ? WHERE id = ?", (elapsed_seconds, final_game["id"]))
        if result == "win":
            score_value = calculate_score(final_game, elapsed_seconds)
            conn.execute(
                """
                INSERT INTO scores (
                    user_id, game_id, difficulty, mode, result, attempts_used, max_attempts,
                    elapsed_seconds, score_value, created_at, username
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (
                    final_game["user_id"],
                    final_game["id"],
                    final_game["difficulty"],
                    final_game["mode"],
                    result,
                    final_game["attempts_used"],
                    final_game["max_attempts"],
                    elapsed_seconds,
                    score_value,
                    fetch_user(final_game["user_id"])["username"],
                ),
            )
        conn.commit()
    session["active_game_id"] = None
    return fetch_game(game["id"], game["user_id"])


def serialize_user(user: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "avatar": user["avatar"],
        "createdAt": user["created_at"],
        "lastLoginAt": user["last_login_at"],
    }


def serialize_game(game: sqlite3.Row) -> dict[str, Any]:
    elapsed = game["elapsed_seconds"] if game["elapsed_seconds"] is not None else calculate_elapsed_seconds(game)
    return {
        "id": game["id"],
        "difficulty": game["difficulty"],
        "mode": game["mode"],
        "status": game["status"],
        "maxAttempts": game["max_attempts"],
        "attemptsUsed": game["attempts_used"],
        "attemptsLeft": max(0, game["max_attempts"] - game["attempts_used"]),
        "timeLimitSeconds": game["time_limit_seconds"],
        "elapsedSeconds": elapsed,
        "isDaily": bool(game["is_daily"]),
        "challengeDate": game["challenge_date"],
        "endedAt": game["ended_at"],
        "secretRevealed": game["secret_number"] if game["status"] in ("win", "lose") else None,
    }


def serialize_attempt(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "attemptNumber": row["attempt_number"],
        "guess": row["guess_value"],
        "exactMatches": row["exact_matches"],
        "partialMatches": row["partial_matches"],
        "direction": row["direction_hint"],
        "aiHint": row["ai_hint"],
        "createdAt": row["created_at"],
    }


def serialize_score(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "avatar": row["avatar"],
        "difficulty": row["difficulty"],
        "mode": row["mode"],
        "attemptsUsed": row["attempts_used"],
        "maxAttempts": row["max_attempts"],
        "elapsedSeconds": row["elapsed_seconds"],
        "scoreValue": row["score_value"],
        "createdAt": row["created_at"],
    }


def error_response(message: str, status: int = 400):
    return jsonify({"error": message}), status


def ensure_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    column_name = definition.split()[0]
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column_name not in columns:
        safe_definition = definition.replace(" NOT NULL DEFAULT CURRENT_TIMESTAMP", "")
        safe_definition = safe_definition.replace(" DEFAULT CURRENT_TIMESTAMP", "")
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {safe_definition}")


def init_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT 'Ace',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS game_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                secret_number TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                mode TEXT NOT NULL,
                max_attempts INTEGER NOT NULL,
                attempts_used INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                hint_count INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT,
                elapsed_seconds INTEGER,
                time_limit_seconds INTEGER,
                is_daily INTEGER NOT NULL DEFAULT 0,
                challenge_date TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS guess_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                attempt_number INTEGER NOT NULL,
                guess_value TEXT NOT NULL,
                exact_matches INTEGER NOT NULL,
                partial_matches INTEGER NOT NULL,
                direction_hint TEXT NOT NULL,
                ai_hint TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (game_id) REFERENCES game_history(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_id INTEGER,
                difficulty TEXT NOT NULL DEFAULT 'medium',
                mode TEXT NOT NULL DEFAULT 'classic',
                result TEXT NOT NULL DEFAULT 'win',
                attempts_used INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL DEFAULT 10,
                elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                score_value INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                username TEXT,
                date_time TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (game_id) REFERENCES game_history(id) ON DELETE SET NULL
            )
            """
        )

        ensure_column(conn, "users", "password_hash TEXT NOT NULL DEFAULT ''")
        ensure_column(conn, "users", "avatar TEXT NOT NULL DEFAULT 'Ace'")
        ensure_column(conn, "users", "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")
        ensure_column(conn, "users", "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")
        ensure_column(conn, "users", "last_login_at TEXT")

        ensure_column(conn, "scores", "user_id INTEGER")
        ensure_column(conn, "scores", "game_id INTEGER")
        ensure_column(conn, "scores", "difficulty TEXT NOT NULL DEFAULT 'medium'")
        ensure_column(conn, "scores", "mode TEXT NOT NULL DEFAULT 'classic'")
        ensure_column(conn, "scores", "max_attempts INTEGER NOT NULL DEFAULT 10")
        ensure_column(conn, "scores", "elapsed_seconds INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "scores", "score_value INTEGER NOT NULL DEFAULT 0")
        ensure_column(conn, "scores", "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "password" in columns:
            conn.execute(
                """
                UPDATE users
                SET password_hash = CASE WHEN password_hash = '' THEN password ELSE password_hash END
                WHERE password IS NOT NULL AND password != ''
                """
            )

        conn.execute(
            """
            UPDATE users
            SET avatar = COALESCE(NULLIF(avatar, ''), ?),
                created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
                updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
            """,
            (DEFAULT_AVATAR,),
        )
        conn.execute(
            """
            UPDATE scores
            SET created_at = COALESCE(created_at, date_time, CURRENT_TIMESTAMP),
                difficulty = COALESCE(NULLIF(difficulty, ''), 'medium'),
                mode = COALESCE(NULLIF(mode, ''), 'classic'),
                max_attempts = COALESCE(max_attempts, 10),
                elapsed_seconds = COALESCE(elapsed_seconds, 0),
                score_value = COALESCE(score_value, 0),
                result = COALESCE(NULLIF(result, ''), 'win')
            """
        )
        conn.execute(
            """
            UPDATE scores
            SET user_id = (
                SELECT id FROM users WHERE users.username = scores.username LIMIT 1
            )
            WHERE user_id IS NULL AND username IS NOT NULL
            """
        )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_game_history_user_status ON game_history(user_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_game_history_daily ON game_history(user_id, challenge_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_guess_attempts_game_attempt ON guess_attempts(game_id, attempt_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_ranking ON scores(score_value DESC, attempts_used ASC, elapsed_seconds ASC)")
        conn.commit()


app = create_app()
init_database()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=ENVIRONMENT == "development")
