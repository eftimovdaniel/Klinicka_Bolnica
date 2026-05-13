// API базен URL – автоматски се прилагодува (вклучително и за file:// протокол при локален развој)
var API_BASE = (function() {
  var h = window.location.hostname;
  var p = window.location.protocol;
  if (p === 'file:' || !h || h === 'localhost' || h === '127.0.0.1') {
    return 'http://localhost:8000';
  }
  return p + '//' + window.location.host;
})();

// Функција за добивање на параметри од URL
function getURLParameter(name) {
  const urlParams = new URLSearchParams(window.location.search);
  return decodeURIComponent(urlParams.get(name) || '');
}

// Опис за различни оддели
const oddelDescriptions = {
  
  'Педијатрија': 'Педијатрискиот оддел се занимава со здравствена нега за деца и адолесценти. Обезбедуваме превентивна нега, дијагностика и лекување на различни детски заболувања, вакцинации и редовни прегледи.',
  'Ортопедија': 'Ортопедскиот оддел се занимава со дијагностика и лекување на заболувања и повреди на коските, зглобовите и мускулите. Обезбедуваме конзервативно и хируршко лекување за различни ортопедски проблеми.',
  'Гинекологија': 'Гинеколошкиот оддел се занимава со здравствена нега за жени, вклучувајќи прегледи, дијагностика и лекување на гинеколошки заболувања, превентивни прегледи и консултации.',
  'Офталмологија': 'Офталмолошкиот оддел се занимава со дијагностика и лекување на заболувања на очите. Обезбедуваме прегледи, дијагностички тестови и хируршки зафати за различни очни заболувања.',
  'Радиологија': 'Радиолошкиот оддел се занимава со дијагностичка визуелизација со помош на рендген, CT, MRI и ултразвук. Обезбедуваме прецизна дијагностика за различни заболувања и повреди.',
  'Хирургија': 'Хируршкиот оддел се занимава со хируршки зафати за различни заболувања. Обезбедуваме безбедни и ефикасни хируршки процедури со модерна опрема и искусни хирурзи.',
  'Општа хирургија': 'Одделот за општа хирургија обезбедува хируршки зафати за широк спектар на заболувања. Нашиот тим од искусни хирурзи обезбедува безбедни и ефикасни процедури.',
  'Урологија': 'Уролошкиот оддел се занимава со дијагностика и лекување на заболувања на уринарниот систем кај мажи и жени. Обезбедуваме прегледи и терапија за различни уролошки проблеми.',
  'Неврологија': 'Невролошкиот оддел се занимава со дијагностика и лекување на заболувања на нервниот систем. Обезбедуваме специјализирана нега за пациенти со невролошки заболувања.',
  'Дерматологија': 'Дерматолошкиот оддел се занимава со дијагностика и лекување на заболувања на кожата, косата и ноктите. Обезбедуваме прегледи и терапија за различни дерматолошки проблеми.',
  'Пулмологија': 'Пулмолошкиот оддел се занимава со дијагностика и лекување на заболувања на дишните патишта и белите дробови. Обезбедуваме специјализирана нега за пациенти со респираторни проблеми.',
  'Гастроентерологија': 'Гастроентеролошкиот оддел се занимава со дијагностика и лекување на заболувања на дигестивниот систем. Обезбедуваме прегледи и терапија за различни гастроентеролошки проблеми.',
  'Анестезиологија': 'Одделот за анестезиологија обезбедува анестезија за хируршки зафати и интензивна нега за критично болни пациенти. Нашиот тим обезбедува безбедна и ефикасна анестезија.',
  'Психијатрија': 'Психијатрискиот оддел се занимава со дијагностика и лекување на ментални здравствени проблеми. Обезбедуваме психолошка поддршка и терапија за пациенти со психијатриски заболувања.',
  'Кардиологија': 'Кардиолошкиот оддел се занимава со дијагностика и лекување на срцеви и крвни садови. Обезбедуваме комплетна здравствена нега за пациенти со кардиоваскуларни заболувања, вклучувајќи прегледи, дијагностички тестови (ЕКГ, ехокардиографија), и терапија.',
  'default': 'Овој оддел обезбедува специјализирана здравствена нега за пациенти. Нашиот тим од искусни лекари е посветен на обезбедување на најдобра можна нега за нашите пациенти со модерна опрема и најнови техники на лекување.'
};

// Функција за прикажување на детали за одделот
async function loadOddelDetails() {
  const oddelNaziv = getURLParameter('oddel');
  
  if (!oddelNaziv) {
    document.getElementById('oddel-title').textContent = 'Оддел не е пронајден';
    document.getElementById('oddel-description-text').textContent = 'Ве молиме изберете оддел од листата на услуги.';
    return;
  }
  
  // Прикажи име на одделот
  document.getElementById('oddel-title').textContent = oddelNaziv;
  
  // Прикажи опис (ако постои, инаку default)
  const description = oddelDescriptions[oddelNaziv] || oddelDescriptions['default'];
  document.getElementById('oddel-description-text').textContent = description;
  
  
  await loadLekariForOddel(oddelNaziv);
}

// Мапирање на оддели со специјалности (за подобро мапирање)
const oddelToSpecialtyMap = {
  'Кардиологија': ['Кардиологија'],
  'Педијатрија': ['Педијатрија'],
  'Ортопедија': ['Ортопедија'],
  'Гинекологија': ['Гинекологија'],
  'Офталмологија': ['Офталмологија'],
  'Радиологија': ['Радиологија'],
  'Хирургија': ['Хирургија', 'Општа хирургија'],
  'Општа хирургија': ['Хирургија', 'Општа хирургија'],
  'Урологија': ['Урологија'],
  'Неврологија': ['Неврологија'],
  'Дерматологија': ['Дерматологија'],
  'Пулмологија': ['Пулмологија и Респираторна Алегологија', 'Пулмологија'],
  'Пулмологија и Респираторна Алегологија': ['Пулмологија и Респираторна Алегологија', 'Пулмологија'],
  'Гастроентерологија': ['Гастроерохепатологија', 'Гастроентерологија'],
  'Гастроерохепатологија': ['Гастроерохепатологија', 'Гастроентерологија'],
  'Анестезиологија': ['Анестезиологија со Интензивно лекување', 'Анестезиологија'],
  'Анестезиологија со Интензивно лекување': ['Анестезиологија со Интензивно лекување', 'Анестезиологија'],
  'Психијатрија': ['Психијатрија']
};

// Функција за вчитување на лекари за одреден оддел
async function loadLekariForOddel(oddelNaziv) {
  const container = document.getElementById('lekari-list-details');
  
  try {
    container.innerHTML = '<div class="loading">Вчитувам лекари...</div>';
    
    console.log(`[DEBUG] Вчитување лекари за оддел: ${oddelNaziv}`);
    
    // Прво пробај со точно име на одделот
    let res = await fetch(`${API_BASE}/lekari?specijalnost=${encodeURIComponent(oddelNaziv)}`);
    
    if (!res.ok) {
      throw new Error(`HTTP грешка! Статус: ${res.status}`);
    }
    
    let lekari = await res.json();
    console.log(`[DEBUG] Лекари од API (точно име):`, lekari.length);
    
    // Ако нема лекари, пробај со мапирани специјалности или филтрирај локално
    if (!Array.isArray(lekari) || lekari.length === 0) {
      console.log(`[DEBUG] Нема лекари со точно име, пробувам со мапирање...`);
      const specialties = oddelToSpecialtyMap[oddelNaziv] || [oddelNaziv];
      console.log(`[DEBUG] Мапирани специјалности:`, specialties);
      
      // Вчитај ги сите лекари и филтрирај локално
      const allRes = await fetch(API_BASE + '/lekari');
      if (allRes.ok) {
        const allLekari = await allRes.json();
        console.log(`[DEBUG] Вкупно лекари во базата:`, allLekari.length);
        console.log(`[DEBUG] Сите специјалности:`, [...new Set(allLekari.map(l => l.specijalnost))]);
        
        lekari = allLekari.filter(lekar => {
          const lekarSpecialty = (lekar.specijalnost || '').trim().toLowerCase();
          const oddelLower = oddelNaziv.toLowerCase();
          
          // Проверка за точно совпаѓање или делумно совпаѓање
          const matches = specialties.some(spec => {
            const specLower = spec.toLowerCase();
            return lekarSpecialty === specLower || 
                   lekarSpecialty.includes(specLower) ||
                   specLower.includes(lekarSpecialty);
          });
          
          
          if (!matches) {
            return lekarSpecialty === oddelLower ||
                   lekarSpecialty.includes(oddelLower) ||
                   oddelLower.includes(lekarSpecialty);
          }
          
          return matches;
        });
        
        console.log(`[DEBUG] Филтрирани лекари:`, lekari.length);
      }
    }
    
    if (!Array.isArray(lekari)) {
      throw new Error('API-то не може да врати лекари сместени во базата на податоци');
    }
    
    container.innerHTML = '';
    
    if (lekari.length === 0) {
      container.innerHTML = '<div class="loading">Во моментот не се пронајдени лекари за избраниот оддел</div>';
      return;
    }
    
    // Зачувај ги сите лекари за прогресивно прикажување (по 8 одеднаш = 2 реда)
    window._sviLekari = lekari;
    window._prikazaniLekari = 0;
    window._chekorLekari = 8;
    
    prikazi_lekari();
    
  } catch (err) {
    console.error('Грешка при вчитување на лекари:', err);
    container.innerHTML = `<div class="loading" style="color: red;">Грешка при вчитување на лекари: ${err.message}</div>`;
  }
}

// Прикажува уште `chekorLekari` лекари (или сите ако се притисне Прикажи сите)
function prikazi_lekari(prikaziSite = false) {
  const container = document.getElementById('lekari-list-details');
  const lekari = window._sviLekari || [];
  const chekor = window._chekorLekari || 2;
  
  let novoBrojKe = prikaziSite ? lekari.length : (window._prikazaniLekari + chekor);
  if (novoBrojKe > lekari.length) novoBrojKe = lekari.length;
  
  container.innerHTML = '';
  container.classList.remove('lekari-single', 'lekari-double', 'lekari-triple', 'lekari-multiple');
  container.style.maxWidth = '';
  container.style.marginLeft = '';
  container.style.marginRight = '';
  container.style.justifyItems = '';
  
  const lekariZaPrikaz = lekari.slice(0, novoBrojKe);
  lekariZaPrikaz.forEach((lekar) => {
    const card = document.createElement('div');
    card.className = 'lekar-card';
    card.innerHTML = `
      <h3>${lekar.name} ${lekar.surname}</h3>
      <p class="specialty"><strong>Специјалност:</strong> ${lekar.specijalnost || 'Н / П'}</p>
      <a href="mailto:${lekar.email || '#'}" class="email">${lekar.email || 'Нема е-пошта'}</a>
      <button class="btn-appointment-card" onclick="openAppointmentModal(${lekar.doctor_ID})">
        Закажи преглед
      </button>
    `;
    container.appendChild(card);
  });
  
  // Примени специјално форматирање според бројот на ПРИКАЖАНИ лекари
  if (lekariZaPrikaz.length === 1) {
    container.classList.add('lekari-single');
    container.style.maxWidth = '400px';
    container.style.marginLeft = 'auto';
    container.style.marginRight = 'auto';
    container.style.justifyItems = 'center';
  } else if (lekariZaPrikaz.length === 2) {
    container.classList.add('lekari-double');
    container.style.maxWidth = '800px';
    container.style.marginLeft = 'auto';
    container.style.marginRight = 'auto';
  } else if (lekariZaPrikaz.length === 3) {
    container.classList.add('lekari-triple');
    container.style.maxWidth = '1000px';
    container.style.marginLeft = 'auto';
    container.style.marginRight = 'auto';
  } else {
    container.classList.add('lekari-multiple');
  }
  
  window._prikazaniLekari = novoBrojKe;
  
  postavi_kopinja_za_prikaz();
}

// Креира / ажурира копчиња „Прикажи повеќе", „Прикажи сите" и „Прикажи помалку"
function postavi_kopinja_za_prikaz() {
  const lekari = window._sviLekari || [];
  const prikazani = window._prikazaniLekari || 0;
  const section = document.querySelector('.lekari-section');
  if (!section) return;
  
  let controls = document.getElementById('lekari-controls');
  if (!controls) {
    controls = document.createElement('div');
    controls.id = 'lekari-controls';
    controls.className = 'lekari-controls';
    section.appendChild(controls);
  }
  controls.innerHTML = '';
  
  if (prikazani < lekari.length) {
    const btnMore = document.createElement('button');
    btnMore.className = 'btn-show-more';
    btnMore.textContent = 'Прикажи повеќе';
    btnMore.onclick = () => prikazi_lekari(false);
    controls.appendChild(btnMore);
  }
  
  if (prikazani > 8) {
    const btnLess = document.createElement('button');
    btnLess.className = 'btn-show-less';
    btnLess.textContent = 'Прикажи помалку';
    btnLess.onclick = () => {
      window._prikazaniLekari = 0;
      prikazi_lekari(false);
      // Скролај до врвот на секцијата за лекари
      const section = document.querySelector('.lekari-section');
      if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    controls.appendChild(btnLess);
  }
}

// Функција за отворање на модал за закажување
function openAppointmentModal(doctorId) {
  // Зачувај го ID на лекарот во sessionStorage и пренасочи на главната страница
  sessionStorage.setItem('pending_appointment_doctor_id', doctorId);
  window.location.href = 'index.html#lekari';
}

// Вчитај детали при вчитување на страницата
document.addEventListener('DOMContentLoaded', () => {
  loadOddelDetails();
});
