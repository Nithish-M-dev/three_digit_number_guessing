const state = {
  me: window.APP_CONFIG?.user || null,
  game: null,
  attempts: [],
  timerId: null,
  selectedAvatar: window.APP_CONFIG?.user?.avatar || null,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    credentials: 'same-origin',
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.message || 'Request failed');
  return data;
}

function toast(message, type = 'success') {
  const stack = document.getElementById('toast-stack');
  if (!stack) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function bodyPage() {
  return document.body?.dataset?.page || '';
}

function formatSeconds(total) {
  if (total == null) return '--';
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function setNavUser(user) {
  if (!user) return;
  const name = document.getElementById('nav-username');
  const avatar = document.getElementById('nav-avatar');
  if (name) name.textContent = user.username;
  if (avatar) avatar.textContent = user.avatar;
}

function setSelectedAvatar(avatar, scope = document) {
  state.selectedAvatar = avatar;
  scope.querySelectorAll('.avatar-chip').forEach((el) => {
    el.classList.toggle('active', el.textContent === avatar);
  });
}

function populateAvatarGrid(target, avatars) {
  if (!target) return;
  target.innerHTML = '';
  avatars.forEach((avatar) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = `avatar-chip ${avatar === state.selectedAvatar ? 'active' : ''}`;
    chip.textContent = avatar;
    chip.addEventListener('click', () => setSelectedAvatar(avatar, target));
    target.appendChild(chip);
  });
}

async function saveAvatarSelection() {
  const data = await api('/api/profile/avatar', { method: 'POST', body: JSON.stringify({ avatar: state.selectedAvatar }) });
  state.me = data.user;
  setNavUser(data.user);
  return data;
}

async function loadMe() {
  const data = await api('/api/me');
  state.me = data.user;
  if (data.user) setNavUser(data.user);
  return data;
}

async function handleAuthForm(formId, endpoint) {
  const form = document.getElementById(formId);
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());
    try {
      await api(endpoint, { method: 'POST', body: JSON.stringify(payload) });
      window.location.href = '/';
    } catch (error) {
      toast(error.message, 'error');
    }
  });
}

async function handleForgotPasswordForm() {
  const form = document.getElementById('forgot-form');
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());
    try {
      const data = await api('/api/forgot-password', { method: 'POST', body: JSON.stringify(payload) });
      toast(data.message || 'Password updated.');
      window.location.href = '/login';
    } catch (error) {
      toast(error.message, 'error');
    }
  });
}

function initPasswordToggles() {
  document.querySelectorAll('[data-password-toggle]').forEach((toggle) => {
    toggle.addEventListener('click', () => {
      const field = toggle.closest('.password-field');
      const input = field?.querySelector('input');
      if (!input) return;
      const visible = input.type === 'text';
      input.type = visible ? 'password' : 'text';
      toggle.textContent = visible ? 'Show' : 'Hide';
    });
  });
}

function initLogout() {
  const button = document.getElementById('logout-button');
  if (!button) return;
  button.addEventListener('click', async () => {
    await api('/api/logout', { method: 'POST' });
    window.location.href = '/login';
  });
}

async function loadStatsInto(prefix = 'stat') {
  const stats = await api('/api/stats');
  const overview = stats.overview;
  const streaks = stats.streaks || {};
  const bind = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };
  bind(`${prefix}-total-games`, overview.totalGames);
  bind(`${prefix}-wins`, overview.wins);
  bind(`${prefix}-losses`, overview.losses);
  bind(`${prefix}-average-attempts`, overview.averageAttempts);
  bind(`${prefix}-current-streak`, streaks.currentWinStreak || 0);
  bind(`${prefix}-best-streak`, streaks.bestWinStreak || 0);
  const recent = document.getElementById(prefix === 'stat' ? 'recent-games' : 'profile-recent-games');
  if (recent) {
    recent.innerHTML = '';
    stats.recentGames.forEach((game) => {
      const item = document.createElement('div');
      item.innerHTML = `<strong>${game.difficulty} / ${game.mode}</strong><div class="history-meta"><span>${game.status}</span><span>${game.attempts_used}/${game.max_attempts} attempts</span><span>${game.ended_at || 'recent'}</span></div>`;
      recent.appendChild(item);
    });
  }
  const best = document.getElementById('profile-best-scores');
  if (best) {
    best.innerHTML = '';
    stats.bestByDifficulty.forEach((row) => {
      const pill = document.createElement('span');
      pill.className = 'best-pill';
      pill.textContent = `${row.difficulty}: ${row.best_score}`;
      best.appendChild(pill);
    });
  }
  const achievementTarget = document.getElementById(prefix === 'stat' ? 'home-achievements' : 'profile-achievements');
  if (achievementTarget) {
    achievementTarget.innerHTML = '';
    (stats.achievements || []).forEach((achievement) => {
      const badge = document.createElement('span');
      badge.className = `player-pill achievement-pill ${achievement.earned ? 'earned' : 'locked'}`;
      badge.title = achievement.description;
      badge.textContent = achievement.earned ? `Unlocked: ${achievement.label}` : `Locked: ${achievement.label}`;
      achievementTarget.appendChild(badge);
    });
  }
}

async function loadDailyPreview() {
  const daily = await api('/api/daily-challenge');
  const summary = document.getElementById('daily-summary');
  const preview = document.getElementById('daily-preview');
  const dateEl = document.getElementById('daily-date');
  if (summary) summary.textContent = daily.previewHint;
  if (preview) preview.textContent = `${daily.previewHint} ${daily.alreadyCompleted ? 'You already finished today\'s run.' : ''}`;
  if (dateEl) dateEl.textContent = daily.date;
}

async function startGame(mode, difficulty, forceRestart = false) {
  const payload = { mode, difficulty, forceRestart };
  await api('/api/game/start', { method: 'POST', body: JSON.stringify(payload) });
  window.location.href = '/game';
}

function initStartButtons() {
  document.querySelectorAll('[data-start-game]').forEach((button) => {
    button.addEventListener('click', async () => {
      const mode = button.getAttribute('data-start-game');
      const difficulty = button.getAttribute('data-difficulty') || 'medium';
      try {
        await startGame(mode, difficulty, true);
      } catch (error) {
        toast(error.message, 'error');
      }
    });
  });
}

function initNavigationButtons() {
  document.querySelectorAll('[data-nav-href]').forEach((button) => {
    button.addEventListener('click', () => {
      const href = button.getAttribute('data-nav-href');
      if (href) window.location.href = href;
    });
  });
}

function initAvatarModal() {
  const modal = document.getElementById('avatar-modal');
  const openButton = document.getElementById('nav-avatar-button');
  const closeButton = document.getElementById('close-avatar-modal');
  const saveButton = document.getElementById('quick-save-avatar-button');
  const avatarGrid = document.getElementById('quick-avatar-grid');
  const avatars = window.APP_CONFIG?.avatars || [];
  if (!modal || !openButton || !avatarGrid) return;

  const openModal = () => {
    populateAvatarGrid(avatarGrid, avatars);
    modal.hidden = false;
  };
  const closeModal = () => {
    modal.hidden = true;
  };

  openButton.addEventListener('click', openModal);
  closeButton?.addEventListener('click', closeModal);
  modal.addEventListener('click', (event) => {
    if (event.target === modal) closeModal();
  });
  saveButton?.addEventListener('click', async () => {
    try {
      await saveAvatarSelection();
      closeModal();
      toast('Avatar updated.');
    } catch (error) {
      toast(error.message, 'error');
    }
  });
}

function renderAttempts(attempts) {
  const history = document.getElementById('history-list');
  if (!history) return;
  history.innerHTML = '';
  attempts.slice().reverse().forEach((attempt) => {
    const item = document.createElement('div');
    item.className = 'history-item';
    item.innerHTML = `<strong>#${attempt.attemptNumber} - ${attempt.guess}</strong><div class="history-meta"><span>Exact: ${attempt.exactMatches}</span><span>Misplaced: ${attempt.partialMatches}</span><span>${attempt.direction}</span></div><p>${attempt.aiHint}</p>`;
    history.appendChild(item);
  });
}

function renderGame(game, feedbackText) {
  state.game = game;
  const bind = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
  bind('attempts-left', game ? game.attemptsLeft : 0);
  bind('game-difficulty', game ? game.difficulty : '-');
  bind('game-mode', game ? game.mode : '-');
  const meter = document.getElementById('meter-fill');
  if (meter && game) meter.style.width = `${(game.attemptsUsed / game.maxAttempts) * 100}%`;
  const feedback = document.getElementById('feedback-text');
  if (feedback && feedbackText) feedback.textContent = feedbackText;
  syncTimer();
}

function syncTimer() {
  const timerEl = document.getElementById('game-timer');
  clearInterval(state.timerId);
  if (!timerEl || !state.game) return;
  const update = () => {
    if (!state.game.timeLimitSeconds) {
      timerEl.textContent = formatSeconds(state.game.elapsedSeconds || 0);
      return;
    }
    const remaining = Math.max(0, state.game.timeLimitSeconds - (state.game.elapsedSeconds || 0));
    timerEl.textContent = formatSeconds(remaining);
    state.game.elapsedSeconds += 1;
  };
  update();
  state.timerId = setInterval(update, 1000);
}

async function hydrateGame() {
  const data = await api('/api/game/current');
  if (!data.game) return;
  state.attempts = data.attempts || [];
  renderGame(data.game, data.timedOut ? 'Timer expired. Start a new run.' : 'Game loaded.');
  renderAttempts(state.attempts);
}

function initGamePage() {
  if (bodyPage() !== 'game') return;
  const startButton = document.getElementById('start-game-button');
  const replayButton = document.getElementById('replay-button');
  const guessForm = document.getElementById('guess-form');
  const difficultySelect = document.getElementById('difficulty-select');
  const modeSelect = document.getElementById('mode-select');

  startButton?.addEventListener('click', async () => {
    try {
      await startGame(modeSelect.value, difficultySelect.value, true);
    } catch (error) {
      toast(error.message, 'error');
    }
  });

  replayButton?.addEventListener('click', async () => {
    try {
      await api('/api/game/replay', { method: 'POST', body: JSON.stringify({ difficulty: difficultySelect.value, mode: modeSelect.value }) });
      await hydrateGame();
      toast('New run started.');
    } catch (error) {
      toast(error.message, 'error');
    }
  });

  guessForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = document.getElementById('guess-input');
    try {
      const data = await api('/api/game/guess', { method: 'POST', body: JSON.stringify({ guess: input.value }) });
      state.attempts = data.attempts;
      renderAttempts(state.attempts);
      renderGame(data.game, data.feedback.aiHint);
      if (data.result === 'win') toast('You won.');
      if (data.result === 'lose') toast(`Run ended. Secret: ${data.game.secretRevealed}`, 'error');
      input.value = '';
    } catch (error) {
      toast(error.message, 'error');
    }
  });

  hydrateGame().catch((error) => toast(error.message, 'error'));
}

async function loadLeaderboard() {
  const body = document.getElementById('leaderboard-body');
  if (!body) return;
  const filter = document.getElementById('scoreboard-difficulty-filter');
  const query = filter?.value ? `?difficulty=${encodeURIComponent(filter.value)}` : '';
  const data = await api(`/api/scoreboard${query}`);
  body.innerHTML = '';
  data.entries.forEach((entry, index) => {
    const row = document.createElement('tr');
    row.innerHTML = `<td>${index + 1}</td><td>${entry.username}</td><td>${entry.mode}</td><td>${entry.attemptsUsed}/${entry.maxAttempts}</td><td>${formatSeconds(entry.elapsedSeconds)}</td><td>${entry.scoreValue}</td>`;
    body.appendChild(row);
  });
}

async function loadParticipants(targetId) {
  const target = document.getElementById(targetId);
  if (!target) return;
  const data = await api('/api/participants');
  target.innerHTML = '';
  data.participants.forEach((participant) => {
    const pill = document.createElement('span');
    pill.className = 'player-pill';
    pill.textContent = `${participant.avatar} ${participant.username}`;
    target.appendChild(pill);
  });
}

async function loadHistoryPage() {
  const target = document.getElementById('history-runs');
  if (!target) return;
  const data = await api('/api/history');
  target.innerHTML = '';
  if (!data.history.length) {
    const empty = document.createElement('div');
    empty.className = 'history-item';
    empty.textContent = 'No finished runs yet. Complete a game to see the replay trail here.';
    target.appendChild(empty);
    return;
  }
  data.history.forEach((run) => {
    const wrap = document.createElement('div');
    wrap.className = 'history-item';
    const attempts = (run.attempts || []).map((attempt) =>
      `<li><strong>#${attempt.attemptNumber} ${attempt.guess}</strong> <span>${attempt.exactMatches} exact / ${attempt.partialMatches} misplaced / ${attempt.direction}</span><div>${attempt.aiHint}</div></li>`
    ).join('');
    wrap.innerHTML = `
      <strong>${run.difficulty} / ${run.mode} / ${run.status}</strong>
      <div class="history-meta">
        <span>${run.attempts_used}/${run.max_attempts} attempts</span>
        <span>${run.ended_at || run.started_at}</span>
        <span>Secret: ${run.secret_number}</span>
      </div>
      <ul class="history-replay">${attempts}</ul>
    `;
    target.appendChild(wrap);
  });
}

function initScoreboardPage() {
  if (bodyPage() !== 'scoreboard') return;
  const filter = document.getElementById('scoreboard-difficulty-filter');
  filter?.addEventListener('change', () => loadLeaderboard().catch((error) => toast(error.message, 'error')));
  loadLeaderboard().catch((error) => toast(error.message, 'error'));
  loadParticipants('participant-list').catch((error) => toast(error.message, 'error'));
}

function initProfilePage() {
  if (bodyPage() !== 'profile') return;
  const avatarGrid = document.getElementById('avatar-grid');
  const saveButton = document.getElementById('save-avatar-button');
  const avatars = window.APP_CONFIG?.avatars || [];
  populateAvatarGrid(avatarGrid, avatars);
  saveButton?.addEventListener('click', async () => {
    try {
      await saveAvatarSelection();
      toast('Avatar updated.');
    } catch (error) {
      toast(error.message, 'error');
    }
  });
  loadStatsInto('profile').catch((error) => toast(error.message, 'error'));
  loadParticipants('profile-participants').catch((error) => toast(error.message, 'error'));
}

function initHomePage() {
  if (bodyPage() !== 'home') return;
  loadStatsInto('stat').catch((error) => toast(error.message, 'error'));
  loadDailyPreview().catch((error) => toast(error.message, 'error'));
}

function initHistoryPage() {
  if (bodyPage() !== 'history') return;
  loadHistoryPage().catch((error) => toast(error.message, 'error'));
}

async function boot() {
  if (window.APP_CONFIG?.user) setNavUser(window.APP_CONFIG.user);
  initLogout();
  initPasswordToggles();
  await handleAuthForm('login-form', '/api/login');
  await handleAuthForm('register-form', '/api/register');
  await handleForgotPasswordForm();
  initStartButtons();
  initNavigationButtons();
  initAvatarModal();
  initHomePage();
  initGamePage();
  initScoreboardPage();
  initProfilePage();
  initHistoryPage();
  if (bodyPage() === 'game') loadDailyPreview().catch(() => {});
}

boot().catch((error) => toast(error.message, 'error'));
