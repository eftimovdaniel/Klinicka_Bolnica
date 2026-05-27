
// Адреса на backend серверот (FastAPI на порт 8000)
const API_URL = "http://localhost:8000/ai-chat/ask";
let kontekst = null; // пр. „Закажи кај Захариев" → AI: „во кое време?" → корисник: „во 12:00" Без контекст, агентот не би „памтел" дека веќе се зборува за Захариев.



//  ФУНКЦИЈА 1: Подготви податоци за најавен корисник
// Се повикува пред секое прашање. Backend-от користи pacient/lekar за да знае кој е најавен (за закажување, мој распоред, итн.).
function zemi_najaven_korisnik() {
  let pacient = null;
  let lekar = null;
  // Глобална променлива currentPacient е поставена при најава
  if (typeof currentPacient !== "undefined" && currentPacient) {
    pacient = {
      pacient_ID: currentPacient.pacient_ID,
      ime: currentPacient.ime,
      prezime: currentPacient.prezime,
      email: currentPacient.email,
      telefon: currentPacient.telefon || "",
    };
  }
  // Истото и за лекар
  if (typeof currentLekar !== "undefined" && currentLekar) {
    lekar = {
      doctor_ID: currentLekar.doctor_ID,
      name: currentLekar.name,
      surname: currentLekar.surname,
      email: currentLekar.email,
      specialty: currentLekar.specialty,
    };
  }
  return { pacient, lekar };
}

//  ФУНКЦИЈА 2: Прати прашање на backend и врати одговор  — мостот меѓу frontend и AI backend-от.
async function prati_prasanje(prasanje) {
  const korisnik = zemi_najaven_korisnik();
  // Пакет што се праќа како JSON на серверот
  const body = {
    prasanje: prasanje,            // текстот од корисникот
    pacient: korisnik.pacient,     // или null ако не е најавен
    lekar: korisnik.lekar,         // или null ако не е лекар
    kontekst: kontekst,            // од претходна порака (за continuation)
  };

  try {
    // HTTP POST на backend endpoint-от
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();// Парсирај JSON одговор
    kontekst = data.kontekst || null;// Зачувај го новиот контекст за следно прашање
  // Врати го одговорот со сите важни полиња
    return {
      odgovor: data.odgovor || "Не добив одговор.",
      navigacija: data.navigacija || null,  // отвори страница (пр. „Кариера")
      akcija: data.akcija || null,          // отвори модал (пр. „login")
    };
  } catch (greska) {
    return { odgovor: "Не можам да се поврзам со серверот." };
  }
}
//  ФУНКЦИЈА 3: Прикажи порака во чатот
// `od_kogo` може да биде "korisnik" или "agent" — за различен стил.
function prikaz_i_porak_a(tekst, od_kogo) {
  const messagesEl = document.getElementById("kbs-ai-messages");
  if (!messagesEl) return;
  const bubble = document.createElement("div");
  bubble.className = "kbs-ai-msg kbs-ai-msg-" + od_kogo;
  bubble.textContent = tekst;
  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight; // Скрол до дното за да се види најновата порака
}
//  ФУНКЦИЈА 4: Изврши акција побарана од backend
// Backend може да врати поле `akcija` — на пр. „отвори ми login модал". Ова е начин AI агентот да „кликне нешто" наместо корисникот.
function izvrsi_akcija(akcija) {
  if (akcija === "otvori_pacient_login") {
    // Корисникот пробал да закаже без најава → отвори login
    if (typeof window.openPacientLoginModal === "function") {
      window.openPacientLoginModal();
    }
  } else if (akcija === "otvori_lekar_login") {
    // Пробал нешто што бара лекарска најава
    if (typeof window.openLekarLoginModal === "function") {
      window.openLekarLoginModal();
    }
  } else if (akcija === "osvezi_admin_dezurstva") {
    // Директор додал дежурство → освежи листа во админ панел
    if (typeof window.loadAdminDezurstva === "function") {
      window.loadAdminDezurstva();
    }
  }
}
//  ФУНКЦИЈА 5: Изврши навигација (отвори таб / страница)
// Backend може да врати `navigacija: { target: "index.html#kariera" }`  → frontend скролува до тој дел / отвора друга страница.
function izvrsi_navigacija(nav) {
  if (!nav || !nav.target) return;
  const target = nav.target;
  // Ако сме на истата страница, само скрол до anchor (#kariera)
  if (target.indexOf("#") !== -1 && target.indexOf(window.location.pathname) !== -1) {
    const hash = target.substring(target.indexOf("#"));
    window.location.hash = hash;
  } else {
    // Инаку оди на друга страница
    window.location.href = target;
  }
}
//  ФУНКЦИЈА 6: Главен handler — кога корисникот ќе притисне „Испрати"
// Ова е „точката на влез" — се повикува од формата во HTML.
async function isprati_porak_a(event) {
  event.preventDefault();  // не дозволи default browser refresh
  const input = document.getElementById("kbs-ai-input");
  const tekst = input.value.trim();
  if (!tekst) return;

  // 1) Прикажи ја пораката на корисникот
  prikaz_i_porak_a(tekst, "korisnik");
  input.value = "";

  // 2) Прати ја на backend и чекај одговор
  const rezultat = await prati_prasanje(tekst);

  // 3) Прикажи го одговорот на агентот
  prikaz_i_porak_a(rezultat.odgovor, "agent");

  // 4) Ако backend побарал акција или навигација — изврши ја
  if (rezultat.akcija) izvrsi_akcija(rezultat.akcija);
  if (rezultat.navigacija) izvrsi_navigacija(rezultat.navigacija);
}
//  ИНИЦИЈАЛИЗАЦИЈА — го поврзува submit на формата со handler-от
function init_ai_chat() {
  const form = document.getElementById("kbs-ai-form");
  if (form) {
    form.addEventListener("submit", isprati_porak_a);
  }
}

// Стартувај кога ќе се вчита целата страница
document.addEventListener("DOMContentLoaded", init_ai_chat);
