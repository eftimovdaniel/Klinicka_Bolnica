/**
 * AI ЧАТ — едноставна верзија (јадрото на врската меѓу frontend и backend).
 *
 * FLOW во 5 чекори:
 *  1) Корисникот пишува и стиска „Испрати"
 *  2) Пораката се прикажува во чатот
 *  3) JavaScript праќа POST на `/ai-chat/ask` со прашањето + контекст
 *  4) Backend враќа JSON: { odgovor, kontekst, akcija, navigacija }
 *  5) Frontend ја прикажува пораката на агентот + извршува акција/навигација
 */

// API bazen URL: lokalno → direktno :8000; na server → ist host (nginx proksira kon backend)
const API_BASE = (function() {
  var h = window.location.hostname;
  if (!h || h === 'localhost' || h === '127.0.0.1') return 'http://localhost:8000';
  return window.location.protocol + '//' + window.location.host;
})();
const API_URL = API_BASE + "/ai-chat/ask"; // POST endpoint za AI prashanja

// Конверзациски контекст — се памти меѓу пораки за повеќестепен дијалог.
// Пр. „Закажи кај Захариев" → AI: „во кое време?" → корисник: „во 12:00".
// Без контекст, агентот не би „памтел" за кој лекар се зборува.
let kontekst = null; // почетно е null — нема активен разговор


// ─────────────────────────────────────────────────────────────────────────
//  ФУНКЦИЈА 1: Подготви податоци за најавен корисник
// ─────────────────────────────────────────────────────────────────────────
// Се повикува пред секое прашање. Backend користи pacient/lekar за да знае
// кој е најавен (за закажување, мој распоред, итн.).
function zemi_najaven_korisnik() {
  let pacient = null; // ако нема најавен пациент → останува null
  let lekar = null;   // ако нема најавен лекар → останува null

  // Глобалната променлива currentPacient се поставува при најава во script.js
  if (typeof currentPacient !== "undefined" && currentPacient) {
    pacient = {                                       // составуваме објект со податоци
      pacient_ID: currentPacient.pacient_ID,          // ID од база (важно за SQL)
      ime: currentPacient.ime,                        // име за приказ
      prezime: currentPacient.prezime,                // презиме за приказ
      email: currentPacient.email,                    // задолжително за закажување
      telefon: currentPacient.telefon || "",          // ако нема — празен string
    };
  }

  // Истото и за лекар (currentLekar се поставува при лекарска најава)
  if (typeof currentLekar !== "undefined" && currentLekar) {
    lekar = {                                         // објект со лекарски податоци
      doctor_ID: currentLekar.doctor_ID,              // ID од Doctors табела
      name: currentLekar.name,                        // име
      surname: currentLekar.surname,                  // презиме
      email: currentLekar.email,                      // email
      specialty: currentLekar.specialty,              // специјалност (Кардиолог, Уролог...)
    };
  }

  return { pacient, lekar }; // едниот / двата / ниту еден може да бидат null
}


// ─────────────────────────────────────────────────────────────────────────
//  ФУНКЦИЈА 2: Прати прашање на backend и врати одговор (МОСТ frontend ↔ backend)
// ─────────────────────────────────────────────────────────────────────────
async function prati_prasanje(prasanje) {
  const korisnik = zemi_najaven_korisnik(); // подготви ги податоците за најавен корисник

  // Пакет што се праќа како JSON на серверот
  const body = {
    prasanje: prasanje,                     // текстот што го напиша корисникот
    pacient: korisnik.pacient,              // или null ако не е најавен
    lekar: korisnik.lekar,                  // или null ако не е лекар
    kontekst: kontekst,                     // од претходна порака (за continuation)
  };

  try {
    // HTTP POST на backend endpoint-от (главната врска)
    const response = await fetch(API_URL, {
      method: "POST",                       // POST бидејќи праќаме податоци
      headers: { "Content-Type": "application/json" }, // велиме дека body-то е JSON
      body: JSON.stringify(body),           // претвори го JS објектот во JSON string
    });

    const data = await response.json();     // парсирај го JSON одговорот од серверот
    kontekst = data.kontekst || null;       // зачувај го новиот контекст за следно прашање

    // Врати го одговорот со сите важни полиња
    return {
      odgovor: data.odgovor || "Не добив одговор.", // текст за приказ во чатот
      navigacija: data.navigacija || null,           // отвори страница (пр. „Кариера")
      akcija: data.akcija || null,                   // отвори модал (пр. „login")
    };
  } catch (greska) {
    // Network failure — backend не работи или нема интернет
    return { odgovor: "Не можам да се поврзам со серверот." };
  }
}


// ─────────────────────────────────────────────────────────────────────────
//  ФУНКЦИЈА 3: Прикажи порака во чатот
// ─────────────────────────────────────────────────────────────────────────
// `od_kogo` може да биде "korisnik" или "agent" — за различен стил (синo / бело bubble).
function prikaz_i_porak_a(tekst, od_kogo) {
  const messagesEl = document.getElementById("kbs-ai-messages"); // контејнер за пораки
  if (!messagesEl) return;                                        // ако нема контејнер — престани

  const bubble = document.createElement("div");                   // ново bubble
  bubble.className = "kbs-ai-msg kbs-ai-msg-" + od_kogo;          // CSS класа според испраќач
  bubble.textContent = tekst;                                     // постави го текстот (без HTML — безбедно)
  messagesEl.appendChild(bubble);                                 // додади го во чатот

  messagesEl.scrollTop = messagesEl.scrollHeight;                 // скрол до дното (нова порака)
}


// ─────────────────────────────────────────────────────────────────────────
//  ФУНКЦИЈА 4: Изврши акција побарана од backend
// ─────────────────────────────────────────────────────────────────────────
// Backend може да врати `akcija` — на пр. „отвори ми login модал".
// Ова е начин AI агентот да „кликне нешто" на UI наместо корисникот.
function izvrsi_akcija(akcija) {
  if (akcija === "otvori_pacient_login") {                       // случај 1: треба пациент login
    if (typeof window.openPacientLoginModal === "function") {     // ако функцијата постои во script.js
      window.openPacientLoginModal();                             // отвори го модалот
    }
  } else if (akcija === "otvori_lekar_login") {                  // случај 2: треба лекар login
    if (typeof window.openLekarLoginModal === "function") {
      window.openLekarLoginModal();                              // отвори лекар login модал
    }
  } else if (akcija === "osvezi_admin_dezurstva") {              // случај 3: освежи дежурства
    if (typeof window.loadAdminDezurstva === "function") {
      window.loadAdminDezurstva();                               // повторно вчитај ги од база
    }
  }
}


// ─────────────────────────────────────────────────────────────────────────
//  ФУНКЦИЈА 5: Изврши навигација (отвори таб / страница)
// ─────────────────────────────────────────────────────────────────────────
// Backend може да врати `navigacija: { target: "index.html#kariera" }`.
function izvrsi_navigacija(nav) {
  if (!nav || !nav.target) return;                               // нема target → ништо
  const target = nav.target;                                     // пр. „index.html#kariera"

  // Ако target-от е anchor на истата страница → само скрол
  if (target.indexOf("#") !== -1 && target.indexOf(window.location.pathname) !== -1) {
    const hash = target.substring(target.indexOf("#"));           // извади го „#kariera"
    window.location.hash = hash;                                  // скрол до тој дел
  } else {
    window.location.href = target;                                // инаку оди на друга страница
  }
}


// ─────────────────────────────────────────────────────────────────────────
//  ФУНКЦИЈА 6: Главен handler — кога корисникот ќе притисне „Испрати"
// ─────────────────────────────────────────────────────────────────────────
// Ова е „точката на влез" — повикана од submit event на формата.
async function isprati_porak_a(event) {
  event.preventDefault();                                        // не дозволи default browser refresh

  const input = document.getElementById("kbs-ai-input");         // input полето
  const tekst = input.value.trim();                              // прочитај го текстот + исчисти го
  if (!tekst) return;                                            // ако е празно — престани

  // 1) Прикажи ја пораката на корисникот
  prikaz_i_porak_a(tekst, "korisnik");                           // синo bubble
  input.value = "";                                              // исчисти го input полето

  // 2) Прати ја на backend и чекај одговор
  const rezultat = await prati_prasanje(tekst);                  // повикај го мостот

  // 3) Прикажи го одговорот на агентот
  prikaz_i_porak_a(rezultat.odgovor, "agent");                   // бело bubble

  // 4) Ако backend побарал акција или навигација — изврши ги
  if (rezultat.akcija) izvrsi_akcija(rezultat.akcija);           // пр. отвори login
  if (rezultat.navigacija) izvrsi_navigacija(rezultat.navigacija); // пр. отвори Кариера
}


// ─────────────────────────────────────────────────────────────────────────
//  ИНИЦИЈАЛИЗАЦИЈА — го поврзува submit на формата со handler-от
// ─────────────────────────────────────────────────────────────────────────
function init_ai_chat() {
  const form = document.getElementById("kbs-ai-form");           // формата од HTML
  if (form) {
    form.addEventListener("submit", isprati_porak_a);            // врзи submit за нашиот handler
  }
}

// Стартувај кога ќе се вчита целата страница (HTML парсиран)
document.addEventListener("DOMContentLoaded", init_ai_chat);     // event-от се активира еднаш по load
