# Three Digit Number Guessing Game

Deployable Flask + SQLite game with bcrypt authentication, session-backed gameplay, ranked scores, and a responsive frontend.

## Features
- Flask backend with server-rendered routes and JSON APIs
- SQLite schema for `users`, `game_history`, `guess_attempts`, and `scores`
- bcrypt password hashing and cookie session management
- Unique 3-digit secret generation
- Exact digit / misplaced digit hint system
- Difficulty levels: Easy, Medium, Hard
- Timer mode, daily challenge mode, practice mode, replay flow
- Leaderboard and user statistics dashboard
- Mobile-friendly frontend with animated feedback

## API
- `POST /api/register`
- `POST /api/login`
- `POST /api/logout`
- `GET /api/me`
- `POST /api/game/start`
- `POST /api/game/guess`
- `GET /api/game/current`
- `GET /api/scoreboard`
- `GET /api/stats`
- `GET /api/daily-challenge`

## Local development
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Environment variables
Copy `.env.example` and set:
- `SECRET_KEY`: long random string
- `DAILY_SALT`: salt for deterministic daily puzzle generation
- `DATABASE_PATH`: SQLite file path
- `FLASK_ENV`: `production` on hosted environments
- `PORT`: platform-provided port on Render/Railway

## Render deployment
1. Push the repository to GitHub.
2. Create a new Render Web Service.
3. Select the repository.
4. Use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
5. Add environment variables:
   - `SECRET_KEY`
   - `DAILY_SALT`
   - `DATABASE_PATH` set to `/opt/render/project/src/database.db`
   - `FLASK_ENV=production`
6. Deploy.

## Railway deployment
1. Create a new Railway project from the repository.
2. Railway detects `Procfile`; if needed set start command to `gunicorn app:app`.
3. Add `SECRET_KEY`, `DAILY_SALT`, `DATABASE_PATH`, and `FLASK_ENV=production`.
4. Deploy and open the generated URL.

## Notes
- SQLite is suitable for small deployments. For higher write volume, move to Postgres.
- Multiplayer is intentionally left optional; the current architecture supports adding rooms and websockets later.
- The old static GitHub Pages flow is no longer the primary deployment target.
