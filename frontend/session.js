

(function () {
  'use strict';

  // ========================================================================
  // КОНФИГУРАЦИЈА
  // ========================================================================
  var INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000;    // 5 минути неактивност
  var ABSOLUTE_TIMEOUT_MS   = 8 * 60 * 60 * 1000; // 8 часа од најава
  var WARN_BEFORE_MS        = 30 * 1000;        // предупреди 30 сек пред
  var TICK_INTERVAL_MS      = 10 * 1000;        // проверка секои 10 сек

  var KEY_PACIENT = 'currentPacient';
  var KEY_LEKAR   = 'currentLekar';

  // Внатрешна состојба
  var warnShownFor = { pacient: false, lekar: false };
  var tickHandle = null;
  var activityListenersAttached = false;

  // ========================================================================
  // ПОМОШНИ ФУНКЦИИ
  // ========================================================================
  function now() { return Date.now(); }

  function safeParse(raw) {
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (e) { return null; }
  }

  function isWrapped(obj) {
    return obj && typeof obj === 'object'
      && obj.data && typeof obj.data === 'object'
      && typeof obj.loggedInAt === 'number';
  }

  function readWrapped(key) {
    var raw = sessionStorage.getItem(key) || localStorage.getItem(key);
    var parsed = safeParse(raw);
    if (!parsed) return null;
    if (isWrapped(parsed)) return parsed;
    // Стар (не-завиткан) формат → завиткај го со „now" timestamps
    return {
      data: parsed,
      loggedInAt: now(),
      lastActivityAt: now()
    };
  }

  function writeWrapped(key, wrapped) {
    try {
      var s = JSON.stringify(wrapped);
      sessionStorage.setItem(key, s);
      localStorage.setItem(key, s);
    } catch (e) {}
  }

  function clearKey(key) {
    try {
      sessionStorage.removeItem(key);
      localStorage.removeItem(key);
    } catch (e) {}
  }

  /**
   * Проверка дали сесијата е експирирана.
   * Враќа: null = валидна, "inactivity" = неактивност, "absolute" = 8ч помина
   */
  function checkExpiry(wrapped) {
    if (!wrapped) return null;
    var t = now();
    if (t - wrapped.loggedInAt > ABSOLUTE_TIMEOUT_MS) return 'absolute';
    if (t - wrapped.lastActivityAt > INACTIVITY_TIMEOUT_MS) return 'inactivity';
    return null;
  }

  function msUntilExpiry(wrapped) {
    if (!wrapped) return -1;
    var t = now();
    var inact = INACTIVITY_TIMEOUT_MS - (t - wrapped.lastActivityAt);
    var absol = ABSOLUTE_TIMEOUT_MS   - (t - wrapped.loggedInAt);
    return Math.min(inact, absol);
  }

  // ========================================================================
  // ЈАВЕН API
  // ========================================================================

  /**
   * Иницијализација при login - запишува нова сесија.
   * @param {"pacient"|"lekar"} role
   * @param {object} data - оригиналните податоци за корисникот
   */
  function startSession(role, data) {
    var key = role === 'lekar' ? KEY_LEKAR : KEY_PACIENT;
    var t = now();
    var wrapped = { data: data, loggedInAt: t, lastActivityAt: t };
    writeWrapped(key, wrapped);
    warnShownFor[role] = false;
    hideWarningToast();
  }

  /**
   * Враќа ги корисничките податоци ако сесијата е валидна.
   * Ако е експирирана - ја брише и враќа null.
   * @returns {object|null}
   */
  function getSession(role) {
    var key = role === 'lekar' ? KEY_LEKAR : KEY_PACIENT;
    var wrapped = readWrapped(key);
    if (!wrapped) return null;

    var expiry = checkExpiry(wrapped);
    if (expiry) {
      clearKey(key);
      return null;
    }
    // back-compat: ако дојде од стар формат, веднаш сними го во новиот
    writeWrapped(key, wrapped);
    return wrapped.data;
  }

  /**
   * Ажурирај го `lastActivityAt` на сите активни сесии. Тивко.
   */
  function touchActivity() {
    [['pacient', KEY_PACIENT], ['lekar', KEY_LEKAR]].forEach(function (pair) {
      var role = pair[0], key = pair[1];
      var wrapped = readWrapped(key);
      if (!wrapped) return;
      // Не „освежувај" експирирана сесија
      if (checkExpiry(wrapped)) {
        endSession(role, 'expired');
        return;
      }
      wrapped.lastActivityAt = now();
      writeWrapped(key, wrapped);
      warnShownFor[role] = false; // user е активен → тргни warning
    });
    if (!hasAnyActiveWarning()) hideWarningToast();
  }

  /**
   * Сино одјавување на улога. Можен е и optional reason: "manual", "expired".
   */
  function endSession(role, reason) {
    var key = role === 'lekar' ? KEY_LEKAR : KEY_PACIENT;
    clearKey(key);
    warnShownFor[role] = false;
    if (!hasAnyActiveWarning()) hideWarningToast();

    // Извести script.js да ги ресетира своите варијабли
    try {
      window.dispatchEvent(new CustomEvent('kbs:session-end', {
        detail: { role: role, reason: reason || 'manual' }
      }));
    } catch (e) {}
  }

  function hasAnyActiveWarning() {
    return warnShownFor.pacient || warnShownFor.lekar;
  }

  // ========================================================================
  // PERIODIC CHECK + WARNING TOAST
  // ========================================================================

  function tick() {
    [['pacient', KEY_PACIENT], ['lekar', KEY_LEKAR]].forEach(function (pair) {
      var role = pair[0], key = pair[1];
      var wrapped = readWrapped(key);
      if (!wrapped) return;

      var expiry = checkExpiry(wrapped);
      if (expiry) {
        endSession(role, 'expired');
        showExpiredNotice(role, expiry);
        return;
      }

      var remaining = msUntilExpiry(wrapped);
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

  // ========================================================================
  // UI: TOAST + EXPIRY MODAL
  // ========================================================================

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
    // Поприсуска нотификација - неблокирачка алтернатива на alert
    var imeUloga = role === 'lekar' ? 'лекарскиот' : 'пациентскиот';
    var minutiNeaktivnost = Math.round(INACTIVITY_TIMEOUT_MS / 60000);
    var prichina = reason === 'absolute'
      ? 'максималното време за најава помина.'
      : 'немаше активност ' + minutiNeaktivnost + ' минути.';

    // Тивко - ако постои custom toast користи го, инаку alert (само еднаш)
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

  // ========================================================================
  // ACTIVITY LISTENERS
  // ========================================================================

  function attachActivityListeners() {
    if (activityListenersAttached) return;
    activityListenersAttached = true;

    // throttle - touch најмногу еднаш на 5 сек
    var lastTouch = 0;
    var THROTTLE_MS = 5000;
    function throttledTouch() {
      var t = now();
      if (t - lastTouch < THROTTLE_MS) return;
      lastTouch = t;
      touchActivity();
    }

    var events = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'click'];
    events.forEach(function (ev) {
      document.addEventListener(ev, throttledTouch, { passive: true });
    });

    // При промена на табот - провери веднаш
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') tick();
    });

    // При focus на прозорецот - провери
    window.addEventListener('focus', tick);

    // Освежи активност при секој fetch (вистинско користење на сајтот)
    if (window.fetch) {
      var origFetch = window.fetch.bind(window);
      window.fetch = function () {
        throttledTouch();
        return origFetch.apply(null, arguments);
      };
    }
  }

  // ========================================================================
  // STORAGE SYNC (промена во друг таб)
  // ========================================================================
  window.addEventListener('storage', function (e) {
    if (e.key === KEY_PACIENT || e.key === KEY_LEKAR) {
      // друг таб одјавил - извести script.js да се синхронизира
      try {
        var role = e.key === KEY_LEKAR ? 'lekar' : 'pacient';
        window.dispatchEvent(new CustomEvent('kbs:session-sync', {
          detail: { role: role, valueExists: !!e.newValue }
        }));
      } catch (err) {}
    }
  });

  // ========================================================================
  // EXPORT
  // ========================================================================
  window.KBSession = {
    start: startSession,
    get: getSession,
    end: endSession,
    touch: touchActivity,
    // Помошни (ретко потребни)
    _config: {
      INACTIVITY_TIMEOUT_MS: INACTIVITY_TIMEOUT_MS,
      ABSOLUTE_TIMEOUT_MS: ABSOLUTE_TIMEOUT_MS,
      WARN_BEFORE_MS: WARN_BEFORE_MS
    }
  };

  // Auto-start
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      attachActivityListeners();
      startTicking();
      tick();
    });
  } else {
    attachActivityListeners();
    startTicking();
    tick();
  }
})();
