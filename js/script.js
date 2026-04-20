 /* Three Digit Number Guessing Game - Static frontend logic */

const STORAGE_KEYS = {
  user: 'guessit_user',
  accounts: 'guessit_accounts',
  users: 'guessit_users',
  scores: 'guessit_scores',
  session: 'guessit_session_token'
};

const COOKIE_KEYS = {
  session: 'guessit_session'
};

const API_ENDPOINTS = {
  participants: '/api/participants',
  scores: '/api/scores'
};

function loadJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (err) {
    return fallback;
  }
}

function saveJSON(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

async function requestJSON(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error('Request failed with status ' + response.status);
  }
  return response.json();
}

async function fetchParticipants() {
  try {
    const data = await requestJSON(API_ENDPOINTS.participants);
    return Array.isArray(data.participants) ? data.participants : [];
  } catch (err) {
    const users = loadJSON(STORAGE_KEYS.users, []);
    return users.map((username) => ({ username, avatar: 'A' }));
  }
}

async function fetchScoresFromApi() {
  try {
    const data = await requestJSON(API_ENDPOINTS.scores);
    return Array.isArray(data.scores) ? data.scores : [];
  } catch (err) {
    return getScores();
  }
}

async function syncParticipant(username, avatar, password) {
  if (!username) return;
  try {
    await requestJSON(API_ENDPOINTS.participants, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, avatar, password })
    });
  } catch (err) {
    // Local storage remains available if the API is offline.
  }
}

async function saveScoreToDatabase(entry) {
  try {
    await requestJSON(API_ENDPOINTS.scores, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry)
    });
  } catch (err) {
    // Keep local storage as a fallback when the API is unavailable.
  }
}

function normalizeUsername(username) {
  return String(username || '').trim().toLowerCase();
}

function setCookie(name, value, days) {
  const maxAge = Math.max(0, Math.floor(days * 24 * 60 * 60));
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAge}; samesite=lax`;
}

function getCookie(name) {
  const parts = document.cookie ? document.cookie.split('; ') : [];
  for (const part of parts) {
    const idx = part.indexOf('=');
    if (idx === -1) continue;
    const key = part.slice(0, idx);
    if (key === name) return decodeURIComponent(part.slice(idx + 1));
  }
  return '';
}

function deleteCookie(name) {
  document.cookie = `${name}=; path=/; max-age=0; samesite=lax`;
}

function getUser() {
  const user = loadJSON(STORAGE_KEYS.user, null);
  const storageSession = localStorage.getItem(STORAGE_KEYS.session) || '';
  const cookieSession = getCookie(COOKIE_KEYS.session);
  const hasValidSession = Boolean(
    user &&
    user.username &&
    (
      storageSession === user.username ||
      (cookieSession && cookieSession === user.username)
    )
  );
  if (hasValidSession) {
    return {
      username: user.username,
      avatar: user.avatar || 'A',
      loggedIn: true
    };
  }
  if (user && user.username) {
    const inferredLoggedIn =
      storageSession === user.username ||
      (cookieSession && cookieSession === user.username);
    return {
      username: user.username,
      avatar: user.avatar || 'A',
      loggedIn: Boolean(inferredLoggedIn)
    };
  }
  return { username: 'Player', avatar: 'A', loggedIn: false };
}

function setUser(username, avatar) {
  const safeName = username && username.trim() ? username.trim() : 'Player';
  const accounts = getAccounts();
  const key = normalizeUsername(safeName);
  const canonicalName = accounts[key]?.username || safeName;
  const storedAvatar = accounts[key]?.avatar || avatar || 'A';
  const user = { username: canonicalName, avatar: storedAvatar, loggedIn: true };
  saveJSON(STORAGE_KEYS.user, user);
  ensureUserInList(user.username);
  localStorage.setItem(STORAGE_KEYS.session, user.username);
  setCookie(COOKIE_KEYS.session, user.username, 7);
  return user;
}

function signOut() {
  saveJSON(STORAGE_KEYS.user, { username: 'Player', avatar: 'A', loggedIn: false });
  localStorage.removeItem(STORAGE_KEYS.session);
  deleteCookie(COOKIE_KEYS.session);
}

function getAccounts() {
  return loadJSON(STORAGE_KEYS.accounts, {});
}

function saveAccounts(accounts) {
  saveJSON(STORAGE_KEYS.accounts, accounts);
}

function userExists(username) {
  if (!username) return false;
  const accounts = getAccounts();
  return Boolean(accounts[normalizeUsername(username)]);
}

async function hashPassword(password) {
  const input = String(password || '');
  if (window.crypto?.subtle && window.TextEncoder) {
    const data = new TextEncoder().encode(input);
    const hashBuffer = await window.crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  return btoa(unescape(encodeURIComponent(input)));
}

async function createAccount(username, password) {
  const safeName = String(username).trim();
  const key = normalizeUsername(safeName);
  const accounts = getAccounts();
  if (accounts[key]) {
    throw new Error('Username already exists. Please choose another one.');
  }
  const passwordHash = await hashPassword(password);
  accounts[key] = {
    username: safeName,
    passwordHash,
    avatar: 'A',
    createdAt: new Date().toISOString()
  };
  saveAccounts(accounts);
  ensureUserInList(safeName);
  await syncParticipant(safeName, 'A', passwordHash);
}

async function validateCredentials(username, password) {
  const key = normalizeUsername(username);
  const accounts = getAccounts();
  const account = accounts[key];
  if (!account) return false;
  const inputHash = await hashPassword(password);
  return inputHash === account.passwordHash;
}

async function resetPassword(username, newPassword) {
  const key = normalizeUsername(username);
  const accounts = getAccounts();
  const account = accounts[key];
  if (!account) {
    throw new Error('User not found. Please register first.');
  }
  account.passwordHash = await hashPassword(newPassword);
  accounts[key] = account;
  saveAccounts(accounts);
}

function updateAccountAvatar(username, avatar) {
  const key = normalizeUsername(username);
  const accounts = getAccounts();
  if (!accounts[key]) return;
  accounts[key].avatar = avatar;
  saveAccounts(accounts);
  syncParticipant(accounts[key].username, avatar, accounts[key].passwordHash);
}

function setButtonLoading(button, isLoading, loadingText) {
  if (!button) return;
  if (isLoading) {
    button.dataset.originalText = button.textContent || '';
    button.disabled = true;
    button.textContent = loadingText || 'Please wait...';
    button.setAttribute('aria-busy', 'true');
  } else {
    button.disabled = false;
    button.textContent = button.dataset.originalText || button.textContent || '';
    button.removeAttribute('aria-busy');
  }
}

function getCurrentPage() {
  return document.body?.dataset?.page || '';
}

function isAuthenticated() {
  return getUser().loggedIn;
}

function redirectToLogin() {
  window.location.replace('login.html');
}

function redirectToHome() {
  window.location.replace('index.html');
}

function enforceRouteProtection() {
  const page = getCurrentPage();
  const protectedPages = new Set(['home', 'game', 'profile', 'scoreboard', 'training', 'practice']);
  const authPages = new Set(['login', 'register']);
  const loggedIn = isAuthenticated();

  if (authPages.has(page) && loggedIn) {
    redirectToHome();
    return false;
  }

  if (protectedPages.has(page) && !loggedIn) {
    redirectToLogin();
    return false;
  }

  return true;
}

function preventBackNavigationOnProtectedPages() {
  const page = getCurrentPage();
  const protectedPages = new Set(['home', 'game', 'profile', 'scoreboard', 'training', 'practice']);
  if (!protectedPages.has(page) || !isAuthenticated()) return;
  window.history.pushState(null, '', window.location.href);
  window.onpopstate = function () {
    window.history.go(1);
  };
}

function ensureUserInList(username) {
  if (!username) return;
  const users = loadJSON(STORAGE_KEYS.users, []);
  if (!users.includes(username)) {
    users.push(username);
    saveJSON(STORAGE_KEYS.users, users);
  }
  syncParticipant(username, getUser().avatar);
}

function getScores() {
  return loadJSON(STORAGE_KEYS.scores, []);
}

function addScore(entry) {
  const scores = getScores();
  scores.push(entry);
  saveJSON(STORAGE_KEYS.scores, scores);
  saveScoreToDatabase(entry);
}

function formatNumber(num) {
  return String(num).padStart(3, '0');
}

function formatDateTime(date) {
  const d = date || new Date();
  return d.toLocaleString();
}

function togglePassword(fieldId, btn) {
  const input = document.getElementById(fieldId);
  if (!input || !btn) return;
  if (input.type === 'password') {
    input.type = 'text';
    btn.textContent = 'Hide';
  } else {
    input.type = 'password';
    btn.textContent = 'Show';
  }
}

function showInlineError(form, msg) {
  if (!form) return;
  form.querySelector('.inline-error')?.remove();
  const div = document.createElement('div');
  div.className = 'flash flash-error inline-error';
  div.textContent = msg;
  form.prepend(div);
  setTimeout(() => div.remove(), 4000);
}

function showInlineSuccess(form, msg) {
  if (!form) return;
  form.querySelector('.inline-success')?.remove();
  const div = document.createElement('div');
  div.className = 'flash flash-success inline-success';
  div.textContent = msg;
  form.prepend(div);
  setTimeout(() => div.remove(), 3000);
}

function updateNavUser() {
  const user = getUser();
  document.querySelectorAll('#nav-user-badge').forEach((el) => {
    el.textContent = user.username;
  });
  document.querySelectorAll('.btn-logout').forEach((btn) => {
    if (user.loggedIn) {
      btn.textContent = 'Logout';
      btn.setAttribute('href', 'login.html');
      btn.onclick = (e) => {
        e.preventDefault();
        signOut();
        redirectToLogin();
      };
    } else {
      btn.textContent = 'Sign In';
      btn.setAttribute('href', 'login.html');
      btn.onclick = null;
    }
  });
}

function initAuthForms() {
  const forms = document.querySelectorAll('form[data-static-form]');
  forms.forEach((form) => {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const username = form.querySelector('#username')?.value.trim() || '';
      const password = form.querySelector('#password')?.value.trim() || '';
      const confirm = form.querySelector('#confirm_password')?.value.trim() || '';
      const submitBtn = form.querySelector('button[type="submit"]');

      if (!username) {
        showInlineError(form, 'Please enter a username.');
        return;
      }

      try {
        if ((form.id === 'login-form' || form.id === 'register-form' || form.id === 'forgot-form') && !password) {
          showInlineError(form, 'Please enter your password.');
          return;
        }

        if (form.id === 'register-form') {
          if (username.length < 3) {
            showInlineError(form, 'Username must be at least 3 characters.');
            return;
          }
          if (userExists(username)) {
            showInlineError(form, 'Username already exists. Please choose another one.');
            return;
          }
          if (password.length < 6) {
            showInlineError(form, 'Password must be at least 6 characters.');
            return;
          }
          if (password !== confirm) {
            showInlineError(form, 'Passwords do not match.');
            return;
          }
          setButtonLoading(submitBtn, true, 'Creating account...');
          await createAccount(username, password);
          setUser(username);
          updateNavUser();
          showInlineSuccess(form, 'Account created. Redirecting...');
          setTimeout(() => redirectToHome(), 500);
          return;
        }

        if (form.id === 'login-form') {
          setButtonLoading(submitBtn, true, 'Signing in...');
          const valid = await validateCredentials(username, password);
          if (!valid) {
            showInlineError(form, 'Invalid username or password.');
            return;
          }
          setUser(username);
          updateNavUser();
          showInlineSuccess(form, 'Login successful. Redirecting...');
          setTimeout(() => redirectToHome(), 400);
          return;
        }

        if (form.id === 'forgot-form') {
          if (password.length < 6) {
            showInlineError(form, 'Password must be at least 6 characters.');
            return;
          }
          if (password !== confirm) {
            showInlineError(form, 'Passwords do not match.');
            return;
          }
          setButtonLoading(submitBtn, true, 'Saving...');
          await resetPassword(username, password);
          showInlineSuccess(form, 'Password updated. Redirecting to login...');
          setTimeout(() => {
            signOut();
            redirectToLogin();
          }, 700);
          return;
        }
      } catch (err) {
        showInlineError(form, err?.message || 'Something went wrong. Please try again.');
      } finally {
        setButtonLoading(submitBtn, false);
      }
    });
  });
}

function initPasswordStrength() {
  const pwInput = document.getElementById('password');
  const strengthWrap = document.getElementById('strength-wrap');
  const strengthFill = document.getElementById('strength-fill');
  const strengthLabel = document.getElementById('strength-label');

  if (!pwInput || !strengthWrap || !strengthFill || !strengthLabel) return;

  pwInput.addEventListener('input', () => {
    const val = pwInput.value;
    if (!val) {
      strengthWrap.style.display = 'none';
      return;
    }
    strengthWrap.style.display = 'flex';

    let score = 0;
    if (val.length >= 6) score++;
    if (val.length >= 10) score++;
    if (/[A-Z]/.test(val)) score++;
    if (/[0-9]/.test(val)) score++;
    if (/[^A-Za-z0-9]/.test(val)) score++;

    const levels = [
      { w: '20%', bg: '#ef4444', label: 'Weak' },
      { w: '40%', bg: '#f97316', label: 'Fair' },
      { w: '60%', bg: '#f59e0b', label: 'Good' },
      { w: '80%', bg: '#22c55e', label: 'Strong' },
      { w: '100%', bg: '#10b981', label: 'Very Strong' }
    ];
    const lvl = levels[Math.min(score, 4)];
    strengthFill.style.width = lvl.w;
    strengthFill.style.background = lvl.bg;
    strengthLabel.textContent = lvl.label;
    strengthLabel.style.color = lvl.bg;
  });
}

function initGame() {
  const gameRoot = document.body?.dataset?.game === 'true';
  if (!gameRoot) return;

  const params = new URLSearchParams(window.location.search);
  const mode = params.get('mode') === 'practice' ? 'practice' : 'normal';
  const maxAttempts = parseInt(document.body.dataset.maxAttempts || '10', 10);

  const guessForm = document.getElementById('guess-form');
  const guessInput = document.getElementById('guess-input');
  const attemptsCount = document.getElementById('attempts-count');
  const progressBar = document.querySelector('.progress-bar');
  const progressFill = document.getElementById('progress-fill');
  const feedbackContainer = document.getElementById('feedback-container');
  const historyList = document.getElementById('history-list');
  const resultWrap = document.getElementById('game-result');
  const resultIcon = document.getElementById('result-icon');
  const resultTitle = document.getElementById('result-title');
  const resultSubtitle = document.getElementById('result-subtitle');
  const resultSecret = document.getElementById('result-secret');
  const statAttemptsUsed = document.getElementById('stat-attempts-used');
  const statAttemptsLeft = document.getElementById('stat-attempts-left');
  const restartBtn = document.getElementById('restart-game');
  const usernameLabel = document.getElementById('game-username');

  if (!guessForm || !guessInput || !feedbackContainer || !historyList || !resultWrap) {
    return;
  }

  let secret = 0;
  let attemptsLeft = maxAttempts;
  let guesses = [];
  let finished = false;

  function resetGame() {
    secret = Math.floor(Math.random() * 1000);
    attemptsLeft = maxAttempts;
    guesses = [];
    finished = false;
    feedbackContainer.innerHTML = '';
    historyList.innerHTML = '';
    resultWrap.hidden = true;
    resultSecret.hidden = true;
    guessInput.disabled = false;
    guessInput.value = '';
    guessInput.classList.remove('pulse-danger');
    updateProgress();
    guessInput.focus();
  }

  function updateProgress() {
    const pct = (attemptsLeft / maxAttempts) * 100;
    if (attemptsCount) {
      attemptsCount.textContent = attemptsLeft + ' / ' + maxAttempts;
      attemptsCount.classList.remove('safe', 'warn', 'danger');
      if (pct > 60) attemptsCount.classList.add('safe');
      else if (pct > 30) attemptsCount.classList.add('warn');
      else attemptsCount.classList.add('danger');
    }
    if (guessInput) {
      guessInput.classList.toggle('pulse-danger', attemptsLeft <= 2 && !finished);
    }
    if (progressBar) {
      progressBar.setAttribute('aria-valuenow', String(attemptsLeft));
      progressBar.setAttribute('aria-valuemax', String(maxAttempts));
    }
    if (progressFill) {
      progressFill.style.width = pct + '%';
      if (pct > 60) progressFill.style.background = 'linear-gradient(90deg, #10b981, #059669)';
      else if (pct > 30) progressFill.style.background = 'linear-gradient(90deg, #f59e0b, #d97706)';
      else progressFill.style.background = 'linear-gradient(90deg, #ef4444, #dc2626)';
    }
  }

  function addFeedback(type, title, detail) {
    if (!feedbackContainer) return;
    const banner = document.createElement('div');
    banner.className = 'feedback-banner ' + type;
    const icon = type === 'correct' ? 'OK' : type === 'high' ? 'High' : type === 'low' ? 'Low' : 'Info';
    banner.innerHTML = `
      <span class="feedback-icon">${icon}</span>
      <div>
        <strong>${title}</strong><br>
        <small>${detail}</small>
      </div>
    `;
    feedbackContainer.innerHTML = '';
    feedbackContainer.appendChild(banner);
  }

  function addHistory(guess, feedback, distance) {
    if (!historyList) return;
    const item = document.createElement('li');
    item.className = 'history-item';
    const badgeClass = feedback === 'correct' ? 'correct' : feedback;
    const badgeText = feedback === 'correct' ? 'Correct' : feedback === 'high' ? 'Too High' : 'Too Low';
    item.innerHTML = `
      <span class="history-num">${formatNumber(guess)}</span>
      <span class="history-badge ${badgeClass}">${badgeText}</span>
      <span class="history-detail">Off by ${distance}</span>
    `;
    historyList.prepend(item);
  }

  function finishGame(result) {
    finished = true;
    guessInput.disabled = true;
    resultWrap.hidden = false;
    const attemptsUsed = maxAttempts - attemptsLeft;
    statAttemptsUsed.textContent = attemptsUsed;
    statAttemptsLeft.textContent = attemptsLeft;

    if (result === 'win') {
      resultIcon.className = 'result-icon win';
      resultIcon.textContent = 'Win';
      resultTitle.className = 'result-title win';
      resultTitle.textContent = 'You Won';
      resultSubtitle.textContent = 'Great job, you guessed the number.';
      resultSecret.hidden = true;
      launchConfetti();
    } else {
      resultIcon.className = 'result-icon lose';
      resultIcon.textContent = 'Lose';
      resultTitle.className = 'result-title lose';
      resultTitle.textContent = 'Game Over';
      resultSubtitle.textContent = 'The secret number was:';
      resultSecret.hidden = false;
      resultSecret.textContent = formatNumber(secret);
    }

    if (mode === 'normal') {
      const user = getUser();
      addScore({
        username: user.username,
        attemptsUsed: attemptsUsed,
        result: result,
        dateTime: formatDateTime(),
        maxAttempts: maxAttempts
      });
    }
  }

  if (usernameLabel) {
    usernameLabel.textContent = getUser().username;
  }

  guessInput.addEventListener('input', () => {
    guessInput.value = guessInput.value.replace(/\D/g, '').slice(0, 3);
  });

  guessForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (finished) return;

    const raw = guessInput.value.trim();
    if (raw === '' || isNaN(Number(raw))) {
      addFeedback('error', 'Invalid guess', 'Please enter a number between 000 and 999.');
      return;
    }
    const guess = Math.min(999, Math.max(0, parseInt(raw, 10)));
    const distance = Math.abs(guess - secret);
    attemptsLeft = Math.max(0, attemptsLeft - 1);

    if (guess === secret) {
      addFeedback('correct', 'Correct', 'You guessed ' + formatNumber(guess) + ' in ' + (maxAttempts - attemptsLeft) + ' attempts.');
      addHistory(guess, 'correct', distance);
      updateProgress();
      finishGame('win');
      return;
    }

    if (guess > secret) {
      addFeedback('high', 'Too High', mode === 'practice' ? 'Off by ' + distance + '.' : 'Try a lower number.');
      addHistory(guess, 'high', distance);
    } else {
      addFeedback('low', 'Too Low', mode === 'practice' ? 'Off by ' + distance + '.' : 'Try a higher number.');
      addHistory(guess, 'low', distance);
    }

    updateProgress();

    if (attemptsLeft <= 0) {
      finishGame('lose');
    }
  });

  restartBtn?.addEventListener('click', () => {
    resetGame();
  });

  resetGame();
}

function renderParticipantList(target, participants, currentUsername) {
  if (!target) return;
  target.innerHTML = '';
  participants.forEach((participant) => {
    const name = typeof participant === 'string' ? participant : participant.username;
    const span = document.createElement('span');
    span.className = 'player-pill' + (name === currentUsername ? ' you' : '');
    span.textContent = name;
    target.appendChild(span);
  });
}

async function initScoreboard() {
  const tableBody = document.getElementById('score-table-body');
  const participantList = document.getElementById('score-participants');
  if (!tableBody && !participantList) return;
  const user = getUser();
  const scores = await fetchScoresFromApi();
  const participants = await fetchParticipants();
  const totalBadge = document.getElementById('score-total');
  const tableWrap = document.getElementById('score-table-wrap');
  const emptyState = document.getElementById('score-empty');
  const participantCount = document.getElementById('score-participant-count');

  if (participantCount) {
    participantCount.textContent = participants.length + (participants.length === 1 ? ' player' : ' players');
  }

  renderParticipantList(participantList, participants, user.username);

  if (totalBadge) {
    totalBadge.textContent = scores.length + (scores.length === 1 ? ' game' : ' games');
  }

  if (!tableBody) return;

  if (scores.length === 0) {
    if (tableWrap) tableWrap.hidden = true;
    if (emptyState) emptyState.hidden = false;
    return;
  }

  if (tableWrap) tableWrap.hidden = false;
  if (emptyState) emptyState.hidden = true;

  const sorted = [...scores].sort((a, b) => a.attemptsUsed - b.attemptsUsed);
  tableBody.innerHTML = '';
  sorted.forEach((score, idx) => {
    const row = document.createElement('tr');
    const resultClass = score.result === 'win' ? 'win' : 'lose';
    const isUser = score.username === user.username;
    const rankClass = idx === 0 ? 'gold' : idx === 1 ? 'silver' : idx === 2 ? 'bronze' : '';
    const attemptCap = Number.isFinite(score.maxAttempts) ? score.maxAttempts : 10;
    if (isUser) row.classList.add('my-row');
    row.innerHTML = `
      <td><span class="rank-badge ${rankClass}">${idx + 1}</span></td>
      <td><span class="player-name">${score.username}</span>${isUser ? ' <span class="you-badge">You</span>' : ''}</td>
      <td><strong>${score.attemptsUsed}</strong> <span style="color: var(--text-muted); font-size: 0.8rem;">/ ${attemptCap}</span></td>
      <td><span class="result-chip ${resultClass}">${score.result === 'win' ? 'Win' : 'Lose'}</span></td>
      <td style="font-size: 0.8rem; color: var(--text-muted);">${score.dateTime}</td>
    `;
    tableBody.appendChild(row);
  });
}

async function initStats() {
  const totalEl = document.getElementById('stat-total');
  const winsEl = document.getElementById('stat-wins');
  const lossesEl = document.getElementById('stat-losses');
  const user = getUser();
  const scores = await fetchScoresFromApi();
  const userScores = scores.filter((s) => s.username === user.username);
  const wins = userScores.filter((s) => s.result === 'win').length;
  const losses = userScores.filter((s) => s.result === 'lose').length;

  if (totalEl) totalEl.textContent = userScores.length;
  if (winsEl) winsEl.textContent = wins;
  if (lossesEl) lossesEl.textContent = losses;

  const profileTotal = document.getElementById('profile-total');
  const profileWins = document.getElementById('profile-wins');
  const profileLosses = document.getElementById('profile-losses');
  const profilePlayers = document.getElementById('profile-players-count');
  const profileBadge = document.getElementById('profile-total-badge');

  if (profileTotal) profileTotal.textContent = userScores.length;
  if (profileWins) profileWins.textContent = wins;
  if (profileLosses) profileLosses.textContent = losses;

  const participants = await fetchParticipants();
  if (profilePlayers) profilePlayers.textContent = participants.length;
  if (profileBadge) profileBadge.textContent = userScores.length + (userScores.length === 1 ? ' game' : ' games');

  const playersList = document.getElementById('profile-players');
  renderParticipantList(playersList, participants, user.username);

  const homeName = document.getElementById('home-username');
  if (homeName) homeName.textContent = user.username;
}

function initAvatarPicker() {
  const avatarGrid = document.getElementById('avatar-grid');
  const avatarForm = document.getElementById('avatar-form');
  if (!avatarGrid || !avatarForm) return;

  const avatars = ['A', 'B', 'C', 'D', 'E', 'F'];
  const user = getUser();

  avatarGrid.innerHTML = '';
  avatars.forEach((avatar) => {
    const label = document.createElement('label');
    label.className = 'avatar-tile' + (avatar === user.avatar ? ' avatar-active' : '');
    label.innerHTML = `
      <input type="radio" name="avatar" value="${avatar}" ${avatar === user.avatar ? 'checked' : ''} />
      <span class="avatar-emoji">${avatar}</span>
    `;
    avatarGrid.appendChild(label);
  });

  avatarForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const selected = avatarForm.querySelector('input[name="avatar"]:checked');
    const avatar = selected ? selected.value : user.avatar;
    updateAccountAvatar(user.username, avatar);
    setUser(user.username, avatar);
    updateNavUser();
    showInlineSuccess(avatarForm, 'Avatar saved.');
  });
}

function initButtonRipple() {
  document.querySelectorAll('.btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      const ripple = document.createElement('span');
      const rect = btn.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      ripple.style.cssText = `
        position: absolute;
        width: ${size}px;
        height: ${size}px;
        left: ${e.clientX - rect.left - size / 2}px;
        top: ${e.clientY - rect.top - size / 2}px;
        background: rgba(255,255,255,0.15);
        border-radius: 50%;
        transform: scale(0);
        animation: ripple-expand 0.5s ease-out forwards;
        pointer-events: none;
      `;
      if (!btn.style.position || btn.style.position === 'static') {
        btn.style.position = 'relative';
      }
      btn.style.overflow = 'hidden';
      btn.appendChild(ripple);
      setTimeout(() => ripple.remove(), 600);
    });
  });

  if (!document.getElementById('ripple-style')) {
    const style = document.createElement('style');
    style.id = 'ripple-style';
    style.textContent = '@keyframes ripple-expand { to { transform: scale(2.5); opacity: 0; } }';
    document.head.appendChild(style);
  }
}

function launchConfetti() {
  const colours = ['#4f8ef7', '#7c3aed', '#ec4899', '#10b981', '#f59e0b', '#ffffff'];
  for (let i = 0; i < 60; i++) {
    setTimeout(() => {
      const dot = document.createElement('div');
      dot.classList.add('confetti-dot');
      dot.style.left = Math.random() * 100 + 'vw';
      dot.style.top = Math.random() * 20 + 'vh';
      dot.style.backgroundColor = colours[Math.floor(Math.random() * colours.length)];
      dot.style.width = (Math.random() * 8 + 5) + 'px';
      dot.style.height = (Math.random() * 8 + 5) + 'px';
      dot.style.animationDuration = (Math.random() * 1 + 1.2) + 's';
      document.body.appendChild(dot);
      setTimeout(() => dot.remove(), 2500);
    }, i * 30);
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  if (!enforceRouteProtection()) return;
  preventBackNavigationOnProtectedPages();
  updateNavUser();
  initAuthForms();
  initPasswordStrength();
  initGame();
  await initScoreboard();
  await initStats();
  initAvatarPicker();
  initButtonRipple();
});
