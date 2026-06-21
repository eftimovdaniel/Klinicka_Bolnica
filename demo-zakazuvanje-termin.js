/* ============================================================
   ДЕМО ВЕРЗИЈА — само за документацијата (интерактивен преглед).
   Сите податоци подолу (лекари, датуми, термини) живеат единствено
   во меморијата на овој прелистувач, додека е отворена страницата.
   Ништо од ова не комуницира со реален сервер, ниту со базата на
   Клиничка болница — Штип. Освежување на страницата ги бриши сите
   промени и враќа сè на почетната, демо состојба.
   ============================================================ */

var lekari = [
  { ime: 'Ана Стојановска', prezime: 'стојановска', spec: 'Кардиолог' },
  { ime: 'Петар Николов', prezime: 'николов', spec: 'Дерматолог' },
  { ime: 'Сара Трајкова', prezime: 'трајкова', spec: 'Офталмолог' }
];

var SLOTOVI = ['09:00', '09:30', '10:00', '10:30', '11:00', '11:30', '12:00', '12:30', '13:00', '13:30', '14:00', '14:30'];

var DATUMI = generirajDatumi(6);

// "зафатени" термини за демо (клуч: "<lekarIdx>-<datumIdx>")
var zafateniSlots = {
  '0-0': ['09:00', '09:30', '11:00'],
  '1-0': ['10:00'],
  '2-1': ['09:00', '09:30', '10:00', '10:30']
};

var zakazaniDemo = [];
var izbor = { lekarIdx: null, datumIdx: null, vreme: null };

/* ---------- Генерирање датуми (само работни дена, почнувајќи од денес) ---------- */
function generirajDatumi(broj) {
  var rezultat = [];
  var denovi = ['нед', 'пон', 'вто', 'сре', 'чет', 'пет', 'саб'];
  var cur = new Date();
  while (rezultat.length < broj) {
    cur.setDate(cur.getDate() + 1);
    var d = cur.getDay();
    if (d !== 0 && d !== 6) {
      var den = ('0' + cur.getDate()).slice(-2);
      var mes = ('0' + (cur.getMonth() + 1)).slice(-2);
      rezultat.push({ label: denovi[d] + ' ' + den + '.' + mes, denNaziv: denovi[d] });
    }
  }
  return rezultat;
}

/* ---------- Чекори ---------- */
function goStep(name) {
  var steps = ['lekar', 'datum', 'slot', 'potvrda'];
  steps.forEach(function (s) {
    document.getElementById('step-' + s).classList.toggle('hidden', s !== name);
  });
  document.getElementById('step-num').textContent = (steps.indexOf(name) + 1);
}

function restartFlow() {
  izbor = { lekarIdx: null, datumIdx: null, vreme: null };
  document.getElementById('lekar-search').value = '';
  renderLekari();
  goStep('lekar');
}

/* ---------- Чекор 1: лекари ---------- */
function renderLekari() {
  var q = document.getElementById('lekar-search').value.trim().toLowerCase();
  var box = document.getElementById('lekari-list');
  var html = '';
  lekari.forEach(function (l, idx) {
    if (q && l.ime.toLowerCase().indexOf(q) === -1 && l.spec.toLowerCase().indexOf(q) === -1) return;
    html += '<div class="card"><div class="card-head"><b>д-р ' + esc(l.ime) + '</b>' +
      '<span class="badge spec">' + esc(l.spec) + '</span></div>' +
      '<button class="btn-red small" onclick="izberiLekar(' + idx + ')">Закажи преглед</button></div>';
  });
  box.innerHTML = html || '<p class="sub" style="text-align:center">Нема лекар според тоа пребарување.</p>';
}

function izberiLekar(idx) {
  izbor.lekarIdx = idx;
  izbor.datumIdx = null;
  izbor.vreme = null;
  document.getElementById('izbran-lekar-ime').textContent = 'д-р ' + lekari[idx].ime + ' (' + lekari[idx].spec + ')';
  renderDatumi();
  goStep('datum');
}

/* ---------- Чекор 2: датум ---------- */
function renderDatumi() {
  var box = document.getElementById('datumi-list');
  var html = '';
  DATUMI.forEach(function (d, idx) {
    html += '<button type="button" class="datum-btn" onclick="izberiDatum(' + idx + ')">' + d.label + '</button>';
  });
  box.innerHTML = html;
}

function izberiDatum(idx) {
  izbor.datumIdx = idx;
  izbor.vreme = null;
  document.getElementById('izbran-datum').textContent = DATUMI[idx].label + ' — д-р ' + lekari[izbor.lekarIdx].ime;
  renderSloti();
  goStep('slot');
}

/* ---------- Чекор 3: термини ---------- */
function renderSloti() {
  var box = document.getElementById('sloti-grid');
  var key = izbor.lekarIdx + '-' + izbor.datumIdx;
  var zafateni = zafateniSlots[key] || [];
  var html = '';
  SLOTOVI.forEach(function (t) {
    var taken = zafateni.indexOf(t) !== -1;
    html += '<button type="button" class="slot-btn' + (taken ? ' taken' : '') + '"' +
      (taken ? ' disabled' : ' onclick="izberiSlot(\'' + t + '\')"') + '>' + t + '</button>';
  });
  box.innerHTML = html;
  document.getElementById('sloti-note').textContent = zafateni.length
    ? ('Засивените термини (' + zafateni.join(', ') + ') се веќе зафатени.')
    : 'Сите термини за овој ден се слободни.';
}

function izberiSlot(t) {
  izbor.vreme = t;
  prikaziRezime();
  goStep('potvrda');
}

/* ---------- Чекор 4: потврда ---------- */
function prikaziRezime() {
  var l = lekari[izbor.lekarIdx];
  var d = DATUMI[izbor.datumIdx];
  document.getElementById('pregled-rezime').innerHTML =
    '<p class="meta"><strong>Лекар:</strong> д-р ' + esc(l.ime) + ' (' + esc(l.spec) + ')</p>' +
    '<p class="meta"><strong>Датум:</strong> ' + d.label + '</p>' +
    '<p class="meta"><strong>Време:</strong> ' + izbor.vreme + '</p>' +
    '<p class="sub">Име, презиме, телефон и е-пошта се веќе познати од вашиот профил — не треба повторно да ги внесувате.</p>';
}

function potvrdiZakazuvanje() {
  var key = izbor.lekarIdx + '-' + izbor.datumIdx;
  var zafateni = zafateniSlots[key] || [];
  if (zafateni.indexOf(izbor.vreme) !== -1) {
    toast('Во меѓувреме некој друг го резервирал тој термин. Изберете друг.');
    renderSloti();
    goStep('slot');
    return;
  }
  var l = lekari[izbor.lekarIdx];
  var d = DATUMI[izbor.datumIdx];
  var napomena = document.getElementById('zakaz-napomena').value.trim();

  zakazaniDemo.push({
    lekarIdx: izbor.lekarIdx, datumIdx: izbor.datumIdx,
    lekar: l.ime, spec: l.spec, datumLabel: d.label, vreme: izbor.vreme, napomena: napomena
  });
  if (!zafateniSlots[key]) zafateniSlots[key] = [];
  zafateniSlots[key].push(izbor.vreme);

  document.getElementById('zakaz-napomena').value = '';
  renderIdniDemo();
  toast('Терминот е закажан! Потврда е „испратена" на marija@example.com.');
  document.getElementById('lekar-search').value = '';
  renderLekari();
  goStep('lekar');
}

/* ---------- Идни термини (демо) ---------- */
function renderIdniDemo() {
  var box = document.getElementById('idni-demo-list');
  if (!zakazaniDemo.length) {
    box.innerHTML = '<p class="sub" style="text-align:center">Немате закажани термини во ова демо — закажете еден погоре.</p>';
    return;
  }
  var html = '';
  zakazaniDemo.forEach(function (p, i) {
    html += '<div class="card"><div class="card-head"><b>д-р ' + esc(p.lekar) + '</b>' +
      '<span class="badge zakazan">закажан</span></div>' +
      '<div class="meta">' + p.datumLabel + ' · ' + p.vreme + ' · ' + esc(p.spec) + '</div>' +
      (p.napomena ? '<div class="meta">Напомена: ' + esc(p.napomena) + '</div>' : '') +
      '<button class="btn-outline small" onclick="otkaziDemo(' + i + ')">Откажи термин</button></div>';
  });
  box.innerHTML = html;
}

function otkaziDemo(i) {
  if (!confirm('Дали сте сигурни дека сакате да го откажете овој термин?')) return;
  var p = zakazaniDemo[i];
  var key = p.lekarIdx + '-' + p.datumIdx;
  if (zafateniSlots[key]) {
    zafateniSlots[key] = zafateniSlots[key].filter(function (t) { return t !== p.vreme; });
  }
  zakazaniDemo.splice(i, 1);
  renderIdniDemo();
  toast('Терминот е откажан, слотот е повторно слободен.');
}

/* ---------- AI асистент (демо) ---------- */
function toggleAi() {
  document.getElementById('ai-panel').classList.toggle('hidden');
}

function aiQuick(t) {
  document.getElementById('ai-in').value = t;
  sendAi();
}

function sendAi() {
  var input = document.getElementById('ai-in');
  var text = input.value.trim();
  if (!text) return;
  var box = document.getElementById('ai-msgs');
  box.innerHTML += '<div class="ai-msg user">' + esc(text) + '</div>';
  input.value = '';
  var reply = obradiAiPoraka(text);
  setTimeout(function () {
    box.innerHTML += '<div class="ai-msg bot">' + esc(reply) + '</div>';
    box.scrollTop = box.scrollHeight;
  }, 400);
}

function obradiAiPoraka(text) {
  var low = text.toLowerCase();

  if (low.indexOf('кои термини') !== -1 || low.indexOf('закажани') !== -1) {
    if (!zakazaniDemo.length) return 'Немате закажани термини во ова демо.';
    return zakazaniDemo.map(function (p) {
      return 'д-р ' + p.lekar + ' — ' + p.datumLabel + ' во ' + p.vreme;
    }).join('; ');
  }

  var lekarIdx = -1;
  for (var i = 0; i < lekari.length; i++) {
    if (low.indexOf(lekari[i].prezime) !== -1 || low.indexOf(lekari[i].spec.toLowerCase()) !== -1) {
      lekarIdx = i;
      break;
    }
  }
  if (lekarIdx === -1) {
    return 'Не препознавам лекар во пораката. Пробајте со презиме (на пример „Стојановска") или специјалност.';
  }

  var denMap = {
    'понеделник': 'пон', 'пон': 'пон',
    'вторник': 'вто', 'вто': 'вто',
    'среда': 'сре', 'сре': 'сре',
    'четврток': 'чет', 'чет': 'чет',
    'петок': 'пет', 'пет': 'пет'
  };
  var trazenDen = null;
  for (var key in denMap) {
    if (low.indexOf(key) !== -1) { trazenDen = denMap[key]; break; }
  }

  var datumIdx = 0;
  if (trazenDen) {
    datumIdx = -1;
    for (var j = 0; j < DATUMI.length; j++) {
      if (DATUMI[j].denNaziv === trazenDen) { datumIdx = j; break; }
    }
    if (datumIdx === -1) {
      return 'Нема понуден термин за тој ден во следните неколку работни дена. Пробајте друг ден.';
    }
  }

  var match = text.match(/(\d{1,2})[:.](\d{2})/);
  var vreme = match ? (('0' + match[1]).slice(-2) + ':' + match[2]) : null;
  if (!vreme || SLOTOVI.indexOf(vreme) === -1) {
    return 'Работното време е 09:00–14:30, на секои 30 минути. Кажете време од тој опсег, на пример „во 10:00".';
  }

  var key2 = lekarIdx + '-' + datumIdx;
  var zafateni = zafateniSlots[key2] || [];
  if (zafateni.indexOf(vreme) !== -1) {
    var slobodni = SLOTOVI.filter(function (t) { return zafateni.indexOf(t) === -1; });
    return 'Терминот во ' + vreme + ' е веќе зафатен кај д-р ' + lekari[lekarIdx].ime + '. Слободни се: ' +
      (slobodni.length ? slobodni.join(', ') : 'нема слободни термини тој ден') + '.';
  }

  zakazaniDemo.push({
    lekarIdx: lekarIdx, datumIdx: datumIdx,
    lekar: lekari[lekarIdx].ime, spec: lekari[lekarIdx].spec,
    datumLabel: DATUMI[datumIdx].label, vreme: vreme, napomena: ''
  });
  if (!zafateniSlots[key2]) zafateniSlots[key2] = [];
  zafateniSlots[key2].push(vreme);
  renderIdniDemo();
  return 'Готово! Закажан преглед кај д-р ' + lekari[lekarIdx].ime + ' на ' + DATUMI[datumIdx].label + ' во ' + vreme + '.';
}

/* ---------- Помошни функции ---------- */
function esc(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function toast(msg) {
  var el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  setTimeout(function () { el.classList.add('hidden'); }, 3000);
}

/* ---------- Почетно вчитување ---------- */
renderLekari();
renderIdniDemo();
goStep('lekar');

/* ----------------------------------------------------------------
   Рачно прикачување на window: гарантира дека копчињата со
   onclick="..." во HTML-то ги наоѓаат функциите без разлика на
   начинот на вклучување на овој <script> (CodePen, Cursor,
   обичен <script src="...">, со или без "wrap"/модул-опции).
   ---------------------------------------------------------------- */
window.goStep = goStep;
window.restartFlow = restartFlow;
window.renderLekari = renderLekari;
window.izberiLekar = izberiLekar;
window.izberiDatum = izberiDatum;
window.izberiSlot = izberiSlot;
window.potvrdiZakazuvanje = potvrdiZakazuvanje;
window.otkaziDemo = otkaziDemo;
window.toggleAi = toggleAi;
window.aiQuick = aiQuick;
window.sendAi = sendAi;
