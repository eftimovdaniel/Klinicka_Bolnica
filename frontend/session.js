
(function () {
  'use strict';

  var INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000;
  var ABSOLUTE_TIMEOUT_MS   = 8 * 60 * 60 * 1000;
  var WARN_BEFORE_MS        = 30 * 1000;
  var TICK_INTERVAL_MS      = 10 * 1000;

  var warnShownFor = { pacient: false, lekar: false };
  var tickHandle = null;
  var activityListenersAttached = false;
  var memory = { pacient: null, lekar: null };
  var meta = { pacient: null, lekar: null };
  var channel = null;

  function now() { return Date.now(); }

  function apiBase() {
    var h = window.location.hostname;
    if (!h) return 'http://localhost:8000';
    if (h === 'localhost' || h === '127.0.0.1') {
      if (!window.location.port || window.location.port === '8000') return window.location.origin;
      return 'http://localhost:8000';
    }
    return window.location.origin;
  }

  function wipeOldStorage() {
    try {
      sessionStorage.removeItem('currentPacient');
      sessionStorage.removeItem('currentLekar');
      localStorage.removeItem('currentPacient');
      localStorage.removeItem('currentLekar');
    } catch (e) {}
  }

  function profileOf(data) {
    if (!data || typeof data !== 'object') return null;
    var copy = {};
    Object.keys(data).forEach(function (key) {
      if (key !== 'session_token') copy[key] = data[key];
    });
    return copy;
  }

  function checkExpiry(stamp) {
    if (!stamp) return null;
    var t = now();
    if (t - stamp.loggedInAt > ABSOLUTE_TIMEOUT_MS) return 'absolute';
    if (t - stamp.lastActivityAt > INACTIVITY_TIMEOUT_MS) return 'inactivity';
    return null;
  }

  function msUntilExpiry(stamp) {
    if (!stamp) return -1;
    var t = now();
    var inact = INACTIVITY_TIMEOUT_MS - (t - stamp.lastActivityAt);
    var absol = ABSOLUTE_TIMEOUT_MS - (t - stamp.loggedInAt);
    return Math.min(inact, absol);
  }

  function publish(type, role, profile) {
    if (!channel) return;
    try { channel.postMessage({ type: type, role: role, profile: profile || null }); } catch (e) {}
  }

  function startSession(role, data, silent) {
    memory[role] = profileOf(data);
    meta[role] = { loggedInAt: now(), lastActivityAt: now() };
    warnShownFor[role] = false;
    hideWarningToast();
    wipeOldStorage();
    if (!silent) publish('start', role, memory[role]);
  }

  function getSession(role) {
    var stamp = meta[role];
    if (!memory[role] || !stamp) return null;
    if (checkExpiry(stamp)) {
      endSession(role, 'expired');
      return null;
    }
    return memory[role];
  }

  function endSession(role, reason, silent) {
    memory[role] = null;
    meta[role] = null;
    warnShownFor[role] = false;
    wipeOldStorage();
    if (!hasAnyActiveWarning()) hideWarningToast();
    if (!silent) {
      publish('end', role, null);
      var path = role === 'lekar' ? '/lekari/logout' : '/pacienti/logout';
      fetch(apiBase() + path, { method: 'POST', credentials: 'include' }).catch(function () {});
    }
    try {
      window.dispatchEvent(new CustomEvent('kbs:session-end', {
        detail: { role: role, reason: reason || 'manual' }
      }));
    } catch (e) {}
  }

  function touchActivity() {
    ['pacient', 'lekar'].forEach(function (role) {
      var stamp = meta[role];
      if (!memory[role] || !stamp) return;
      if (checkExpiry(stamp)) {
        endSession(role, 'expired');
        return;
      }
      stamp.lastActivityAt = now();
      warnShownFor[role] = false;
    });
    if (!hasAnyActiveWarning()) hideWarningToast();
  }

  function hasAnyActiveWarning() {
    return warnShownFor.pacient || warnShownFor.lekar;
  }

  function tick() {
    ['pacient', 'lekar'].forEach(function (role) {
      var stamp = meta[role];
      if (!memory[role] || !stamp) return;
      var expiry = checkExpiry(stamp);
      if (expiry) {
        endSession(role, 'expired');
        showExpiredNotice(role, expiry);
        return;
      }
      var remaining = msUntilExpiry(stamp);
      if (remaining <= WARN_BEFORE_MS && !warnShownFor[role]) {
        warnShownFor[role] = true;
        showWarningToast(role, remaining);
      }
    });
  }

  function startTicking() {
    if (tickHandle) return;
    tickHandle = setInterval(tick, TICK_INTERVAL_MS);
  }

  function ensureToastEl() {
    var el = document.getElementById('kbs-session-toast');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'kbs-session-toast';
    el.className = 'kbs-session-toast';
    el.style.display = 'none';
    el.innerHTML =
      '<div class="kbs-session-toast__icon" aria-hidden="true">⏱</div>' +
      '<div class="kbs-session-toast__body">' +
        '<div class="kbs-session-toast__title">Сесијата истекува</div>' +
        '<div class="kbs-session-toast__msg" id="kbs-session-toast-msg"></div>' +
      '</div>' +
      '<button type="button" class="kbs-session-toast__btn" id="kbs-session-toast-stay">Остани најавен</button>' +
      '<button type="button" class="kbs-session-toast__close" id="kbs-session-toast-close" aria-label="Затвори">×</button>';
    document.body.appendChild(el);
    document.getElementById('kbs-session-toast-stay').addEventListener('click', function () {
      touchActivity();
      hideWarningToast();
    });
    document.getElementById('kbs-session-toast-close').addEventListener('click', function () {
      hideWarningToast();
    });
    return el;
  }

  function showWarningToast(role, remainingMs) {
    var el = ensureToastEl();
    var sek = Math.max(5, Math.round(remainingMs / 1000));
    var imeUloga = role === 'lekar' ? 'лекар' : 'пациент';
    document.getElementById('kbs-session-toast-msg').textContent =
      'Како ' + imeUloga + ' ќе бидете автоматски одјавени за ' + sek + ' секунди поради неактивност.';
    el.style.display = 'flex';
  }

  function hideWarningToast() {
    var el = document.getElementById('kbs-session-toast');
    if (el) el.style.display = 'none';
  }

  function showExpiredNotice(role, reason) {
    var imeUloga = role === 'lekar' ? 'лекарскиот' : 'пациентскиот';
    var minutiNeaktivnost = Math.round(INACTIVITY_TIMEOUT_MS / 60000);
    var prichina = reason === 'absolute'
      ? 'максималното време за најава помина.'
      : 'немаше активност ' + minutiNeaktivnost + ' минути.';
    var el = ensureToastEl();
    document.getElementById('kbs-session-toast-msg').textContent =
      'Автоматски сте одјавени од ' + imeUloga + ' профил - ' + prichina;
    el.classList.add('kbs-session-toast--expired');
    el.style.display = 'flex';
    setTimeout(function () {
      el.classList.remove('kbs-session-toast--expired');
      hideWarningToast();
    }, 6000);
  }

  function isOurApi(url) {
    if (!url) return false;
    if (url.charAt(0) === '/') return true;
    try {
      return new URL(url, window.location.href).host === new URL(apiBase()).host;
    } catch (e) {
      return false;
    }
  }

  function attachActivityListeners() {
    if (activityListenersAttached) return;
    activityListenersAttached = true;

    var lastTouch = 0;
    function throttledTouch() {
      var t = now();
      if (t - lastTouch < 5000) return;
      lastTouch = t;
      touchActivity();
    }

    ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'click'].forEach(function (ev) {
      document.addEventListener(ev, throttledTouch, { passive: true });
    });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') tick();
    });
    window.addEventListener('focus', tick);

    if (window.fetch) {
      var origFetch = window.fetch.bind(window);
      window.fetch = function (input, init) {
        throttledTouch();
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        if (!isOurApi(url)) return origFetch(input, init);
        var next = init ? Object.assign({}, init) : {};
        next.credentials = 'include';
        return origFetch(input, next);
      };
    }
  }

  try {
    channel = new BroadcastChannel('kb-sesija');
    channel.onmessage = function (msg) {
      var data = msg.data || {};
      if (data.type === 'end' && (data.role === 'pacient' || data.role === 'lekar')) {
        endSession(data.role, 'manual', true);
      } else if (data.type === 'start' && data.profile) {
        startSession(data.role, data.profile, true);
        try {
          window.dispatchEvent(new CustomEvent('kbs:session-sync', {
            detail: { role: data.role, valueExists: true }
          }));
        } catch (e) {}
      }
    };
  } catch (e) {
    channel = null;
  }

  function vcitajSesija() {
    return fetch(apiBase() + '/sesija', { credentials: 'include' })
      .then(function (res) { return res.ok ? res.json() : { pacient: null, lekar: null }; })
      .then(function (data) {
        data = data || {};
        if (data.pacient) startSession('pacient', data.pacient, true);
        if (data.lekar) startSession('lekar', data.lekar, true);
        return { pacient: memory.pacient, lekar: memory.lekar };
      })
      .catch(function () {
        return { pacient: null, lekar: null };
      });
  }

  function izbranaSoglasnost() {
    var m = document.cookie.match(/(?:^|; )kb_soglasnost=([^;]*)/);
    if (m && decodeURIComponent(m[1]) === 'prifateni') return 'prifateni';
    try {
      if (localStorage.getItem('kb_soglasnost') === 'odbieni') return 'odbieni';
    } catch (e) {}
    return '';
  }

  function zapisiPrifateni() {
    var secure = window.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = 'kb_soglasnost=prifateni; Path=/; Max-Age=15552000; SameSite=Lax' + secure;
    try { localStorage.removeItem('kb_soglasnost'); } catch (e) {}
  }

  function zapisiOdbieni() {
    document.cookie = 'kb_soglasnost=; Path=/; Max-Age=0; SameSite=Lax';
    try { localStorage.setItem('kb_soglasnost', 'odbieni'); } catch (e) {}
  }

  function izbrisiSesiskiKolacinja() {
    fetch(apiBase() + '/pacienti/logout', { method: 'POST', credentials: 'include' }).catch(function () {});
    fetch(apiBase() + '/lekari/logout', { method: 'POST', credentials: 'include' }).catch(function () {});
    memory.pacient = null;
    memory.lekar = null;
    meta.pacient = null;
    meta.lekar = null;
    ['pacient', 'lekar'].forEach(function (role) {
      try {
        window.dispatchEvent(new CustomEvent('kbs:session-end', {
          detail: { role: role, reason: 'manual' }
        }));
      } catch (e) {}
    });
  }

  function skrijKolacinja() {
    var el = document.getElementById('kb-kolacinja');
    if (el) el.style.display = 'none';
    if (document.body) document.body.classList.remove('kb-kolacinja-otvoreni');
  }

  function pokazhiKolacinja() {
    if (!document.body) return;
    var el = document.getElementById('kb-kolacinja');
    if (!el) {
      el = document.createElement('div');
      el.id = 'kb-kolacinja';
      el.className = 'kb-kolacinja';
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-label', 'Колачиња');
      el.innerHTML =
        '<div class="kb-kolacinja__text">' +
          '<strong>Колачиња</strong>' +
          '<p>Сајтот користи колачиња за да ве задржи најавени. Ако ги одбиете, најавата не се памети.</p>' +
        '</div>' +
        '<div class="kb-kolacinja__actions">' +
          '<button type="button" class="kb-kolacinja__prifati" data-kb="prifati">Прифати</button>' +
          '<button type="button" class="kb-kolacinja__odbij" data-kb="odbij">Одбиј</button>' +
        '</div>';
      document.body.appendChild(el);
      el.querySelector('[data-kb="prifati"]').addEventListener('click', function () {
        zapisiPrifateni();
        skrijKolacinja();
      });
      el.querySelector('[data-kb="odbij"]').addEventListener('click', function () {
        zapisiOdbieni();
        izbrisiSesiskiKolacinja();
        skrijKolacinja();
      });
    }
    el.style.display = 'flex';
    document.body.classList.add('kb-kolacinja-otvoreni');
  }

  wipeOldStorage();

  var ready = izbranaSoglasnost() === 'prifateni'
    ? vcitajSesija()
    : Promise.resolve({ pacient: null, lekar: null });

  if (izbranaSoglasnost() === 'odbieni') izbrisiSesiskiKolacinja();

  window.KBSession = {
    start: startSession,
    get: getSession,
    end: endSession,
    touch: touchActivity,
    ready: ready
  };

  window.KBKolacinja = {
    prifateni: function () { return izbranaSoglasnost() === 'prifateni'; },
    pokazhi: pokazhiKolacinja
  };

  function startUi() {
    attachActivityListeners();
    startTicking();
    tick();
    if (!izbranaSoglasnost()) pokazhiKolacinja();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startUi);
  } else {
    startUi();
  }
})();
