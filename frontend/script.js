// Овие променливи се користат низ целиот код за чување на состојбата на апликацијата

// API базен URL – автоматски се прилагодува (localhost vs production)
var API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  ? 'http://localhost:8000'
  : (window.location.protocol + '//' + window.location.hostname + ':8000');

// URL на надворешната платформа за матични лекари (резервација на термини). Смени го кога ќе го имаш линкот.
var MATICNI_LEKARI_URL = 'https://mojtermin.mk/health_workers';

let allDoctors = [];  // Листа на сите лекари вчитани од API-то
let filteredDoctors = [];  // Моментално филтрирана листа на лекари (според име и специјалност)
let selectedDoctor = null;  // Лекарот кој е избран за закажување на преглед
let selectedDate = null;  // Избраниот датум за преглед (Date објект)
let selectedTime = null;  // Избраното време за преглед (string формат "HH:MM")
let currentLekar = null;  // Податоци за моментално најавениот лекар (за приказ на неговите термини)
let currentPacient = null;  // Податоци за моментално најавениот пациент (за закажување на прегледи)
let displayedDoctorsCount = 8;  // Почетно прикажуваме 8 лекари (2 реда x 4 колони), може да се зголеми со "Прикажи повеќе"

// Врати го најавениот пациент од sessionStorage (за да може да закаже по враќање од oddel-details)
(function restorePacientSession() {
  try {
    var saved = sessionStorage.getItem('currentPacient');
    if (saved) {
      var parsed = JSON.parse(saved);
      if (parsed && (parsed.pacient_ID || parsed.email)) {
        currentPacient = parsed;
      }
    }
  } catch (e) {}
})();

// Врати го најавениот лекар (директор) од sessionStorage – да остане најавен по објава/превчитување
(function restoreLekarSession() {
  try {
    var saved = sessionStorage.getItem('currentLekar');
    if (saved) {
      var parsed = JSON.parse(saved);
      if (parsed && parsed.doctor_ID) {
        currentLekar = parsed;
      }
    }
  } catch (e) {}
})();

// Константа за автоматско менување на годината во footer-от
const yearSpan = document.getElementById('year');
if (yearSpan) {
  yearSpan.textContent = new Date().getFullYear();
}
// ============================================================================
// ФУНКЦИИ ЗА ВЧИТУВАЊЕ И ПРИКАЗУВАЊЕ НА ЛЕКАРИ
// ============================================================================

// Функција за вчитување на лекари од API-то
// Според PDF: "Лекарите ќе имаат целосен пристап до медицинската слика и основните податоци за пациентот"
// Оваа функција ги вчитува сите достапни лекари од базата на податоци преку REST API
async function loadLekari() {
  try {
    const container = document.getElementById('lekari-list');
    
    if (!container) {
      return;
    }

    container.innerHTML = '<div class="loading">Вчитувам лекари...</div>';

    const res = await fetch(API_BASE + '/lekari');

    if (!res.ok) {
      throw new Error(`HTTP грешка! Статус: ${res.status}`);
    }

    const data = await res.json();
    
    if (!Array.isArray(data)) {
      throw new Error('API-то не врати листа од лекари');
    }

    allDoctors = data;
    filteredDoctors = data; // Иницијално, филтрираната листа е иста како сите лекари

    if (data.length === 0) {
      container.innerHTML = '<div class="loading">Нема достапни лекари.</div>';
      return;
    }

    renderDoctors(data);
    populateSpecialtyFilter(data);
  } catch (err) {
    const container = document.getElementById('lekari-list');
    if (container) {
      container.innerHTML =
        `<div class="loading" style="color: red;">Грешка при вчитување на лекарите: ${err.message}</div>`;
    }
  }
}

// Функција за прикажување на лекари во grid формат
// Креира HTML картички за секој лекар со неговите основни информации
// Според PDF: "Системот би бил со едноставен интерфејс за полесно управување"
function renderDoctors(doctors) {
  const container = document.getElementById('lekari-list');
  const controlsDiv = document.querySelector('.lekari-controls');
  container.innerHTML = '';

  if (doctors.length === 0) {
    container.innerHTML = '<div class="loading">Нема лекари кои одговараат на филтерот.</div>';
    if (controlsDiv) controlsDiv.style.display = 'none';
    return;
  }

  // Прикажи само првите displayedDoctorsCount лекари
  const doctorsToShow = doctors.slice(0, displayedDoctorsCount);
  
  doctorsToShow.forEach(doctor => {
    const div = document.createElement('div');
    div.className = 'lekar-card';
    div.innerHTML = `
      <h3>${doctor.name} ${doctor.surname}</h3>
      <p class="specialty"><strong>Специјалност:</strong> ${doctor.specijalnost || 'Н / П'}</p>
      <a href="mailto:${doctor.email || '#'}" class="email">${doctor.email || 'Нема е-пошта'}</a>
      <button class="btn-appointment-card" onclick="openAppointmentModal(${doctor.doctor_ID})">Закажи преглед</button>
    `;
    container.appendChild(div);
  });

  // Прикажи/скриј копчињата според бројот на лекари
  if (controlsDiv) {
    const showMoreBtn = document.getElementById('show-more-btn');
    const showLessBtn = document.getElementById('show-less-btn');
    
    if (doctors.length > 8) {
      controlsDiv.style.display = 'block';
      if (showMoreBtn) {
        showMoreBtn.style.display = doctors.length > displayedDoctorsCount ? 'inline-block' : 'none';
      }
      if (showLessBtn) {
        showLessBtn.style.display = displayedDoctorsCount > 8 ? 'inline-block' : 'none';
      }
    } else {
      controlsDiv.style.display = 'none';
    }
  }
}

// Функција за пополнување на dropdown менито за филтрирање по специјалност
// Го извлекува уникатниот список на специјалности од листата на лекари
function populateSpecialtyFilter(doctors) {
  const specialtySelect = document.getElementById('filter-specialty');
  const specialties = [...new Set(doctors.map(d => d.specijalnost).filter(Boolean))].sort();

  specialties.forEach(specialty => {
    const option = document.createElement('option');
    option.value = specialty;
    option.textContent = specialty;
    specialtySelect.appendChild(option);
  });
}

// Функција за филтрирање на лекари според име и специјалност
// Корисникот може да пребарува по име и да филтрира по специјалност
function filterDoctors() {
  const nameFilter = document.getElementById('filter-name').value.toLowerCase();
  const specialtyFilter = document.getElementById('filter-specialty').value;

  filteredDoctors = allDoctors.filter(doctor => {
    const matchesName = !nameFilter ||
      `${doctor.name} ${doctor.surname}`.toLowerCase().includes(nameFilter);
    const matchesSpecialty = !specialtyFilter || doctor.specijalnost === specialtyFilter;

    return matchesName && matchesSpecialty;
  });

  // Ресетирај бројот на прикажани лекари кога се менува филтерот
  displayedDoctorsCount = 8;
  renderDoctors(filteredDoctors);
}

// Функција за поставување на event listeners за филтрирање
// Се прикачуваат слушатели на input и select полињата за автоматско филтрирање при промена
function setupFilters() {
  const nameInput = document.getElementById('filter-name');
  const specialtySelect = document.getElementById('filter-specialty');

  if (nameInput) {
    nameInput.addEventListener('input', filterDoctors);
  }

  if (specialtySelect) {
    specialtySelect.addEventListener('change', filterDoctors);
  }
}
// ФУНКЦИИ ЗА ЗАКАЖУВАЊЕ НА ПРЕГЛЕД

// Прикажи/скриј линк „Закажи преглед“ во навигацијата кога пациентот е најавен
function updateNavForPacient() {
  var navLink = document.getElementById('nav-zakazi-pregled');
  if (navLink) navLink.style.display = currentPacient ? 'inline-block' : 'none';
  var callout = document.getElementById('lekari-pacient-callout');
  if (callout) {
    var dismissed = sessionStorage.getItem('lekari_callout_dismissed');
    callout.style.display = (currentPacient && !dismissed) ? 'block' : 'none';
  }
}

function dismissLekariCallout() {
  sessionStorage.setItem('lekari_callout_dismissed', '1');
  var callout = document.getElementById('lekari-pacient-callout');
  if (callout) callout.style.display = 'none';
}

function closeAppointmentSuccess() {
  var el = document.getElementById('appointment-success-overlay');
  if (el) el.style.display = 'none';
  currentPacient = null;
  try { sessionStorage.removeItem('currentPacient'); } catch (e) {}
  updateNavForPacient();
}

// Функција за отворање на модален прозорец за закажување на преглед
// Според PDF: "Пациентот по извршување на снимката, треба да се консултира со лекар"
// Оваа функција отвора модал каде пациентот може да избере датум и време за преглед
window.openAppointmentModal = function (doctorId) {
  var id = typeof doctorId === 'number' ? doctorId : parseInt(doctorId, 10);
  if (isNaN(id)) {
    alert('Неважечки избор на лекар.');
    return;
  }

  if (!currentPacient) {
    sessionStorage.setItem('pending_appointment_doctor_id', id);
    openPacientLoginModal();
    return;
  }

  selectedDoctor = allDoctors.find(function (d) { return Number(d.doctor_ID) === id; });
  openAppointmentModalInternal(id);
};

// Внатрешна функција за отворање на модалот за закажување (кога пациентот е најавен)
async function openAppointmentModalInternal(doctorId) {
  const modal = document.getElementById('appointment-modal');
  const doctorInfo = document.getElementById('appointment-doctor-info');
  const doctorIdInput = document.getElementById('appointment-doctor-id');
  const pacientInfoDisplay = document.getElementById('pacient-info-display');
  const pacientNameDisplay = document.getElementById('pacient-name-display');
  const pacientEmailDisplay = document.getElementById('pacient-email-display');

  var doctorIdNum = typeof doctorId === 'number' ? doctorId : parseInt(doctorId, 10);
  if (isNaN(doctorIdNum)) {
    alert('Неважечки избор на лекар.');
    return;
  }
  if (!selectedDoctor || Number(selectedDoctor.doctor_ID) !== doctorIdNum) {
    selectedDoctor = allDoctors.find(function (d) { return Number(d.doctor_ID) === doctorIdNum; });
    if (!selectedDoctor) {
      try {
        const res = await fetch(API_BASE + '/lekari');
        if (res.ok) {
          const lekari = await res.json();
          selectedDoctor = lekari.find(function (d) { return Number(d.doctor_ID) === doctorIdNum; });
          if (selectedDoctor) allDoctors = lekari;
        }
      } catch (err) {
        console.error('Грешка при вчитување на лекари за закажување:', err);
      }
    }
  }

  if (!selectedDoctor) {
    alert('Лекарот не е пронајден.');
    return;
  }

  doctorInfo.innerHTML = `
    <h3>${selectedDoctor.name} ${selectedDoctor.surname}</h3>
    <p><strong>Специјалност:</strong> ${selectedDoctor.specijalnost || 'Н/П'}</p>
    <p><strong>Е-пошта:</strong> ${selectedDoctor.email || 'Нема е-пошта'}</p>
  `;

  if (doctorIdInput) {
    doctorIdInput.value = selectedDoctor.doctor_ID || '';
  }

  if (currentPacient && pacientInfoDisplay && pacientNameDisplay && pacientEmailDisplay) {
    pacientInfoDisplay.style.display = 'block';
    pacientNameDisplay.textContent = `${currentPacient.ime || ''} ${currentPacient.prezime || ''}`.trim();
    pacientEmailDisplay.textContent = currentPacient.email || '';
    document.getElementById('patient-ime').value = currentPacient.ime || '';
    document.getElementById('patient-prezime').value = currentPacient.prezime || '';
    document.getElementById('patient-email').value = currentPacient.email || '';
    document.getElementById('patient-telefon').value = currentPacient.telefon || '';
    const pacientIdInput = document.getElementById('pacient-id');
    if (pacientIdInput) pacientIdInput.value = currentPacient.pacient_ID || '';
  } else {
    if (pacientInfoDisplay) pacientInfoDisplay.style.display = 'none';
  }

  selectedDate = null;
  selectedTime = null;
  if (modal) {
    modal.style.display = 'block';
    modal.setAttribute('aria-hidden', 'false');
  }
  var calendarSection = modal ? modal.querySelector('.calendar-section') : null;
  if (calendarSection) calendarSection.style.display = 'block';
  renderCalendar();
  clearTimeSlots();
}

// Close appointment modal
function closeAppointmentModal() {
  const modal = document.getElementById('appointment-modal');
  modal.style.display = 'none';
  selectedDoctor = null;
  selectedDate = null;
  selectedTime = null;

  const form = document.getElementById('appointment-form');
  if (form) {
    form.reset();
  }
}

// Setup modal close button
function setupModal() {
  const modal = document.getElementById('appointment-modal');
  const closeBtn = modal.querySelector('.close');

  if (closeBtn) {
    closeBtn.addEventListener('click', closeAppointmentModal);
  }

  window.addEventListener('click', (e) => {
    if (e.target === modal) {
      closeAppointmentModal();
    }
  });
}
// ФУНКЦИИ ЗА КАЛЕНДАР И ИЗБОР НА ДАТУМ И ВРЕМЕ

// Функција за рендерирање на календар за избор на датум за преглед
// Според PDF: "Не се закажуваат прегледи во сабота и недела"
// Календарот ги прикажува само работните денови (понеделник-петок)
function renderCalendar() {
  const calendar = document.getElementById('calendar');
  if (!calendar) return;

  const today = new Date();
  const currentMonth = today.getMonth();
  const currentYear = today.getFullYear();

  let displayMonth = currentMonth;
  let displayYear = currentYear;

  function updateCalendar() {
    calendar.innerHTML = '';

    const nav = document.createElement('div');
    nav.className = 'calendar-nav';
    nav.innerHTML = `
      <button onclick="prevMonth()">← Претходен</button>
      <span>${getMonthName(displayMonth)} ${displayYear}</span>
      <button onclick="nextMonth()">Следен →</button>
    `;
    calendar.appendChild(nav);

    const monthGrid = document.createElement('div');
    monthGrid.className = 'calendar-month';

    const dayNames = ['Пон', 'Вто', 'Сре', 'Чет', 'Пет', 'Саб', 'Нед'];
    dayNames.forEach(day => {
      const header = document.createElement('div');
      header.className = 'calendar-header';
      header.textContent = day;
      monthGrid.appendChild(header);
    });

    const firstDay = new Date(displayYear, displayMonth, 1);
    const lastDay = new Date(displayYear, displayMonth + 1, 0);
    const daysInMonth = lastDay.getDate();
    const startingDayOfWeek = firstDay.getDay();
    const adjustedStart = startingDayOfWeek === 0 ? 6 : startingDayOfWeek - 1;

    for (let i = 0; i < adjustedStart; i++) {
      const empty = document.createElement('div');
      monthGrid.appendChild(empty);
    }

    for (let day = 1; day <= daysInMonth; day++) {
      const dayCell = document.createElement('div');
      dayCell.className = 'calendar-day';
      dayCell.textContent = day;

      const cellDate = new Date(displayYear, displayMonth, day);
      const isPast = cellDate < new Date(today.getFullYear(), today.getMonth(), today.getDate());
      const isToday = cellDate.toDateString() === today.toDateString();
      const isWeekend = cellDate.getDay() === 0 || cellDate.getDay() === 6; // 0 = недела, 6 = сабота

      if (isPast || isWeekend) {
        dayCell.classList.add('past', 'disabled');
        if (isWeekend) {
          dayCell.title = 'Не се закажуваат прегледи во сабота и недела';
        }
      } else {
        dayCell.addEventListener('click', function () {
          selectDate(cellDate, this);
        });
        if (isToday) {
          dayCell.style.fontWeight = 'bold';
        }
      }

      monthGrid.appendChild(dayCell);
    }

    calendar.appendChild(monthGrid);
  }

  window.prevMonth = function () {
    displayMonth--;
    if (displayMonth < 0) {
      displayMonth = 11;
      displayYear--;
    }
    updateCalendar();
  };

  window.nextMonth = function () {
    displayMonth++;
    if (displayMonth > 11) {
      displayMonth = 0;
      displayYear++;
    }
    updateCalendar();
  };

  updateCalendar();
}

function getMonthName(month) {
  const months = [
    'Јануари', 'Февруари', 'Март', 'Април', 'Мај', 'Јуни',
    'Јули', 'Август', 'Септември', 'Октомври', 'Ноември', 'Декември'
  ];
  return months[month];
}

function selectDate(date, element) {
  // Проверка дали е викенд (сабота или недела)
  const dayOfWeek = date.getDay();
  if (dayOfWeek === 0 || dayOfWeek === 6) {
    alert('Не се закажуваат прегледи во сабота и недела. Изберете друг датум.');
    return;
  }

  selectedDate = date;
  selectedTime = null;

  document.querySelectorAll('.calendar-day').forEach(day => {
    day.classList.remove('selected');
  });

  if (element) {
    element.classList.add('selected');
  }

  const dateInput = document.getElementById('appointment-date');
  if (dateInput) {
    dateInput.value = date.toISOString().split('T')[0];
  }

  renderTimeSlots();
}

// Функција за прикажување на достапни временски слотови за избраниот датум
// Проверува кои термини се веќе закажани и ги прикажува само достапните времена
// Според PDF: "Системот ќе генерира дијагноза која се прегледува и податоците се евидентираат во базата"
async function renderTimeSlots() {
  const timeSlotsContainer = document.getElementById('time-slots');
  if (!timeSlotsContainer || !selectedDate || !selectedDoctor) {
    clearTimeSlots();
    return;
  }

  const slots = [];
  for (let hour = 9; hour < 17; hour++) {
    slots.push(`${hour.toString().padStart(2, '0')}:00`);
    slots.push(`${hour.toString().padStart(2, '0')}:30`);
  }

  timeSlotsContainer.innerHTML = '<div class="loading">Вчитувам достапни термини...</div>';

  try {
    const datumStr = selectedDate.toISOString().split('T')[0];
    const res = await fetch(`${API_BASE}/termini/dostapni?lekar_id=${selectedDoctor.doctor_ID}&datum=${datumStr}`);
    
    if (!res.ok) {
      throw new Error(`HTTP грешка! Статус: ${res.status}`);
    }

    const zafateniTermini = await res.json();
    const zafateniSet = new Set(zafateniTermini.map(t => t.length === 5 ? t : t.substring(0, 5)));

    timeSlotsContainer.innerHTML = '';

    slots.forEach(slot => {
      const slotDiv = document.createElement('div');
      slotDiv.className = 'time-slot';
      slotDiv.textContent = slot;

      const isAvailable = !zafateniSet.has(slot);

      if (isAvailable) {
        slotDiv.addEventListener('click', () => selectTime(slot, slotDiv));
      } else {
        slotDiv.classList.add('disabled');
      }

      timeSlotsContainer.appendChild(slotDiv);
    });
  } catch (err) {
    timeSlotsContainer.innerHTML = '<div class="loading" style="color: red;">Грешка при вчитување на термини.</div>';
  }
}

function selectTime(time, element) {
  selectedTime = time;

  document.querySelectorAll('.time-slot').forEach(slot => {
    slot.classList.remove('selected');
  });

  element.classList.add('selected');

  const timeInput = document.getElementById('appointment-time');
  if (timeInput) {
    timeInput.value = time;
  }
}

function clearTimeSlots() {
  const timeSlotsContainer = document.getElementById('time-slots');
  if (timeSlotsContainer) {
    timeSlotsContainer.innerHTML = '';
  }
}

// Функција за поставување на обработка на формата за закажување на преглед
// Според PDF: "По завршување на медицинските услуги се иницира процес на наплата"
// Оваа функција ги собира податоците од формата и ги испраќа на backend за зачувување во базата
function setupAppointmentForm() {
  const form = document.getElementById('appointment-form');
  if (form) {
    form.removeEventListener('submit', null); // Чистиме претходни лисенери
    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      // Проверка дали се избрани датум и време од календарот
      if (!selectedDate || !selectedTime) {
        alert('Ве молиме изберете датум и време од календарот.');
        return;
      }

      // Дополнителна проверка за викенд (сабота и недела)
      const dayOfWeek = selectedDate.getDay();
      if (dayOfWeek === 0 || dayOfWeek === 6) {
        alert('Не се закажуваат прегледи во сабота и недела. Изберете друг датум.');
        return;
      }

      // Собирање на податоците точно како што ти треба
      const appointmentData = {
        lekar_id: parseInt(document.getElementById('appointment-doctor-id').value),
        datum: document.getElementById('appointment-date').value || new Date().toISOString().split('T')[0],
        vreme: document.getElementById('appointment-time').value || '00:00',
        ime: document.getElementById('patient-ime').value.trim(),
        prezime: document.getElementById('patient-prezime').value.trim(),
        email: document.getElementById('patient-email').value.trim(),
        telefon: document.getElementById('patient-telefon').value.trim(),
        napomena: document.getElementById('patient-napomena').value.trim()
      };
      try {
        const response = await fetch(API_BASE + '/termini', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(appointmentData)
        });

        var result = {};
        try {
          result = await response.json();
        } catch (_) {
          result = { detail: response.statusText || 'Грешка од сервер' };
        }

        if (response.ok) {
          var mod = document.getElementById('appointment-modal');
          if (mod) mod.style.display = 'none';
          form.reset();
          selectedDate = null;
          selectedTime = null;
          selectedDoctor = null;
          var successEl = document.getElementById('appointment-success-overlay');
          if (successEl) successEl.style.display = 'flex';
        } else {
          alert('Грешка при закажување: ' + (result.detail || result.message || 'Обидете се повторно.'));
        }
      } catch (err) {
        alert('Серверот не е достапен. Проверете дали backend работи на ' + API_BASE);
      }
    });
  }
}
// ФУНКЦИИ ЗА ВЧИТУВАЊЕ НА УСЛУГИ И ОДДЕЛИ

// Функција за вчитување на услуги/оддели од API-то
// Според PDF: "Обезбедуваме комплетна здравствена нега преку нашите специјализирани оддели"
// Услугите се прикажуваат поделени во медицински гранки (хируршки, интерни, итн.)
async function loadUslugi() {
  try {
    const container = document.getElementById('uslugi-list');
    
    if (!container) {
      return;
    }

    container.innerHTML = '<div class="loading">Вчитувам услуги...</div>';

    const res = await fetch(API_BASE + '/uslugi');

    if (!res.ok) {
      throw new Error(`HTTP грешка! Статус: ${res.status}`);
    }

    const data = await res.json();
    
    if (!Array.isArray(data)) {
      throw new Error('API-то не врати листа од услуги');
    }

    container.innerHTML = '';

    if (data.length === 0) {
      container.innerHTML = '<div class="loading">Нема достапни услуги.</div>';
      return;
    }

    // Креирај анимирана лента со услуги
    const marqueeWrapper = document.createElement('div');
    marqueeWrapper.className = 'uslugi-marquee-wrapper';
    
    // Копчиња за контрола
    const prevButton = document.createElement('button');
    prevButton.className = 'uslugi-nav-btn uslugi-nav-btn-prev';
    prevButton.innerHTML = `
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M15 18l-6-6 6-6"/>
      </svg>
    `;
    prevButton.setAttribute('aria-label', 'Претходни услуги');
    
    const nextButton = document.createElement('button');
    nextButton.className = 'uslugi-nav-btn uslugi-nav-btn-next';
    nextButton.innerHTML = `
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 18l6-6-6-6"/>
      </svg>
    `;
    nextButton.setAttribute('aria-label', 'Следни услуги');
    
    const marqueeTrack = document.createElement('div');
    marqueeTrack.className = 'uslugi-marquee-track';
    
    // Креирај картички за услугите
    data.forEach((usluga) => {
      const card = document.createElement('div');
      card.className = 'usluga-marquee-card';
      card.style.cursor = 'pointer';
      card.innerHTML = `
        <div class="usluga-card-content">
          <span class="usluga-name">${usluga.naziv || 'Услуга'}</span>
        </div>
      `;
      
      // Додади click event listener за отворање на детали за одделот
      card.addEventListener('click', () => {
        const oddelNaziv = encodeURIComponent(usluga.naziv || '');
        window.location.href = `oddel-details.html?oddel=${oddelNaziv}`;
      });
      
      marqueeTrack.appendChild(card);
    });
    
    // Променливи за позицијата
    let scrollPosition = 0;
    const scrollSpeed = 300;
    let animationId = null;
    let isScrolling = false;
    
    // Функција за скролување
    const scrollToPosition = (targetPosition) => {
      if (isScrolling) return;
      isScrolling = true;
      
      const startPosition = scrollPosition;
      const distance = targetPosition - startPosition;
      const duration = 500;
      let startTime = null;
      
      const animate = (currentTime) => {
        if (startTime === null) startTime = currentTime;
        const timeElapsed = currentTime - startTime;
        const progress = Math.min(timeElapsed / duration, 1);
        
        const ease = progress < 0.5 
          ? 2 * progress * progress 
          : 1 - Math.pow(-2 * progress + 2, 2) / 2;
        
        scrollPosition = startPosition + (distance * ease);
        marqueeTrack.style.transform = `translateX(${-scrollPosition}px)`;
        
        if (progress < 1) {
          animationId = requestAnimationFrame(animate);
        } else {
          isScrolling = false;
          animationId = null;
        }
      };
      
      if (animationId) {
        cancelAnimationFrame(animationId);
      }
      animationId = requestAnimationFrame(animate);
    };
    
    // Event listeners за копчињата
    prevButton.addEventListener('click', () => {
      const maxScroll = marqueeTrack.scrollWidth - marqueeWrapper.offsetWidth;
      scrollToPosition(Math.max(0, scrollPosition - scrollSpeed));
    });
    
    nextButton.addEventListener('click', () => {
      const maxScroll = marqueeTrack.scrollWidth - marqueeWrapper.offsetWidth;
      scrollToPosition(Math.min(maxScroll, scrollPosition + scrollSpeed));
    });
    
    // Автоматско скролување
    let autoScrollInterval = null;
    const startAutoScroll = () => {
      if (autoScrollInterval) return;
      autoScrollInterval = setInterval(() => {
        if (!isScrolling) {
          const maxScroll = marqueeTrack.scrollWidth - marqueeWrapper.offsetWidth;
          if (scrollPosition >= maxScroll) {
            scrollPosition = 0;
          } else {
            scrollPosition += 2.5;
          }
          marqueeTrack.style.transform = `translateX(${-scrollPosition}px)`;
        }
      }, 30);
    };
    
    startAutoScroll();
    
    marqueeWrapper.addEventListener('mouseenter', () => {
      if (autoScrollInterval) {
        clearInterval(autoScrollInterval);
        autoScrollInterval = null;
      }
    });
    
    marqueeWrapper.addEventListener('mouseleave', () => {
      startAutoScroll();
    });
    
    marqueeWrapper.appendChild(prevButton);
    marqueeWrapper.appendChild(nextButton);
    marqueeWrapper.appendChild(marqueeTrack);
    container.appendChild(marqueeWrapper);
  } catch (err) {
    const container = document.getElementById('uslugi-list');
    if (container) {
      container.innerHTML =
        `<div class="loading" style="color: red;">Грешка при вчитување на услуги: ${err.message}</div>`;
    }
  }
}

// ФУНКЦИИ ЗА КАРИЕРА И АПЛИКАЦИИ
// Глобална променлива за чување на избраната позиција од кариера
let selectedOglas = null;

// Функција за вчитување на отворени позиции за работа од API-то
// Според PDF: "Сакаш да бидеш дел од нашиот тим? Погледни ги отворените позиции и аплицирај!"
// КАРИЕРА - ОГЛАСИ ЗА РАБОТА
// Вчитување на огласи за работа од API-то
// Ги вчитува сите активни огласи и ги прикажува во секцијата за кариера
// Автоматски ги филтрира истечените огласи (повеќе од 5 дена од истекот)
async function loadKariera() {
  const container = document.getElementById('kariera-list');
  if (!container) return;
  try {
    container.classList.add('kariera-loading');
    container.innerHTML = '<span class="loading">Вчитувам позиции...</span>';
    const res = await fetch(API_BASE + '/kariera');
    const pozicii = await res.json();
    container.classList.remove('kariera-loading');
    container.innerHTML = '';

    if (pozicii.length === 0) {
      container.innerHTML = '<span class="loading">Нема достапни позиции.</span>';
      container.classList.add('kariera-loading');
      return;
    }

    pozicii.forEach(p => {
      // Проверка дали датумот за пријавување е истечен и дали треба да се прикаже
      let isExpired = false;
      let shouldShow = true;
      
      if (p.rok) {
        try {
          // Парсирај датум во формат DD.MM.YYYY
          const [day, month, year] = p.rok.split('.');
          const deadlineDate = new Date(year, month - 1, day);
          deadlineDate.setHours(23, 59, 59, 999); // Стави на крајот на денот
          
          const today = new Date();
          today.setHours(0, 0, 0, 0); // Стави на почетокот на денот
          
          // Пресметај колку дена се поминале од истекот на рокот за пријавување
          const daysSinceExpiry = Math.floor((today - deadlineDate) / (1000 * 60 * 60 * 24));
          
          // Ако е поминато повеќе од 5 дена од истекот, не го прикажувај воопшто
          if (daysSinceExpiry > 5) {
            shouldShow = false;
            return; // Skip this oglas
          }
          
          // Ако е поминат рокот но помалку од 5 дена, прикажи како истечен (не-кликабилен)
          if (deadlineDate < today) {
            isExpired = true;
          }
        } catch (e) {
          console.error('Грешка при парсирање на датум:', e);
        }
      }
      
      // Ако не треба да се прикаже (повеќе од 5 дена од истекот), прескокни го
      if (!shouldShow) {
        return;
      }
      
      const div = document.createElement('div');
      div.className = 'pozicija-card';
      div.setAttribute('data-id-oglas', p.id_oglas);
      div.setAttribute('data-pozicija', p.naslov);
      
      // Ако е истечен, додади класа и направи не-кликабилен
      if (isExpired) {
        div.classList.add('expired');
        div.style.cursor = 'not-allowed';
        div.style.opacity = '0.6';
      } else {
        div.style.cursor = 'pointer';
      }
      
      div.innerHTML = `
        <h3>${p.naslov}</h3>
        <p>${p.opis}</p>
        <p><strong>Рок:</strong> ${p.rok}</p>
        ${isExpired ? '<p class="expired-badge">ИСТЕЧЕН</p>' : ''}
      `;
      
      // Додади click event за избор на позиција (само ако не е истечен)
      if (!isExpired) {
        div.addEventListener('click', function() {
          // Отстрани selected класа од сите картички
          document.querySelectorAll('.pozicija-card').forEach(card => {
            card.classList.remove('selected');
          });
          
          // Додади selected класа на кликнатата картичка
          div.classList.add('selected');
          
          // Зачувај избрана позиција во глобална променлива
          selectedOglas = {
            id_oglas: p.id_oglas,
            pozicija: p.naslov
          };
          
          // Ажурирај скриени полиња во формата
          document.getElementById('hidden-id-oglas').value = p.id_oglas;
          document.getElementById('hidden-pozicija').value = p.naslov;
          
          // Прикажи информација за избраната позиција
          const infoDiv = document.getElementById('selected-pozicija-info');
          const infoText = document.getElementById('selected-pozicija-text');
          if (infoDiv && infoText) {
            infoText.textContent = `${p.naslov}${p.opis ? ' - ' + p.opis : ''}`;
            infoDiv.style.display = 'block';
          }
          
          // Скролувај до формата за аплицирање
          document.getElementById('kariera-forma').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
      } else {
        // Ако е истечен, додади event listener за да покаже порака при клик
        div.addEventListener('click', function(e) {
          e.preventDefault();
          alert('Рокот за пријавување на овој оглас е истечен.');
        });
      }
      
      container.appendChild(div);
    });
  } catch (err) {
    const c = document.getElementById('kariera-list');
    if (c) {
      c.classList.add('kariera-loading');
      c.innerHTML = '<span class="loading">Грешка при вчитување на позициите.</span>';
    }
  }
}


// Attach form handlers
function attachForms() {
  const kf = document.getElementById('kontakt-forma');
  if (kf) {
    kf.addEventListener('submit', (e) => {
      e.preventDefault();
      alert('Пораката е испратена!');
      e.target.reset();
    });
  }

  const af = document.getElementById('kariera-forma');
  if (af) {
    af.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      // Check if position is selected
      if (!selectedOglas || !selectedOglas.id_oglas) {
        alert('Ве молиме изберете позиција од понудените огласи.');
        return;
      }
      
      const formData = new FormData(e.target);

      try {
        const res = await fetch(API_BASE + '/aplikacija', {
          method: 'POST',
          body: formData
        });

        if (!res.ok) {
          const errorData = await res.json();
          throw new Error(errorData.detail || 'Грешка при испраќање на апликацијата');
        }

        const result = await res.json();
        alert(result.message || 'Апликацијата е испратена!');
        e.target.reset();
        
        // Reset selected position
        selectedOglas = null;
        document.getElementById('selected-pozicija-info').style.display = 'none';
        document.querySelectorAll('.pozicija-card').forEach(card => {
          card.classList.remove('selected');
        });
      } catch (err) {
        alert(err.message || 'Грешка при испраќање на апликацијата.');
      }
    });
  }
}

// Smooth scroll for anchor links
function setupSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        target.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });
      }
    });
  });
}
// ИНИЦИЈАЛИЗАЦИЈА НА АПЛИКАЦИЈАТА
// Главна функција за иницијализација на апликацијата при вчитување на страницата
// Според PDF: "Системот би бил со едноставен интерфејс за полесно управување"
// Оваа функција ги повикува сите потребни функции за вчитување на податоци и поставување на event listeners
function initialize() {
  var navMaticni = document.getElementById('nav-maticni-lekari');
  if (navMaticni && typeof MATICNI_LEKARI_URL === 'string') navMaticni.href = MATICNI_LEKARI_URL;

  // Load services
  if (document.getElementById('uslugi-list')) {
    loadUslugi();
  }

  // Load doctors
  const lekariList = document.getElementById('lekari-list');
  if (lekariList) {
    loadLekari().then(() => {
      setupFilters();
      // По вчитување на лекарите, провери дали има закажан преглед во чекање
      const pendingDoctorId = sessionStorage.getItem('pending_appointment_doctor_id');
      if (pendingDoctorId && currentPacient) {
        sessionStorage.removeItem('pending_appointment_doctor_id');
        setTimeout(() => {
          openAppointmentModalInternal(parseInt(pendingDoctorId));
        }, 500);
      }
    });
  } else {
  }

  // Load career
  if (document.getElementById('kariera-list')) {
    loadKariera();
  }

  attachForms();
  setupModal();
  setupAppointmentForm();
  setupSmoothScroll();
  setupLekarLogin();
  setupLekarPasswordForms();
  setupPacientAuth();
  if (typeof setupAuth === 'function') setupAuth();
  updateNavForPacient();

  var pendingId = sessionStorage.getItem('pending_appointment_doctor_id');
  if (pendingId) {
    if (currentPacient) {
      sessionStorage.removeItem('pending_appointment_doctor_id');
      setTimeout(function () { openAppointmentModalInternal(parseInt(pendingId, 10)); }, 300);
    } else {
      openPacientLoginModal();
    }
  }
}

// Check if DOM is already loaded
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initialize);
} else {
  // DOM is already loaded
  initialize();
}
// ФУНКЦИИ ЗА НАЈАВА НА ЛЕКАРИ
// Функција за отворање на модален прозорец за најава на лекари
// Според PDF: "За прикачување на мрежата секој вработен ќе треба да го внесе својот ID идентификатор и соодветна лозинка"
function openLekarLoginModal() {
  const modal = document.getElementById('lekar-login-modal');
  if (modal) {
    modal.style.display = 'block';
  }
}

function closeLekarLoginModal() {
  const modal = document.getElementById('lekar-login-modal');
  if (modal) {
    modal.style.display = 'none';
    const form = document.getElementById('lekar-login-form');
    const errorMessage = document.getElementById('login-error-message');
    const submitBtn = document.getElementById('login-submit-btn');
    const btnText = submitBtn?.querySelector('.btn-text');
    const btnLoading = submitBtn?.querySelector('.btn-loading');
    
    if (form) {
      form.reset();
    }
    
    // Ресетирај error message и loading state
    if (errorMessage) {
      errorMessage.style.display = 'none';
      errorMessage.textContent = '';
    }
    
    if (submitBtn && btnText && btnLoading) {
      submitBtn.disabled = false;
      btnText.style.display = 'inline-block';
      btnLoading.style.display = 'none';
    }
  }
}

// Функции за управување со главниот интерфејс за лекари (dashboard)
function openLekarDashboardModal() {
  const modal = document.getElementById('lekar-dashboard-modal');
  if (modal) {
    modal.style.display = 'block';
  }
}

function closeLekarDashboardModal() {
  const modal = document.getElementById('lekar-dashboard-modal');
  if (modal) {
    modal.style.display = 'none';
  }
}

// Подразуеваната привремена лозинка – не смее да се користи како нова (исто како на backend)
var DEFAULT_LOZINKA_LEKARI = 'Test123..';

// Прикажи/скриј лозинка додека се пишува (како на другите сајтови)
function togglePasswordVisibility(inputId, btn) {
  var input = document.getElementById(inputId);
  if (!input) return;
  if (input.type === 'password') {
    input.type = 'text';
    if (btn) btn.setAttribute('title', 'Скриј лозинка');
  } else {
    input.type = 'password';
    if (btn) btn.setAttribute('title', 'Прикажи лозинка');
  }
}
window.togglePasswordVisibility = togglePasswordVisibility;

// Глобална функција за копче „Во ред“ – скриј порака, прикажи форма за промена на лозинка (повикана и од onclick во HTML)
function showLekarFirstLoginFormStep() {
  var msgStep = document.getElementById('lekar-first-login-message-step');
  var formStep = document.getElementById('lekar-first-login-form-step');
  if (msgStep) msgStep.style.display = 'none';
  if (formStep) formStep.style.display = 'block';
}
window.showLekarFirstLoginFormStep = showLekarFirstLoginFormStep;

// Глобална обработка на прва најава – смена лозинка (повикана од onsubmit на формата за сигурно работење)
async function handlePrvaNajavaSubmit(e) {
  if (e) { e.preventDefault(); e.stopPropagation(); }
  var errEl = document.getElementById('prva-najava-lozinka-poraka');
  var tekovnaEl = document.getElementById('prva-najava-tekovna');
  var novaEl = document.getElementById('prva-najava-nova');
  var potvrdiEl = document.getElementById('prva-najava-potvrdi');
  var tekovna = tekovnaEl ? tekovnaEl.value.trim() : '';
  var nova = novaEl ? novaEl.value.trim() : '';
  var potvrdi = potvrdiEl ? potvrdiEl.value.trim() : '';
  if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
  if (nova !== potvrdi) {
    if (errEl) { errEl.textContent = 'Лозинките не се совпаѓаат.'; errEl.style.display = 'block'; } else { alert('Лозинките не се совпаѓаат.'); }
    return false;
  }
  if (nova === DEFAULT_LOZINKA_LEKARI) {
    var msg = 'Лозинката не смее да биде привремената/подразуеваната лозинка. Изберете друга лозинка според правилата (мин. 8 знаци, голема буква, број, интерпункциски знак).';
    if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; } else { alert(msg); }
    return false;
  }
  if (!currentLekar || !currentLekar.doctor_ID) {
    if (errEl) { errEl.textContent = 'Немате најавен лекар.'; errEl.style.display = 'block'; } else { alert('Немате најавен лекар.'); }
    return false;
  }
  try {
    var res = await fetch(API_BASE + '/lekari/promeni-lozinka', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        doctor_id: parseInt(currentLekar.doctor_ID, 10),
        trenutna_lozinka: tekovna,
        nova_lozinka: nova
      })
    });
    var data = await res.json().catch(function() { return {}; });
    var detail = data.detail;
    if (Array.isArray(detail) && detail.length) detail = detail[0].msg || detail[0];
    if (typeof detail !== 'string') detail = data.message || 'Грешка при смена на лозинка.';
    if (res.ok) {
      var overlay = document.getElementById('lekar-first-login-overlay');
      if (overlay) overlay.style.display = 'none';
      var prvaForm = document.getElementById('lekar-prva-najava-lozinka-form');
      if (prvaForm) prvaForm.reset();
      if (errEl) errEl.style.display = 'none';
      var imePrezime = (currentLekar && (currentLekar.name || currentLekar.surname))
        ? 'Добредојде, Др. ' + (currentLekar.name || '') + ' ' + (currentLekar.surname || '') + '!'
        : 'Добредојде!';
      alert(imePrezime + ' Лозинката е успешно променета. Сега можете да правите преглед на пациенти.');
      document.querySelectorAll('.lekar-tab-content').forEach(function(t) { t.classList.remove('active'); });
      document.querySelectorAll('.nav-tab').forEach(function(b) { b.classList.remove('active'); });
      var tabPacienti = document.getElementById('tab-pacienti');
      if (tabPacienti) tabPacienti.classList.add('active');
      var navPacienti = document.querySelector('.lekar-nav-tabs .nav-tab');
      if (navPacienti) navPacienti.classList.add('active');
      var datumInput = document.getElementById('raspored-datum-select');
      if (datumInput) {
        var today = new Date();
        datumInput.value = today.toISOString().split('T')[0];
      }
      if (typeof loadMojRaspored === 'function') loadMojRaspored();
    } else {
      if (errEl) { errEl.textContent = detail; errEl.style.display = 'block'; } else { alert(detail); }
    }
  } catch (err) {
    var msg = 'Серверот не е достапен. Обидете се повторно.';
    if (errEl) { errEl.textContent = msg; errEl.style.display = 'block'; } else { alert(msg); }
  }
  return false;
}
window.handlePrvaNajavaSubmit = handlePrvaNajavaSubmit;

function setupLekarPasswordForms() {
  // Дополнително прикачување на listener за „Во ред“ (ако onclick не се изврши)
  var okBtn = document.getElementById('lekar-first-login-ok-btn');
  if (okBtn && !okBtn.getAttribute('onclick')) {
    okBtn.addEventListener('click', showLekarFirstLoginFormStep);
  }

  // Форма за прва најава се обработува со handlePrvaNajavaSubmit() преку onsubmit во HTML

  // Форма за смена на лозинка во Поставки
  var promeniForm = document.getElementById('lekar-promeni-lozinka-form');
  if (promeniForm) {
    promeniForm.addEventListener('submit', async function(e) {
      e.preventDefault();
      var errEl = document.getElementById('promeni-lozinka-poraka');
      var tekovna = document.getElementById('lozinka-tekovna').value.trim();
      var nova = document.getElementById('lozinka-nova').value.trim();
      var potvrdi = document.getElementById('lozinka-nova-potvrdi').value.trim();
      if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
      if (nova !== potvrdi) {
        if (errEl) { errEl.textContent = 'Лозинките не се совпаѓаат.'; errEl.style.display = 'block'; }
        return;
      }
      if (nova === DEFAULT_LOZINKA_LEKARI) {
        if (errEl) { errEl.textContent = 'Лозинката не смее да биде привремената/подразуеваната лозинка. Изберете друга лозинка според правилата (мин. 8 знаци, голема буква, број, интерпункциски знак).'; errEl.style.display = 'block'; }
        return;
      }
      if (!currentLekar || !currentLekar.doctor_ID) {
        if (errEl) { errEl.textContent = 'Немате најавен лекар.'; errEl.style.display = 'block'; }
        return;
      }
      try {
        var res = await fetch(API_BASE + '/lekari/promeni-lozinka', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ doctor_id: currentLekar.doctor_ID, trenutna_lozinka: tekovna, nova_lozinka: nova })
        });
        var data = await res.json().catch(function() { return {}; });
        if (res.ok) {
          promeniForm.reset();
          if (errEl) { errEl.style.display = 'none'; }
          alert('Лозинката е успешно променета.');
        } else {
          if (errEl) { errEl.textContent = (data.detail || data.message || 'Грешка при смена на лозинка.'); errEl.style.display = 'block'; }
        }
      } catch (err) {
        if (errEl) { errEl.textContent = 'Серверот не е достапен. Обидете се повторно.'; errEl.style.display = 'block'; }
      }
    });
  }
}

// Функција за прикажување на различни табови во интерфејсот за лекари
// Функција за прикажување на различни табови во dashboard-от за лекари
// Параметри: tabName - име на табот ('pacienti', 'dezurstva', 'aparati', 'admin')
// Прикажува избраниот таб и вчитува соодветни податоци
function showLekarTab(tabName) {
  // Сокриј сите табови
  document.querySelectorAll('.lekar-tab-content').forEach(tab => {
    tab.classList.remove('active');
  });
  
  // Отстрани active класа од сите таб копчиња
  document.querySelectorAll('.nav-tab').forEach(btn => {
    btn.classList.remove('active');
  });
  
  // Прикажи избраниот таб
  const selectedTab = document.getElementById(`tab-${tabName}`);
  if (selectedTab) {
    selectedTab.classList.add('active');
  }
  
  // Додади active класа на избраното копче
  event.target.classList.add('active');
  
  // Ако е табот за пациенти, вчитај го распоредот за денешниот датум
  if (tabName === 'pacienti') {
    if (currentLekar && currentLekar.doctor_ID) {
      const datumInput = document.getElementById('raspored-datum-select');
      if (datumInput) {
        const today = new Date();
        const todayStr = today.toISOString().split('T')[0];
        datumInput.value = todayStr;
        loadMojRaspored();
      }
    }
  }
  
  // Ако е табот за дежурства, вчитај ги податоците за дежурства
  if (tabName === 'dezurstva') {
    loadDezurstva();
  }
  
  // Ако е табот за апарати, вчитај ги лекарите и апаратите за select и иницијализирај календар
  if (tabName === 'aparati') {
    loadLekariForAparati();
    loadAparati();
    
    // Додади event listener за промена на апарат (за филтрирање на лекари)
    const aparatSelect = document.getElementById('aparati-aparat-select');
    if (aparatSelect) {
      aparatSelect.addEventListener('change', function() {
        filterLekariByAparat(this.value);
      });
    }
    
    // Иницијализирај календар за апарати
    renderAparatiCalendar();
  }
  
  // Ако е табот за администрација, вчитај ги податоците за дежурства и огласи
  // Овој таб е достапен само за директорот (Владко Захариев)
  if (tabName === 'admin') {
    loadAdminDezurstva();
    loadAdminOglasi();
    loadDoctorsForAdmin();
  }
}

// Функција за прикажување на главниот dashboard за лекари
// Параметри: data - податоци за лекарот и неговите термини од API-то
// Прикажува информации за лекарот, неговите термини и проверува дали е администратор
function displayLekarDashboard(data) {
  const doctorInfo = document.getElementById('lekar-info');
  const terminiList = document.getElementById('lekar-termini-list');
  const firstLoginOverlay = document.getElementById('lekar-first-login-overlay');

  // При прва најава со привремена лозинка – прикажи overlay за задолжителна смена (прво порака, по „Во ред“ форма)
  if (firstLoginOverlay) {
    if (data.must_change_password) {
      firstLoginOverlay.style.display = 'flex';
      var msgStep = document.getElementById('lekar-first-login-message-step');
      var formStep = document.getElementById('lekar-first-login-form-step');
      if (msgStep) msgStep.style.display = 'block';
      if (formStep) formStep.style.display = 'none';
    } else {
      firstLoginOverlay.style.display = 'none';
    }
  }

  if (doctorInfo) {
    doctorInfo.innerHTML = `
      <h3>${data.doctor.name} ${data.doctor.surname}</h3>
      <p><strong>Специјалност:</strong> ${data.doctor.specijalnost || 'Н/П'}</p>
      <p><strong>Е-пошта:</strong> ${data.doctor.email || 'Нема е-пошта'}</p>
    `;
  }

  // Проверка дали најавениот лекар е директорот (Владко Захариев)
  // Точниот формат во базата е "Владко Захариев"
  // Само директорот може да види административниот таб
  const doctorName = `${data.doctor.name} ${data.doctor.surname}`.trim();
  const adminNames = [
    "Владко Захариев",  // Точниот формат во базата
    "Влатко Захариев",  // Варијација со "Влатко"
    "Владко Захаријев", // Варијација со "Захаријев"
    "Влатко Захаријев"  // Комбинација на двете варијации
  ];
  const isAdmin = adminNames.includes(doctorName);
  
  // Прикажи/скриј административниот таб според дали е директор
  const adminTabBtn = document.getElementById('admin-tab-btn');
  if (adminTabBtn) {
    adminTabBtn.style.display = isAdmin ? 'inline-block' : 'none';
  }

  // Прикажи ги термините на лекарот
  displayLekarTermini(data);
  
  // Автоматски вчитувај го распоредот за денешниот датум
  if (document.getElementById('raspored-datum-select')) {
    const today = new Date();
    const todayStr = today.toISOString().split('T')[0];
    document.getElementById('raspored-datum-select').value = todayStr;
    loadMojRaspored();
  }
}

// Функција за вчитување на распоред на дежурства
async function loadDezurstva() {
  const dezurstvaList = document.getElementById('dezurstva-list');
  if (!dezurstvaList) return;
  
  dezurstvaList.innerHTML = '<div class="loading">Вчитувам распоред на дежурства...</div>';
  
  try {
    // Ова ќе биде имплементирано во backend
    // За сега прикажуваме пример
    const res = await fetch(`${API_BASE}/lekari/${currentLekar.doctor_ID}/dezurstva`);
    
    if (res.ok) {
      const dezurstva = await res.json();
      renderDezurstva(dezurstva);
    } else {
      // Ако endpoint-от не постои, прикажи пример
      dezurstvaList.innerHTML = `
        <div class="dezurstva-info">
          <p>Распоредот на дежурства ќе биде прикажан тука.</p>
          <p><em>Забелешка: Оваа функционалност треба да се имплементира во backend.</em></p>
        </div>
      `;
    }
  } catch (err) {
    dezurstvaList.innerHTML = `
      <div class="dezurstva-info">
        <p>Распоредот на дежурства ќе биде прикажан тука.</p>
        <p><em>Забелешка: Оваа функционалност треба да се имплементира во backend.</em></p>
      </div>
    `;
  }
}

// Функција за рендерирање на дежурства
function renderDezurstva(dezurstva) {
  const dezurstvaList = document.getElementById('dezurstva-list');
  if (!dezurstvaList) return;
  
  if (!dezurstva || dezurstva.length === 0) {
    dezurstvaList.innerHTML = '<div class="loading">Нема закажани дежурства за овој месец.</div>';
    return;
  }
  
  // Групирај по оддел за подобро прикажување
  const groupedByOddel = {};
  dezurstva.forEach(d => {
    const oddel = d.oddel || 'Н/П';
    if (!groupedByOddel[oddel]) {
      groupedByOddel[oddel] = [];
    }
    groupedByOddel[oddel].push(d);
  });
  
  let html = '<div class="dezurstva-container">';
  
  Object.keys(groupedByOddel).forEach(oddel => {
    html += `<div class="dezurstva-section">`;
    html += `<h3>${oddel}</h3>`;
    html += '<div class="dezurstva-grid">';
    
    groupedByOddel[oddel].forEach(d => {
      const datumObj = new Date(d.datum);
      const datumStr = datumObj.toLocaleDateString('mk-MK', { 
        day: '2-digit', 
        month: '2-digit', 
        year: 'numeric' 
      });
      
      html += `
        <div class="dezurstvo-card">
          <h4>${d.den || datumStr}</h4>
          <p><strong>Датум:</strong> ${datumStr}</p>
          <p><strong>Време:</strong> ${d.vreme_od || '08:00'} - ${d.vreme_do || '20:00'}</p>
          ${d.napomena ? `<p><em>${d.napomena}</em></p>` : ''}
        </div>
      `;
    });
    
    html += '</div></div>';
  });
  
  html += '</div>';
  dezurstvaList.innerHTML = html;
}

// Мапирање помеѓу апарати (по код и име) и специјалности
// ВАЖНО: Користи точни имиња на специјалности како што се во базата
// Може да биде string (една специјалност) или array (повеќе специјалности)
const aparatToSpecialtyMap = {
  // По код
  'dermoskop': 'Дерматовенерологија',  // Во базата е "Дерматовенерологија", не "Дерматологија"
  'rentgen': 'Радиологија',
  'kt': 'Радиологија',
  'mri': 'Радиологија',
  'ehokardiografija': 'Кардиологија',
  'dopler_ekstremiteti': ['Радиологија', 'Кардиологија'],  // Доплер бара и радиолози и кардиолози
  'perimetar': 'Офтамологија',  // Во базата е "Офтамологија" (без "л")
  'oct_zaden_segment': 'Офтамологија',  // Во базата е "Офтамологија" (без "л")
  'eho_ugs_prostata': 'Урологија',
  'gastroskopija': 'Гастроерохепатологија',  // Во базата е "Гастроерохепатологија"
  'kolonoskopija': 'Гастроерохепатологија',  // Во базата е "Гастроерохепатологија"
  'denzitometrija': ['Ревматологија', 'Радиологија'],  // Дензитометрија бара и ревматолози и радиолози
  'eho_tomografija': 'Радиологија',
  'ultrazvuk': 'Радиологија',
  // По име (за совместимост)
  'Дермоскоп': 'Дерматовенерологија',
  'Рентгенографија': 'Радиологија',
  'Компјутерска томографија': 'Радиологија',
  'Магнетна резонанца': 'Радиологија',
  'Ехокардиографија': 'Кардиологија',
  'Доплер на артериски или венски крвни садови на екстремитети': ['Радиологија', 'Кардиологија'],  // Доплер бара и радиолози и кардиолози
  'Периметар': 'Офтамологија',  // Во базата е "Офтамологија" (без "л")
  'Оптичка кохерентна томографија заден сегмент (ОЦТ)': 'Офтамологија',  // Во базата е "Офтамологија" (без "л")
  'ЕХО на УГС и простата': 'Урологија',
  'Гастроскопија': 'Гастроерохепатологија',
  'Колоноскопија': 'Гастроерохепатологија',
  'Дензитометрија': ['Ревматологија', 'Радиологија'],  // Дензитометрија бара и ревматолози и радиолози
  'Ехо томографија': 'Радиологија'
};

// Зачувај ги сите лекари за филтрирање
let allLekariForAparati = [];

// Функција за вчитување на лекари за select во формата за апарати
async function loadLekariForAparati() {
  const lekarSelect = document.getElementById('aparati-lekar-select');
  if (!lekarSelect) return;
  
  try {
    const res = await fetch(API_BASE + '/lekari');
    if (res.ok) {
      allLekariForAparati = await res.json();
      // Не ги пополнуваме директно, ќе се пополнат кога се избере апарат
    }
  } catch (err) {
    console.error('Грешка при вчитување на лекари:', err);
  }
}

// Функција за филтрирање на лекари според избраниот апарат
function filterLekariByAparat(aparatKod) {
  const lekarSelect = document.getElementById('aparati-lekar-select');
  const aparatSelect = document.getElementById('aparati-aparat-select');
  if (!lekarSelect || !aparatSelect) return;
  
  // Исчисти ги постоечките опции
  while (lekarSelect.options.length > 0) {
    lekarSelect.remove(0);
  }
  
  if (!aparatKod) {
    // Ако не е избран апарат, прикажи placeholder
    const placeholderOption = document.createElement('option');
    placeholderOption.value = '';
    placeholderOption.textContent = 'Прво изберете апарат...';
    placeholderOption.disabled = true;
    placeholderOption.selected = true;
    lekarSelect.appendChild(placeholderOption);
    lekarSelect.disabled = true;
    return;
  }
  
  // Најди го името на апаратот од select-от
  const selectedOption = aparatSelect.options[aparatSelect.selectedIndex];
  const aparatIme = selectedOption ? selectedOption.textContent : '';
  
  // Пробај да најдеш специјалност по код, па по име
  // Може да биде string (една специјалност) или array (повеќе специјалности)
  let specialtyOrArray = aparatToSpecialtyMap[aparatKod] || aparatToSpecialtyMap[aparatIme];
  
  // Конвертирај во array за еднообразна обработка
  const specialties = specialtyOrArray 
    ? (Array.isArray(specialtyOrArray) ? specialtyOrArray : [specialtyOrArray])
    : null;
  
  if (!specialties || specialties.length === 0) {
    // Ако нема мапирање, прикажи сите лекари
    const placeholderOption = document.createElement('option');
    placeholderOption.value = '';
    placeholderOption.textContent = 'Изберете лекар...';
    lekarSelect.appendChild(placeholderOption);
    
    allLekariForAparati.forEach(lekar => {
      const option = document.createElement('option');
      option.value = lekar.doctor_ID;
      option.textContent = `${lekar.name} ${lekar.surname} - ${lekar.specijalnost || 'Н/П'}`;
      lekarSelect.appendChild(option);
    });
    lekarSelect.disabled = false;
    return;
  }
  
  // Филтрирај ги лекарите според специјалностите (може да биде една или повеќе)
  // Користи case-insensitive и trim за подобра совместимост
  const filteredLekari = allLekariForAparati.filter(lekar => {
    if (!lekar.specijalnost) return false;
    const lekarSpecialty = lekar.specijalnost.trim();
    return specialties.includes(lekarSpecialty);
  });
  
  // Додади placeholder
  const placeholderOption = document.createElement('option');
  placeholderOption.value = '';
  const specialtyLabel = specialties.length === 1 
    ? specialties[0] 
    : specialties.join(' или ');
  placeholderOption.textContent = filteredLekari.length > 0 
    ? `Изберете ${specialtyLabel} лекар...` 
    : `Нема лекари од ${specialtyLabel}`;
  placeholderOption.disabled = true;
  if (filteredLekari.length === 0) {
    placeholderOption.selected = true;
  }
  lekarSelect.appendChild(placeholderOption);
  
  // Додади ги филтрираните лекари
  filteredLekari.forEach(lekar => {
    const option = document.createElement('option');
    option.value = lekar.doctor_ID;
    option.textContent = `${lekar.name} ${lekar.surname} - ${lekar.specijalnost || 'Н/П'}`;
    lekarSelect.appendChild(option);
  });
  
  lekarSelect.disabled = filteredLekari.length === 0;
}

// Функција за вчитување на апарати од API и пополнување на select-от
async function loadAparati() {
  const aparatSelect = document.getElementById('aparati-aparat-select');
  if (!aparatSelect) return;
  
  try {
    const res = await fetch(API_BASE + '/aparati');
    if (res.ok) {
      const aparati = await res.json();
      
      // Исчисти ги постоечките опции (освен првата "Изберете апарат...")
      while (aparatSelect.options.length > 1) {
        aparatSelect.remove(1);
      }
      
      // Ако има апарати од базата, додај ги
      if (Array.isArray(aparati) && aparati.length > 0) {
        aparati.forEach(aparat => {
          const option = document.createElement('option');
          // Користи 'kod' ако постои, инаку 'aparat_id', инаку 'ime' како value
          option.value = aparat.kod || aparat.aparat_id || aparat.ime;
          option.textContent = aparat.ime || aparat.opis || option.value;
          aparatSelect.appendChild(option);
        });
      }
      // Ако нема апарати од базата, остануваат хардкодираните опции
    } else {
      // Ако API-то врати грешка, остануваат хардкодираните опции
    }
  } catch (err) {
    // При грешка, остануваат хардкодираните опции
  }
  
  // Ресетирај го select-от за лекари при вчитување
  filterLekariByAparat('');
}

// Функција за обработка на формата за закажување термин на апарат
// Глобални променливи за календар на апарати
let aparatiSelectedDate = null;
let aparatiSelectedTime = null;

// Функција за рендерирање на календар за апарати
function renderAparatiCalendar() {
  const calendar = document.getElementById('aparati-calendar');
  if (!calendar) return;

  const today = new Date();
  const currentMonth = today.getMonth();
  const currentYear = today.getFullYear();

  let displayMonth = currentMonth;
  let displayYear = currentYear;

  function updateCalendar() {
    calendar.innerHTML = '';

    const nav = document.createElement('div');
    nav.className = 'calendar-nav';
    nav.innerHTML = `
      <button onclick="aparatiPrevMonth()">← Претходен</button>
      <span>${getMonthName(displayMonth)} ${displayYear}</span>
      <button onclick="aparatiNextMonth()">Следен →</button>
    `;
    calendar.appendChild(nav);

    const monthGrid = document.createElement('div');
    monthGrid.className = 'calendar-month';

    const dayNames = ['Пон', 'Вто', 'Сре', 'Чет', 'Пет', 'Саб', 'Нед'];
    dayNames.forEach(day => {
      const header = document.createElement('div');
      header.className = 'calendar-header';
      header.textContent = day;
      monthGrid.appendChild(header);
    });

    const firstDay = new Date(displayYear, displayMonth, 1);
    const lastDay = new Date(displayYear, displayMonth + 1, 0);
    const daysInMonth = lastDay.getDate();
    const startingDayOfWeek = firstDay.getDay();
    const adjustedStart = startingDayOfWeek === 0 ? 6 : startingDayOfWeek - 1;

    for (let i = 0; i < adjustedStart; i++) {
      const empty = document.createElement('div');
      monthGrid.appendChild(empty);
    }

    for (let day = 1; day <= daysInMonth; day++) {
      const dayCell = document.createElement('div');
      dayCell.className = 'calendar-day';
      dayCell.textContent = day;

      const cellDate = new Date(displayYear, displayMonth, day);
      const isPast = cellDate < new Date(today.getFullYear(), today.getMonth(), today.getDate());
      const isToday = cellDate.toDateString() === today.toDateString();
      const isWeekend = cellDate.getDay() === 0 || cellDate.getDay() === 6;

      if (isPast || isWeekend) {
        dayCell.classList.add('past', 'disabled');
        if (isWeekend) {
          dayCell.title = 'Не се закажуваат термини во сабота и недела';
        }
      } else {
        dayCell.addEventListener('click', function () {
          aparatiSelectDate(cellDate, this);
        });
        if (isToday) {
          dayCell.style.fontWeight = 'bold';
        }
      }

      monthGrid.appendChild(dayCell);
    }

    calendar.appendChild(monthGrid);
  }

  window.aparatiPrevMonth = function () {
    displayMonth--;
    if (displayMonth < 0) {
      displayMonth = 11;
      displayYear--;
    }
    updateCalendar();
  };

  window.aparatiNextMonth = function () {
    displayMonth++;
    if (displayMonth > 11) {
      displayMonth = 0;
      displayYear++;
    }
    updateCalendar();
  };

  updateCalendar();
}

function aparatiSelectDate(date, element) {
  const dayOfWeek = date.getDay();
  if (dayOfWeek === 0 || dayOfWeek === 6) {
    alert('Не се закажуваат термини во сабота и недела. Изберете друг датум.');
    return;
  }

  aparatiSelectedDate = date;
  aparatiSelectedTime = null;

  document.querySelectorAll('#aparati-calendar .calendar-day').forEach(day => {
    day.classList.remove('selected');
  });

  if (element) {
    element.classList.add('selected');
  }

  const dateInput = document.getElementById('aparati-datum-input');
  if (dateInput) {
    dateInput.value = date.toISOString().split('T')[0];
  }

  renderAparatiTimeSlots();
}

async function renderAparatiTimeSlots() {
  const timeSlotsContainer = document.getElementById('aparati-time-slots');
  const lekarSelect = document.getElementById('aparati-lekar-select');
  
  if (!timeSlotsContainer || !aparatiSelectedDate || !lekarSelect || !lekarSelect.value) {
    if (timeSlotsContainer) {
      timeSlotsContainer.innerHTML = '';
    }
    return;
  }

  const slots = [];
  for (let hour = 9; hour < 17; hour++) {
    slots.push(`${hour.toString().padStart(2, '0')}:00`);
    slots.push(`${hour.toString().padStart(2, '0')}:30`);
  }

  timeSlotsContainer.innerHTML = '<div class="loading">Вчитувам достапни термини...</div>';

  try {
    const datumStr = aparatiSelectedDate.toISOString().split('T')[0];
    const lekarId = lekarSelect.value;
    const res = await fetch(`${API_BASE}/termini/dostapni?lekar_id=${lekarId}&datum=${datumStr}`);
    
    if (!res.ok) {
      throw new Error(`HTTP грешка! Статус: ${res.status}`);
    }

    const zafateniTermini = await res.json();
    const zafateniSet = new Set(zafateniTermini.map(t => t.length === 5 ? t : t.substring(0, 5)));

    timeSlotsContainer.innerHTML = '';

    slots.forEach(slot => {
      const slotDiv = document.createElement('div');
      slotDiv.className = 'time-slot';
      slotDiv.textContent = slot;

      const isAvailable = !zafateniSet.has(slot);

      if (isAvailable) {
        slotDiv.addEventListener('click', () => aparatiSelectTime(slot, slotDiv));
      } else {
        slotDiv.classList.add('disabled');
      }

      timeSlotsContainer.appendChild(slotDiv);
    });
  } catch (err) {
    timeSlotsContainer.innerHTML = '<div class="loading" style="color: red;">Грешка при вчитување на термини.</div>';
  }
}

function aparatiSelectTime(time, element) {
  aparatiSelectedTime = time;

  document.querySelectorAll('#aparati-time-slots .time-slot').forEach(slot => {
    slot.classList.remove('selected');
  });

  element.classList.add('selected');

  const timeInput = document.getElementById('aparati-vreme-input');
  if (timeInput) {
    timeInput.value = time;
  }
  
  // Провери достапност кога се избере време
  checkAparatiDostapnost();
}

function setupAparatiForm() {
  const form = document.getElementById('aparati-booking-form');
  if (!form) return;
  
  const aparatSelect = document.getElementById('aparati-aparat-select');
  const dostapnostMessage = document.createElement('div');
  dostapnostMessage.id = 'aparati-dostapnost-message';
  dostapnostMessage.style.marginTop = '0.5rem';
  dostapnostMessage.style.padding = '0.5rem';
  dostapnostMessage.style.borderRadius = '4px';
  dostapnostMessage.style.display = 'none';
  
  const timeSlotsContainer = document.getElementById('aparati-time-slots');
  if (timeSlotsContainer && !document.getElementById('aparati-dostapnost-message')) {
    timeSlotsContainer.parentElement.appendChild(dostapnostMessage);
  }
  
  async function checkAparatiDostapnost() {
    const aparat = aparatSelect.value;
    const datumInput = document.getElementById('aparati-datum-input');
    const vremeInput = document.getElementById('aparati-vreme-input');
    const lekarId = document.getElementById('aparati-lekar-select').value;
    const pacientInput = document.getElementById('aparati-pacient-input');
    const pacientFullName = pacientInput?.value.trim() || '';
    
    // Парсирај име и презиме од едното поле
    const parts = pacientFullName.split(/\s+/).filter(p => p.length > 0);
    const pacientIme = parts.length > 0 ? parts[0] : '';
    const pacientPrezime = parts.length > 1 ? parts.slice(1).join(' ') : '';
    
    if (!aparat || !datumInput?.value || !vremeInput?.value) {
      dostapnostMessage.style.display = 'none';
      return;
    }
    
    try {
      const datum = datumInput.value;
      const vreme = vremeInput.value;
      const aparatKod = aparatSelect.value; // Кодот на апаратот
      const aparatIme = aparatSelect.options[aparatSelect.selectedIndex]?.textContent || aparatKod;
      
      // Користи го кодот на апаратот за проверка на достапност
      let url = `${API_BASE}/aparati/termini/dostapnost?aparat=${encodeURIComponent(aparatKod)}&datum=${datum}&vreme=${vreme}`;
      
      if (lekarId) {
        url += `&lekar_id=${lekarId}`;
      }
      
      // Додади име и презиме на пациентот за проверка дали има закажан преглед
      if (pacientIme && pacientPrezime) {
        url += `&pacient_ime=${encodeURIComponent(pacientIme)}&pacient_prezime=${encodeURIComponent(pacientPrezime)}`;
      }
      
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        dostapnostMessage.textContent = data.poraka;
        dostapnostMessage.style.display = 'block';
        if (data.dostapen) {
          dostapnostMessage.style.backgroundColor = '#d4edda';
          dostapnostMessage.style.color = '#155724';
          dostapnostMessage.style.border = '1px solid #c3e6cb';
        } else {
          dostapnostMessage.style.backgroundColor = '#f8d7da';
          dostapnostMessage.style.color = '#721c24';
          dostapnostMessage.style.border = '1px solid #f5c6cb';
        }
      }
    } catch (err) {
      dostapnostMessage.style.display = 'none';
    }
  }
  
  // Експонирај checkAparatiDostapnost глобално за да може да се повика од други функции
  window.checkAparatiDostapnost = checkAparatiDostapnost;
  
  if (aparatSelect) {
    aparatSelect.addEventListener('change', checkAparatiDostapnost);
  }
  
  const lekarSelect = document.getElementById('aparati-lekar-select');
  const pacientInput = document.getElementById('aparati-pacient-input');
  
  if (lekarSelect) {
    lekarSelect.addEventListener('change', function() {
      if (aparatiSelectedDate) {
        renderAparatiTimeSlots();
      }
      checkAparatiDostapnost();
    });
  }
  
  // Додади event listener за име и презиме на пациентот за проверка на достапност
  if (pacientInput) {
    pacientInput.addEventListener('input', checkAparatiDostapnost);
  }
  
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const lekarId = document.getElementById('aparati-lekar-select').value;
    const pacientInput = document.getElementById('aparati-pacient-input');
    const pacientFullName = pacientInput?.value.trim() || '';
    const aparat = document.getElementById('aparati-aparat-select').value;
    const datumInput = document.getElementById('aparati-datum-input');
    const vremeInput = document.getElementById('aparati-vreme-input');
    const opis = document.getElementById('aparati-opis-input').value.trim();
    
    // Парсирај име и презиме од едното поле
    const parts = pacientFullName.split(/\s+/).filter(p => p.length > 0);
    const pacientIme = parts.length > 0 ? parts[0] : '';
    const pacientPrezime = parts.length > 1 ? parts.slice(1).join(' ') : '';
    
    if (!lekarId || !pacientFullName || !aparat || !datumInput?.value || !vremeInput?.value || !opis) {
      alert('Ве молиме пополнете ги сите полиња и изберете датум и време.');
      return;
    }
    
    if (!pacientIme || !pacientPrezime) {
      alert('Ве молиме внесете го целото име и презиме на пациентот (на пр. "Име Презиме").');
      return;
    }
    
    const datum = datumInput.value;
    const vreme = vremeInput.value;
    const datumVreme = `${datum}T${vreme}`;
    
    // Проверка на достапност пред закажување
    try {
      // Користи го кодот на апаратот наместо целото име за да се избегне проблем со должина
      const aparatSelect = document.getElementById('aparati-aparat-select');
      const aparatKod = aparatSelect.value; // Кодот на апаратот
      const aparatIme = aparatSelect.options[aparatSelect.selectedIndex]?.textContent || aparatKod;
      
      let checkUrl = `${API_BASE}/aparati/termini/dostapnost?aparat=${encodeURIComponent(aparatKod)}&datum=${datum}&vreme=${vreme}`;
      checkUrl += `&lekar_id=${lekarId}`;
      checkUrl += `&pacient_ime=${encodeURIComponent(pacientIme)}&pacient_prezime=${encodeURIComponent(pacientPrezime)}`;
      
      const checkRes = await fetch(checkUrl);
      if (checkRes.ok) {
        const checkData = await checkRes.json();
        if (!checkData.dostapen) {
          alert(checkData.poraka + ' Ве молиме изберете друг термин.');
          return;
        }
      }
    } catch (err) {
      console.error('Грешка при проверка на достапност:', err);
    }
    
    try {
      // Користи го кодот на апаратот наместо целото име
      const aparatSelect = document.getElementById('aparati-aparat-select');
      const aparatKod = aparatSelect.value;
      const aparatIme = aparatSelect.options[aparatSelect.selectedIndex]?.textContent || aparatKod;
      
      const res = await fetch(API_BASE + '/aparati/termini', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          lekar_id: parseInt(lekarId),
          lekar_ime: (allLekariForAparati.find(d => d.doctor_ID == lekarId)?.name || '') + ' ' + (allLekariForAparati.find(d => d.doctor_ID == lekarId)?.surname || ''),
          pacient_ime: pacientIme,
          pacient_prezime: pacientPrezime,
          aparat: aparatKod, // Користи код наместо цело име
          aparat_ime: aparatIme, // Додади и име за приказ ако е потребно
          datum_vreme: datumVreme,
          opis: opis
        })
      });
      
      if (res.ok) {
        alert('Терминот за апарат е успешно закажан!');
        form.reset();
        // Ресетирај го select-от за лекари
        filterLekariByAparat('');
        aparatiSelectedDate = null;
        aparatiSelectedTime = null;
        const timeSlotsContainer = document.getElementById('aparati-time-slots');
        if (timeSlotsContainer) {
          timeSlotsContainer.innerHTML = '';
        }
        document.querySelectorAll('#aparati-calendar .calendar-day').forEach(day => {
          day.classList.remove('selected');
        });
        dostapnostMessage.style.display = 'none';
      } else {
        const error = await res.json();
        alert(error.detail || 'Грешка при закажување на термин.');
      }
    } catch (err) {
      alert('Грешка при закажување на термин. Проверете дали серверот работи.');
    }
  });
}

// Функција за најава на лекар со корисничко име (име.презиме) и лозинка
// Според новата документација: "Се најавуваа со корисничко име и лозинка"
// За лекари: корисничко име = име.презиме (напр. "ана.ивановска")
async function loginLekar() {
  const usernameInput = document.getElementById('lekar-username-input');
  const passwordInput = document.getElementById('lekar-password-input');
  const submitBtn = document.getElementById('login-submit-btn');
  const errorMessage = document.getElementById('login-error-message');
  const btnText = submitBtn.querySelector('.btn-text');
  const btnLoading = submitBtn.querySelector('.btn-loading');
  
  const username = usernameInput.value.trim().toLowerCase();
  const password = passwordInput.value;
  
  // Сокриј претходни грешки
  errorMessage.style.display = 'none';
  errorMessage.textContent = '';
  
  // Валидација: проверуваме дали се внесени и корисничко име и лозинка
  if (!username) {
    showLoginError('Внесете корисничко име');
    usernameInput.focus();
    return;
  }
  
  // Проверка на формат: треба да биде име.презиме
  if (!username.includes('.') || username.split('.').length !== 2) {
    showLoginError('Корисничкото име мора да биде во формат: име.презиме (напр. ана.ивановска)');
    usernameInput.focus();
    return;
  }
  
  if (!password) {
    showLoginError('Внесете лозинка');
    passwordInput.focus();
    return;
  }

  // Прикажи loading state
  submitBtn.disabled = true;
  btnText.style.display = 'none';
  btnLoading.style.display = 'inline-block';

  try {
    // Испраќаме POST барање со корисничко име и лозинка за автентификација
    // Backend-от ќе провери дали комбинацијата е валидна
    const res = await fetch(API_BASE + '/lekari/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        username: username,
        password: password
      })
    });
    
    if (!res.ok) {
      const error = await res.json();
      showLoginError(error.detail || 'Грешка при најава. Проверете ги вашите податоци.');
      // Ресетирај loading state
      submitBtn.disabled = false;
      btnText.style.display = 'inline-block';
      btnLoading.style.display = 'none';
      return;
    }

    // Ако автентификацијата е успешна, ги земаме податоците за лекарот и неговите термини
    const data = await res.json();
    currentLekar = data.doctor;
    try { sessionStorage.setItem('currentLekar', JSON.stringify(data.doctor)); } catch (e) {}
    
    // Прикажи персонализирана порака за најавениот лекар
    const lekarIme = `${data.doctor.name} ${data.doctor.surname}`;
    const lekarSpecijalnost = data.doctor.specijalnost || '';
    
    // Затвораме модал за најава и прикажуваме главен интерфејс за лекари (dashboard)
    closeLekarLoginModal();
    displayLekarDashboard(data);
    openLekarDashboardModal();
    
    // Прикажи персонализирана порака
    setTimeout(() => {
      alert(`Добредојде, Др. ${lekarIme}${lekarSpecijalnost ? ` (${lekarSpecijalnost})` : ''}! Успешно се најавивте.`);
    }, 300);
  } catch (err) {
    showLoginError('Грешка при најава. Проверете дали серверот работи.');
    // Ресетирај loading state
    submitBtn.disabled = false;
    btnText.style.display = 'inline-block';
    btnLoading.style.display = 'none';
  }
}

// Помошна функција за прикажување на грешки при најава
function showLoginError(message) {
  const errorMessage = document.getElementById('login-error-message');
  errorMessage.textContent = message;
  errorMessage.style.display = 'block';
  
  // Автоматски сокриј грешката после 5 секунди
  setTimeout(() => {
    errorMessage.style.display = 'none';
  }, 5000);
}

// Функција за вчитување на распоред за одреден датум користејќи го новиот endpoint
// Користи GET /lekari/moj-raspored/{lekar_id} за да го прикаже распоредот на лекарот
window.loadMojRaspored = async function loadMojRaspored() {
  if (!currentLekar || !currentLekar.doctor_ID) {
    alert('Не сте најавени како лекар.');
    return;
  }

  const datumInput = document.getElementById('raspored-datum-select');
  const terminiList = document.getElementById('lekar-termini-list');
  
  if (!terminiList) {
    return;
  }

  // Ако нема избран датум, користи денешен
  let datum = '';
  if (datumInput && datumInput.value) {
    datum = datumInput.value;
  } else {
    const today = new Date();
    datum = today.toISOString().split('T')[0];
    if (datumInput) {
      datumInput.value = datum;
    }
  }

  terminiList.innerHTML = '<div class="loading">Вчитувам распоред...</div>';

  try {
    const url = `${API_BASE}/lekari/moj-raspored/${currentLekar.doctor_ID}${datum ? `?datum=${datum}` : ''}`;
    const res = await fetch(url);

    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.detail || 'Грешка при вчитување на распоред');
    }

    const data = await res.json();
    
    if (!data.raspored || data.raspored.length === 0) {
      terminiList.innerHTML = `<div class="loading">Немате закажани термини за ${data.datum || datum}.</div>`;
      return;
    }

    terminiList.innerHTML = '';
    
    // Прикажи датумот
    const datumHeader = document.createElement('div');
    datumHeader.style.cssText = 'margin-bottom: 1.5rem; padding: 1rem; background: #f8f9fa; border-radius: 8px;';
    datumHeader.innerHTML = `<h4 style="margin: 0; color: #2c3e50;">Распоред за ${data.datum || datum}</h4>`;
    terminiList.appendChild(datumHeader);

    // Прикажи ги термините сортирани по време
    data.raspored.forEach(termin => {
      const terminDiv = document.createElement('div');
      terminDiv.className = 'termin-card';
      
      terminDiv.innerHTML = `
        <div class="termin-header">
          <h4>${termin.ime_puno || termin.ime_pacient || 'Нема име'}</h4>
          <p><strong>Време:</strong> ${termin.vreme}</p>
          <p><strong>Статус:</strong> <span style="color: ${termin.status === 'закажан' ? '#27ae60' : '#e74c3c'}">${termin.status || 'закажан'}</span></p>
        </div>
        <div class="termin-contact">
          <h5>Податоци за пациентот:</h5>
          <div class="pacient-osnovni-podatoci">
            <p><strong>Име:</strong> ${termin.ime_pacient || 'Нема'}</p>
            <p><strong>Презиме:</strong> ${termin.prezime_pacient || 'Нема'}</p>
            <p><strong>Е-пошта:</strong> ${termin.email_pacient || 'Нема'}</p>
          </div>
        </div>
      `;
      terminiList.appendChild(terminDiv);
    });
  } catch (err) {
    terminiList.innerHTML = `<div class="loading" style="color: red;">Грешка: ${err.message}</div>`;
  }
}

// Функција за прикажување на термини за најавениот лекар
// Според PDF: "Лекарот ќе има целосен пристап до медицинската слика и основните податоци за пациентот"
// Прикажува листа на термини со можност за внесување на дијагноза и терапија
function displayLekarTermini(data) {
  const doctorInfo = document.getElementById('lekar-info');
  const terminiList = document.getElementById('lekar-termini-list');

  if (doctorInfo) {
    doctorInfo.innerHTML = `
      <h3>${data.doctor.name} ${data.doctor.surname}</h3>
      <p><strong>Специјалност:</strong> ${data.doctor.specijalnost || 'Н/П'}</p>
      <p><strong>Е-пошта:</strong> ${data.doctor.email || 'Нема е-пошта'}</p>
    `;
  }

  if (terminiList) {
    if (!data.termini || data.termini.length === 0) {
      terminiList.innerHTML = '<div class="loading">Немате закажани термини.</div>';
      return;
    }

    terminiList.innerHTML = '';
    data.termini.forEach(termin => {
      const terminDiv = document.createElement('div');
      terminDiv.className = 'termin-card';
      
      // Подели го името на пациентот на име и презиме
      const imeParts = (termin.ime_pacient || '').split(' ');
      const ime = imeParts[0] || '';
      const prezime = imeParts.slice(1).join(' ') || '';
      
      terminDiv.innerHTML = `
        <div class="termin-header">
          <h4>${termin.ime_pacient || 'Нема име'}</h4>
          <p><strong>Датум:</strong> ${termin.datum_pregled}</p>
          <p><strong>Време:</strong> ${termin.vreme_pregled}</p>
        </div>
        <div class="termin-contact">
          <h5>Основни податоци за пациентот:</h5>
          <div class="pacient-osnovni-podatoci">
            <p><strong>Име:</strong> ${ime}</p>
            <p><strong>Презиме:</strong> ${prezime}</p>
            <p><strong>Е-пошта:</strong> ${termin.email_pacient || 'Нема'}</p>
            <p><strong>Телефон:</strong> ${termin.telefon_pacient || 'Нема'}</p>
          </div>
        </div>
        <div class="termin-medical">
          <h5>Медицински податоци:</h5>
          <div class="medical-field">
            <label>Дијагноза:</label>
            <textarea class="dijagnoza-input" data-termin-id="${termin.termin_ID}" placeholder="Внесете дијагноза...">${termin.dijagnoza || ''}</textarea>
          </div>
          <div class="medical-field">
            <label>Терапија:</label>
            <textarea class="terapija-input" data-termin-id="${termin.termin_ID}" placeholder="Внесете терапија...">${termin.terapija || ''}</textarea>
          </div>
          <button class="btn-save-termin" onclick="saveTerminChanges(${termin.termin_ID})">Зачувај промени</button>
        </div>
      `;
      terminiList.appendChild(terminDiv);
    });
  }
}

// Функција за зачувување на промените во дијагноза и терапија за одреден термин
// Според PDF: "Сите корекции кои се направени од страна на лекарот се запишуваат во базата"
// Оваа функција ги испраќа промените на backend за зачувување во базата на податоци
async function saveTerminChanges(terminId) {
  const dijagnozaInput = document.querySelector(`.dijagnoza-input[data-termin-id="${terminId}"]`);
  const terapijaInput = document.querySelector(`.terapija-input[data-termin-id="${terminId}"]`);

  if (!dijagnozaInput || !terapijaInput) {
    alert('Грешка при наоѓање на полињата');
    return;
  }

  const dijagnoza = dijagnozaInput.value.trim();
  const terapija = terapijaInput.value.trim();

  try {
    const res = await fetch(`${API_BASE}/termini/${terminId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ dijagnoza, terapija })
    });

    if (!res.ok) {
      const error = await res.json();
      alert(error.detail || 'Грешка при зачувување');
      return;
    }

    const result = await res.json();
    alert(result.message || 'Промените се зачувани успешно!');
  } catch (err) {
    alert('Грешка при зачувување. Проверете дали серверот работи.');
  }
}
// ФУНКЦИИ ЗА ПРИКАЗУВАЊЕ НА ПОВЕЌЕ/ПОМАЛКУ ЛЕКАРИ

// Функција за прикажување на повеќе лекари (додава 8 нови лекари во приказот)
function showMoreDoctors() {
  displayedDoctorsCount += 8; // Додади уште 8 лекари (2 реда)
  renderDoctors(filteredDoctors); // Ре-рендерирај со новиот број без ресетирање
}

function showLessDoctors() {
  displayedDoctorsCount = Math.max(8, displayedDoctorsCount - 8); // Намали за 8, но не помалку од 8
  renderDoctors(filteredDoctors); // Ре-рендерирај со новиот број без ресетирање
}

// Make functions available globally if needed
window.loadLekari = loadLekari;
window.loadKariera = loadKariera;
window.loadUslugi = loadUslugi;

function showPacientRegisterError(message) {
  const errorMessage = document.getElementById('pacient-register-error-message');
  if (errorMessage) {
    errorMessage.textContent = message;
    errorMessage.style.display = 'block';
    setTimeout(() => {
      errorMessage.style.display = 'none';
    }, 5000);
  }
}

// Функции за управување со модалите за пациенти
function openPacientLoginModal() {
  const modal = document.getElementById('pacient-login-modal');
  if (modal) {
    modal.style.display = 'block';
  }
}

function closePacientLoginModal() {
  const modal = document.getElementById('pacient-login-modal');
  if (modal) {
    modal.style.display = 'none';
    const form = document.getElementById('pacient-login-form');
    if (form) {
      form.reset();
    }
  }
}

function showPacientRegister() {
  closePacientLoginModal();
  const registerModal = document.getElementById('pacient-register-modal');
  if (registerModal) {
    registerModal.style.display = 'block';
  }
}

function showPacientLogin() {
  closePacientRegisterModal();
  openPacientLoginModal();
}

function closePacientRegisterModal() {
  const modal = document.getElementById('pacient-register-modal');
  if (modal) {
    modal.style.display = 'none';
    const form = document.getElementById('pacient-register-form');
    if (form) {
      form.reset();
    }
  }
}
window.openLekarLoginModal = openLekarLoginModal;
window.closeLekarLoginModal = closeLekarLoginModal;
window.closeLekarDashboardModal = closeLekarDashboardModal;
window.showLekarTab = showLekarTab;
window.saveTerminChanges = saveTerminChanges;
window.showMoreDoctors = showMoreDoctors;

// АДМИНИСТРАЦИЈА - УПРАВУВАЊЕ СО ДЕЖУРСТВА И ОГЛАСИ
// Овој дел содржи функции за управување со дежурства и огласи за работа.
// Пристапот е ограничен само за директорот на болницата (Владко Захариев).

// Функција за прикажување на под-табови во администрација
// Параметри: subTabName - име на под-табот ('dezurstva-admin' или 'oglasi-admin')
function showAdminSubTab(subTabName) {
  // Сокриј сите под-табови
  document.querySelectorAll('.admin-sub-tab-content').forEach(tab => {
    tab.classList.remove('active');
  });
  
  // Отстрани active класа од сите под-таб копчиња
  document.querySelectorAll('.admin-sub-tab').forEach(btn => {
    btn.classList.remove('active');
  });
  
  // Прикажи избраниот под-таб
  const selectedTab = document.getElementById(subTabName);
  if (selectedTab) {
    selectedTab.classList.add('active');
  }
  
  // Додади active класа на избраното копче
  event.target.classList.add('active');
  
  // Вчитај ги податоците според под-табот
  if (subTabName === 'dezurstva-admin') {
    loadAdminDezurstva();
  } else if (subTabName === 'oglasi-admin') {
    loadAdminOglasi();
  } else if (subTabName === 'novosti-admin') {
    loadNovostiAdmin();
  }
}

// Вчитување на дежурства за администрација
// Ги вчитува сите дежурства од базата и ги прикажува во административниот панел
// Задолжително треба да се најавен лекар (currentLekar) и да е директорот
async function loadAdminDezurstva() {
  const container = document.getElementById('dezurstva-admin-list');
  if (!container || !currentLekar) return;
  
  try {
    container.innerHTML = '<div class="loading">Вчитувам дежурства...</div>';
    
    const res = await fetch(`${API_BASE}/admin/dezurstva?admin_doctor_id=${currentLekar.doctor_ID}`);
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.detail || `HTTP грешка! Статус: ${res.status}`);
    }
    
    const dezurstva = await res.json();
    
    if (dezurstva.length === 0) {
      container.innerHTML = '<div class="loading">Нема дежурства.</div>';
      return;
    }
    
    container.innerHTML = '';
    dezurstva.forEach(d => {
      const div = document.createElement('div');
      div.className = 'admin-item';
      div.innerHTML = `
        <div class="admin-item-content">
          <h4>${d.doctor_name} - ${d.oddel}</h4>
          <p><strong>Датум:</strong> ${d.datum}</p>
          <p><strong>Време:</strong> ${d.vreme_od} - ${d.vreme_do}</p>
          ${d.napomena ? `<p><strong>Напомена:</strong> ${d.napomena}</p>` : ''}
        </div>
        <div class="admin-item-actions">
          <button class="btn-edit" onclick="editDezurstvo(${d.dezurstvo_ID})">Уреди</button>
          <button class="btn-delete" onclick="deleteDezurstvo(${d.dezurstvo_ID})">Избриши</button>
        </div>
      `;
      container.appendChild(div);
    });
  } catch (err) {
    container.innerHTML = `<div class="loading" style="color: red;">Грешка: ${err.message}</div>`;
  }
}

// Вчитување на огласи за администрација
// Ги вчитува сите огласи за работа од базата и ги прикажува во административниот панел
// Задолжително треба да се најавен лекар (currentLekar) и да е директорот
async function loadAdminOglasi() {
  const container = document.getElementById('oglasi-admin-list');
  if (!container || !currentLekar) return;
  
  try {
    container.innerHTML = '<div class="loading">Вчитувам огласи...</div>';
    
    const res = await fetch(`${API_BASE}/admin/oglasi?admin_doctor_id=${currentLekar.doctor_ID}`);
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.detail || `HTTP грешка! Статус: ${res.status}`);
    }
    
    const oglasi = await res.json();
    
    if (oglasi.length === 0) {
      container.innerHTML = '<div class="loading">Нема огласи.</div>';
      return;
    }
    
    container.innerHTML = '';
    oglasi.forEach(o => {
      const div = document.createElement('div');
      div.className = 'admin-item';
      div.innerHTML = `
        <div class="admin-item-content">
          <h4>${o.pozicija} - ${o.oddel}</h4>
          <p><strong>Датум на објава:</strong> ${o.datum_na_objava || 'Н/П'}</p>
          <p><strong>Рок за пријавување:</strong> ${o.datum_na_prijavuvanje || 'Н/П'}</p>
          <p><strong>Статус:</strong> ${o.status_oglas || 'Активен'}</p>
        </div>
        <div class="admin-item-actions">
          <button class="btn-edit" onclick="editOglas(${o.id_oglas})">Уреди</button>
          <button class="btn-delete" onclick="deleteOglas(${o.id_oglas})">Избриши</button>
        </div>
      `;
      container.appendChild(div);
    });
  } catch (err) {
    container.innerHTML = `<div class="loading" style="color: red;">Грешка: ${err.message}</div>`;
  }
}

// Вчитување на лекари за select во формата за дежурство
// Ги вчитува сите лекари од базата и ги пополнува во dropdown менито за избор на лекар
async function loadDoctorsForAdmin() {
  const select = document.getElementById('dezurstvo-doctor-select');
  if (!select) return;
  
  try {
    const res = await fetch(API_BASE + '/lekari');
    if (res.ok) {
      const lekari = await res.json();
      select.innerHTML = '<option value="">Изберете лекар...</option>';
      lekari.forEach(lekar => {
        const option = document.createElement('option');
        option.value = lekar.doctor_ID;
        option.textContent = `${lekar.name} ${lekar.surname} - ${lekar.specijalnost || 'Н/П'}`;
        select.appendChild(option);
      });
    }
  } catch (err) {
    console.error('Грешка при вчитување на лекари:', err);
  }
}

// Отворање на форма за дежурство
function openDezurstvoForm(dezurstvoId = null) {
  if (!currentLekar) {
    alert('Не сте најавени');
    return;
  }
  
  // Проверка дали најавениот лекар е директорот
  const doctorName = `${currentLekar.name} ${currentLekar.surname}`.trim();
  const adminNames = ["Владко Захариев", "Влатко Захариев", "Владко Захаријев", "Влатко Захаријев"];
  if (!adminNames.includes(doctorName)) {
    alert('Немате пристап до административниот панел');
    return;
  }
  
  const modal = document.getElementById('dezurstvo-form-modal');
  const form = document.getElementById('dezurstvo-form');
  const title = document.getElementById('dezurstvo-form-title');
  
  if (!modal || !form) return;
  
  // Ресетирај форма
  form.reset();
  document.getElementById('dezurstvo-id').value = '';
  
  if (dezurstvoId) {
    // Уредување на постоечко дежурство
    title.textContent = 'Уреди дежурство';
    loadDezurstvoForEdit(dezurstvoId);
  } else {
    // Ново дежурство
    title.textContent = 'Додади ново дежурство';
    // Постави денешен датум како default
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('dezurstvo-datum').value = today;
  }
  
  modal.style.display = 'block';
  loadDoctorsForAdmin();
}

// Затворање на форма за дежурство
// Затвора модалниот прозорец за формата за дежурство
function closeDezurstvoForm() {
  const modal = document.getElementById('dezurstvo-form-modal');
  if (modal) {
    modal.style.display = 'none';
  }
}

// Вчитување на дежурство за уредување
// Параметри: dezurstvoId - ID на дежурството што треба да се уреди
// Ги вчитува податоците за дежурството и ги пополнува полињата во формата
async function loadDezurstvoForEdit(dezurstvoId) {
  if (!currentLekar) {
    alert('Не сте најавени');
    return;
  }
  
  try {
    // Вчитај ги сите дежурства и најди го тоа со соодветниот ID
    const res = await fetch(`${API_BASE}/admin/dezurstva?admin_doctor_id=${currentLekar.doctor_ID}`);
    if (!res.ok) throw new Error('Грешка при вчитување');
    
    const dezurstva = await res.json();
    const dezurstvo = dezurstva.find(d => d.dezurstvo_ID === dezurstvoId);
    
    if (dezurstvo) {
      document.getElementById('dezurstvo-id').value = dezurstvo.dezurstvo_ID;
      document.getElementById('dezurstvo-doctor-select').value = dezurstvo.doctor_ID;
      document.getElementById('dezurstvo-datum').value = dezurstvo.datum;
      document.getElementById('dezurstvo-oddel').value = dezurstvo.oddel;
      document.getElementById('dezurstvo-vreme-od').value = dezurstvo.vreme_od.substring(0, 5);
      document.getElementById('dezurstvo-vreme-do').value = dezurstvo.vreme_do.substring(0, 5);
      document.getElementById('dezurstvo-napomena').value = dezurstvo.napomena || '';
    }
  } catch (err) {
    alert('Грешка при вчитување на дежурство: ' + err.message);
  }
}

// Уредување на дежурство
// Параметри: dezurstvoId - ID на дежурството што треба да се уреди
// Отвора формата за дежурство со пополнети податоци
function editDezurstvo(dezurstvoId) {
  openDezurstvoForm(dezurstvoId);
}

// Бришење на дежурство
// Параметри: dezurstvoId - ID на дежурството што треба да се избрише
// Брише дежурство од базата по потврда од корисникот
async function deleteDezurstvo(dezurstvoId) {
  if (!confirm('Дали сте сигурни дека сакате да го избришете ова дежурство?')) {
    return;
  }
  
  if (!currentLekar) {
    alert('Не сте најавени');
    return;
  }
  
  try {
    const res = await fetch(`${API_BASE}/admin/dezurstva/${dezurstvoId}?admin_doctor_id=${currentLekar.doctor_ID}`, {
      method: 'DELETE'
    });
    
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || 'Грешка при бришење');
    }
    
    alert('Дежурството е успешно избришано');
    loadAdminDezurstva();
  } catch (err) {
    alert('Грешка при бришење: ' + err.message);
  }
}

// Отворање на форма за оглас
// Параметри: oglasId - ID на огласот за уредување (null за нов оглас)
// Проверува дали најавениот лекар е директорот пред да отвори формата
function openOglasForm(oglasId = null) {
  if (!currentLekar) {
    alert('Не сте најавени');
    return;
  }
  
  // Проверка дали најавениот лекар е директорот (Владко Захариев)
  // Точниот формат во базата е "Владко Захариев"
  const doctorName = `${currentLekar.name} ${currentLekar.surname}`.trim();
  const adminNames = [
    "Владко Захариев",  // Точниот формат во базата
    "Влатко Захариев",  // Варијација со "Влатко"
    "Владко Захаријев", // Варијација со "Захаријев"
    "Влатко Захаријев"  // Комбинација на двете варијации
  ];
  if (!adminNames.includes(doctorName)) {
    alert('Немате пристап до административниот панел');
    return;
  }
  
  const modal = document.getElementById('oglas-form-modal');
  const form = document.getElementById('oglas-form');
  const title = document.getElementById('oglas-form-title');
  
  if (!modal || !form) return;
  
  // Ресетирај форма
  form.reset();
  document.getElementById('oglas-id').value = '';
  
  if (oglasId) {
    // Уредување на постоечки оглас
    title.textContent = 'Уреди оглас';
    loadOglasForEdit(oglasId);
  } else {
    // Нов оглас
    title.textContent = 'Додади нов оглас';
    // Постави денешен датум како default
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('oglas-datum-objava').value = today;
  }
  
  modal.style.display = 'block';
}

// Затворање на форма за оглас
// Затвора модалниот прозорец за формата за оглас
function closeOglasForm() {
  const modal = document.getElementById('oglas-form-modal');
  if (modal) {
    modal.style.display = 'none';
  }
}

// Вчитување на оглас за уредување
// Параметри: oglasId - ID на огласот што треба да се уреди
// Ги вчитува податоците за огласот и ги пополнува полињата во формата
async function loadOglasForEdit(oglasId) {
  if (!currentLekar) {
    alert('Не сте најавени');
    return;
  }
  
  try {
    const res = await fetch(`${API_BASE}/admin/oglasi?admin_doctor_id=${currentLekar.doctor_ID}`);
    if (!res.ok) throw new Error('Грешка при вчитување');
    
    const oglasi = await res.json();
    const oglas = oglasi.find(o => o.id_oglas === oglasId);
    
    if (oglas) {
      document.getElementById('oglas-id').value = oglas.id_oglas;
      document.getElementById('oglas-pozicija').value = oglas.pozicija;
      document.getElementById('oglas-oddel').value = oglas.oddel;
      document.getElementById('oglas-datum-objava').value = oglas.datum_na_objava;
      document.getElementById('oglas-datum-prijava').value = oglas.datum_na_prijavuvanje;
      document.getElementById('oglas-status').value = oglas.status_oglas || '';
    }
  } catch (err) {
    alert('Грешка при вчитување на оглас: ' + err.message);
  }
}

// Уредување на оглас
// Параметри: oglasId - ID на огласот што треба да се уреди
// Отвора формата за оглас со пополнети податоци
function editOglas(oglasId) {
  openOglasForm(oglasId);
}

// Бришење на оглас
// Параметри: oglasId - ID на огласот што треба да се избрише
// Брише оглас од базата по потврда од корисникот
async function deleteOglas(oglasId) {
  if (!confirm('Дали сте сигурни дека сакате да го избришете овој оглас?')) {
    return;
  }
  
  if (!currentLekar) {
    alert('Не сте најавени');
    return;
  }
  
  try {
    const res = await fetch(`${API_BASE}/admin/oglasi/${oglasId}?admin_doctor_id=${currentLekar.doctor_ID}`, {
      method: 'DELETE'
    });
    
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || 'Грешка при бришење');
    }
    
    alert('Огласот е успешно избришан');
    loadAdminOglasi();
  } catch (err) {
    alert('Грешка при бришење: ' + err.message);
  }
}

// ============================================================================
// НОВОСТИ (јавна листа + администрација за директорот)
// ============================================================================
function resolveNovostSlikaUrl(p) {
  if (!p || typeof p !== 'string') return '';
  var s = p.trim();
  if (s.indexOf('http://') === 0 || s.indexOf('https://') === 0) return s;
  return API_BASE + '/static/' + s;
}

function formatSodrzinaForDisplay(text) {
  if (!text) return '';
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br/>');
}

function getVideoInfo(url) {
  if (!url || typeof url !== 'string') return null;
  var u = url.trim();
  if (!u) return null;
  // YouTube – користиме youtube-nocookie.com за да се избегне Error 153
  var m = u.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]+)/);
  if (m) return { type: 'embed', url: 'https://www.youtube-nocookie.com/embed/' + m[1] };
  m = u.match(/youtube\.com\/embed\/([a-zA-Z0-9_-]+)/);
  if (m) return { type: 'embed', url: 'https://www.youtube-nocookie.com/embed/' + m[1] };
  m = u.match(/youtube-nocookie\.com\/embed\/([a-zA-Z0-9_-]+)/);
  if (m) return { type: 'embed', url: u };
  // Vimeo
  m = u.match(/vimeo\.com\/(?:video\/)?(\d+)/);
  if (m) return { type: 'embed', url: 'https://player.vimeo.com/video/' + m[1] };
  // Direct video files
  if (/\.(mp4|webm|ogg)$/i.test(u)) {
    return { type: 'file', url: u };
  }
  // Generic embed/player URLs
  if (u.indexOf('embed') !== -1 || u.indexOf('player.') !== -1) {
    return { type: 'embed', url: u };
  }
  // Fallback: treat as direct link opened in iframe
  return { type: 'embed', url: u };
}

async function loadNovosti() {
  var listEl = document.getElementById('novosti-list');
  if (!listEl) return;
  try {
    listEl.innerHTML = '<div class="loading">Вчитувам новости...</div>';
    var res = await fetch(API_BASE + '/novosti');
    if (!res.ok) throw new Error('Грешка при вчитување');
    var data = await res.json();
    renderNovosti(data);
  } catch (err) {
    listEl.innerHTML = '<div class="loading" style="color:red;">' + (err.message || 'Грешка при вчитување на новости.') + '</div>';
  }
}

function renderNovosti(items) {
  var listEl = document.getElementById('novosti-list');
  if (!listEl) return;
  if (!items || items.length === 0) {
    listEl.innerHTML = '<p class="loading">Нема објавени новости.</p>';
    return;
  }
  listEl.innerHTML = '';
  items.forEach(function(n) {
    var raw = n.sodrzina || '';
    var excerpt = raw.substring(0, 150).replace(/\n/g, ' ');
    if (raw.length > 150) excerpt += '...';
    var dateStr = n.created_at ? (n.created_at.split('T')[0] || n.created_at) : '';
    var author = [n.author_name, n.author_surname].filter(Boolean).join(' ') || 'Болница';
    var imgUrl = resolveNovostSlikaUrl(n.slika_path);
    var card = document.createElement('div');
    card.className = 'novosti-card';
    card.innerHTML =
      (imgUrl ? '<img src="' + imgUrl + '" alt="" class="novosti-card-img" />' : '') +
      '<div class="novosti-card-body">' +
      '<h3 class="novosti-card-title">' + (n.naslov || '').replace(/</g, '&lt;') + '</h3>' +
      '<p class="novosti-card-meta">' + dateStr + ' &middot; ' + author + '</p>' +
      '<p class="novosti-card-excerpt">' + (excerpt || '').replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</p>' +
      '<button type="button" class="btn-primary btn-sm" onclick="openNovostViewModal(' + n.id + ')">Прочитај повеќе</button>' +
      '</div>';
    listEl.appendChild(card);
  });
}

function openNovostViewModal(id) {
  var modal = document.getElementById('novost-view-modal');
  var content = document.getElementById('novost-view-content');
  if (!modal || !content) return;
  content.innerHTML = '<div class="loading">Вчитувам...</div>';
  if (modal) modal.style.display = 'block';
  fetch(API_BASE + '/novosti/' + id)
    .then(function(r) { return r.ok ? r.json() : Promise.reject(new Error('Не е пронајдена')); })
    .then(function(n) {
      var imgUrl = resolveNovostSlikaUrl(n.slika_path);
      var author = [n.author_name, n.author_surname].filter(Boolean).join(' ') || 'Болница';
      var dateStr = n.created_at ? (n.created_at.split('T')[0] || n.created_at) : '';
      var topHtml = (imgUrl ? '<img src="' + imgUrl + '" alt="" class="novost-main-img" />' : '');
      var extra = n.slike_extra && Array.isArray(n.slike_extra) ? n.slike_extra : [];
      var textHtml = '<h2>' + (n.naslov || '').replace(/</g, '&lt;') + '</h2>' +
        '<p style="color:#666; margin-bottom:1rem;">' + dateStr + ' &middot; ' + author + '</p>' +
        '<div class="novosti-full-sodrzina">' + formatSodrzinaForDisplay(n.sodrzina) + '</div>';
      var galleryHtml = '';
      if (extra.length) {
        galleryHtml = '<div class="novost-extra-gallery">';
        extra.forEach(function(p) {
          var src = (p.indexOf('http') === 0 || p.indexOf('/') === 0) ? p : API_BASE + '/static/' + p;
          galleryHtml += '<img class="novost-extra-thumb" src="' + src.replace(/"/g, '&quot;') + '" alt="" />';
        });
        galleryHtml += '</div>';
      }
      var videoHtml = '';
      var videoInfo = getVideoInfo(n.video_url);
      if (videoInfo) {
        if (videoInfo.type === 'file') {
          var vSrc = videoInfo.url;
          if (vSrc.indexOf('http') !== 0 && vSrc.charAt(0) !== '/') {
            vSrc = API_BASE + '/static/' + vSrc;
          }
          vSrc = vSrc.replace(/"/g, '&quot;');
          videoHtml =
            '<div class="novost-video-wrap" style="margin-top:1.5rem; text-align:center;">' +
            '<video controls style="max-width:100%; width:560px; max-height:360px; border-radius:8px; box-shadow:0 4px 12px rgba(0,0,0,0.25);">' +
            '<source src="' + vSrc + '" type="video/mp4" />' +
            '</video>' +
            '</div>';
        } else {
          var eUrl = videoInfo.url.replace(/"/g, '&quot;');
          var allowAttr = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
          videoHtml =
            '<div class="novost-video-wrap" style="margin-top:1.5rem; text-align:center;">' +
            '<iframe src="' + eUrl + '" allow="' + allowAttr + '" allowfullscreen style="max-width:100%; width:560px; height:315px; border:0; border-radius:8px; box-shadow:0 4px 12px rgba(0,0,0,0.25);"></iframe>' +
            '</div>';
        }
      }
      content.innerHTML = topHtml + textHtml + galleryHtml + videoHtml;
      setupNovostGallery(content);
    })
    .catch(function() { content.innerHTML = '<p style="color:red;">Грешка при вчитување.</p>'; });
}

function setupNovostGallery(rootEl) {
  var root = rootEl || document;
  var thumbs = root.querySelectorAll('.novost-extra-thumb');
  if (!thumbs.length) return;
  var urls = Array.prototype.map.call(thumbs, function(img) { return img.getAttribute('src'); });
  thumbs.forEach(function(img, index) {
    img.addEventListener('click', function() {
      openNovostGalleryLightbox(urls, index);
    });
  });
}

function openNovostGalleryLightbox(urls, startIndex) {
  if (!urls || !urls.length) return;
  var existing = document.getElementById('novost-gallery-lightbox');
  if (existing) existing.remove();
  var overlay = document.createElement('div');
  overlay.id = 'novost-gallery-lightbox';
  var inner = document.createElement('div');
  inner.className = 'novost-gallery-inner';
  var img = document.createElement('img');
  img.className = 'novost-gallery-image';
  inner.appendChild(img);
  var close = document.createElement('div');
  close.className = 'novost-gallery-close';
  close.textContent = '×';
  inner.appendChild(close);
  var left = document.createElement('div');
  left.className = 'novost-gallery-arrow left';
  left.textContent = '‹';
  var right = document.createElement('div');
  right.className = 'novost-gallery-arrow right';
  right.textContent = '›';
  inner.appendChild(left);
  inner.appendChild(right);
  overlay.appendChild(inner);
  document.body.appendChild(overlay);

  var current = startIndex || 0;
  function render() {
    if (current < 0) current = urls.length - 1;
    if (current >= urls.length) current = 0;
    img.src = urls[current];
  }
  render();

  function go(delta) {
    current += delta;
    render();
  }

  left.addEventListener('click', function(e) {
    e.stopPropagation();
    go(-1);
  });
  right.addEventListener('click', function(e) {
    e.stopPropagation();
    go(1);
  });
  close.addEventListener('click', function(e) {
    e.stopPropagation();
    overlay.remove();
  });
  overlay.addEventListener('click', function() {
    overlay.remove();
  });
}

function closeNovostViewModal() {
  var modal = document.getElementById('novost-view-modal');
  if (modal) modal.style.display = 'none';
}

async function loadNovostiAdmin() {
  var listEl = document.getElementById('novosti-admin-list');
  if (!listEl || !currentLekar) return;
  try {
    listEl.innerHTML = '<div class="loading">Вчитувам новости...</div>';
    var res = await fetch(API_BASE + '/novosti');
    if (!res.ok) throw new Error('Грешка при вчитување');
    var data = await res.json();
    listEl.innerHTML = '';
    if (!data.length) {
      listEl.innerHTML = '<p>Нема новости. Додадете прва новост.</p>';
      return;
    }
    data.forEach(function(n) {
      var dateStr = n.created_at ? (n.created_at.split('T')[0] || n.created_at) : '';
      var div = document.createElement('div');
      div.className = 'admin-list-item';
      div.innerHTML =
        '<div class="admin-list-item-content">' +
        '<strong>' + (n.naslov || '').replace(/</g, '&lt;') + '</strong> &ndash; ' + dateStr +
        '</div>' +
        '<div class="admin-list-item-actions">' +
        '<button type="button" class="btn-edit" onclick="editNovost(' + n.id + ')">Уреди</button> ' +
        '<button type="button" class="btn-delete" onclick="deleteNovost(' + n.id + ')">Избриши</button>' +
        '</div>';
      listEl.appendChild(div);
    });
  } catch (err) {
    listEl.innerHTML = '<p style="color:red;">' + (err.message || 'Грешка') + '</p>';
  }
}

function openNovostForm(id) {
  document.getElementById('novost-form-title').textContent = id ? 'Уреди новост' : 'Додади новост';
  document.getElementById('novost-id').value = id || '';
  document.getElementById('novost-naslov').value = '';
  document.getElementById('novost-sodrzina').value = '';
  document.getElementById('novost-slika').value = '';
  var videoEl = document.getElementById('novost-video-url');
  if (videoEl) videoEl.value = '';
  var extraInput = document.getElementById('novost-sliki-extra');
  if (extraInput) extraInput.value = '';
  var extraUrlsEl = document.getElementById('novost-slike-extra-urls');
  if (extraUrlsEl) extraUrlsEl.value = '';
  var urlEl = document.getElementById('novost-slika-url');
  if (urlEl) urlEl.value = '';
  var wrap = document.getElementById('novost-current-image');
  var img = document.getElementById('novost-current-image-img');
  var removeCb = document.getElementById('novost-remove-slika');
  if (wrap) { wrap.style.display = 'none'; img.src = ''; }
  if (removeCb) removeCb.checked = false;
  if (id) {
    fetch(API_BASE + '/novosti/' + id)
      .then(function(r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function(n) {
        document.getElementById('novost-naslov').value = n.naslov || '';
        document.getElementById('novost-sodrzina').value = n.sodrzina || '';
        if (videoEl && n.video_url) videoEl.value = n.video_url;
        if (n.slika_path) {
          img.src = resolveNovostSlikaUrl(n.slika_path);
          wrap.style.display = 'block';
        }
        var urlEl = document.getElementById('novost-slika-url');
        if (urlEl) urlEl.value = (n.slika_path && (n.slika_path.indexOf('http') === 0)) ? n.slika_path : '';
        var extra = n.slike_extra && Array.isArray(n.slike_extra) ? n.slike_extra : [];
        if (extraUrlsEl && extra.length) extraUrlsEl.value = extra.join('\n');
      })
      .catch(function() {});
  }
  var m = document.getElementById('novost-form-modal');
  if (m) m.style.display = 'block';
}

function closeNovostForm() {
  var m = document.getElementById('novost-form-modal');
  if (m) m.style.display = 'none';
}

function editNovost(id) {
  openNovostForm(id);
}

async function deleteNovost(id) {
  if (!currentLekar || !confirm('Дали сте сигурни дека сакате да ја избришете оваа новост?')) return;
  try {
    var res = await fetch(API_BASE + '/admin/novosti/' + id + '?admin_doctor_id=' + currentLekar.doctor_ID, { method: 'DELETE' });
    if (!res.ok) {
      var d = await res.json();
      throw new Error(d.detail || 'Грешка при бришење');
    }
    alert('Новоста е избришана.');
    loadNovostiAdmin();
    loadNovosti();
  } catch (err) {
    alert(err.message);
  }
}

// ============================================================================
// EVENT LISTENERS ЗА АДМИНИСТРАТИВНИ ФОРМИ
// ============================================================================

// Поставување на event listeners за административните форми
// Се извршува кога DOM е целосно вчитан
document.addEventListener('DOMContentLoaded', () =>{
  // Форма за дежурство - обработка на submit
  const dezurstvoForm = document.getElementById('dezurstvo-form');
  if (dezurstvoForm) {
    dezurstvoForm.addEventListener('submit', async function(e) {
      e.preventDefault();
      
      const dezurstvoId = document.getElementById('dezurstvo-id').value;
      const doctorId = document.getElementById('dezurstvo-doctor-select').value;
      const datum = document.getElementById('dezurstvo-datum').value;
      const oddel = document.getElementById('dezurstvo-oddel').value;
      const vremeOd = document.getElementById('dezurstvo-vreme-od').value;
      const vremeDo = document.getElementById('dezurstvo-vreme-do').value;
      const napomena = document.getElementById('dezurstvo-napomena').value;
      
      try {
        if (!currentLekar) {
          alert('Не сте најавени');
          return;
        }
        
        const url = dezurstvoId 
          ? `${API_BASE}/admin/dezurstva/${dezurstvoId}`
          : API_BASE + '/admin/dezurstva';
        
        const method = dezurstvoId ? 'PUT' : 'POST';
        
        const res = await fetch(url, {
          method: method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            admin_doctor_id: currentLekar.doctor_ID,
            doctor_ID: parseInt(doctorId),
            datum: datum,
            oddel: oddel,
            vreme_od: vremeOd,
            vreme_do: vremeDo,
            napomena: napomena || null
          })
        });
        
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || 'Грешка при зачувување');
        }
        
        alert(dezurstvoId ? 'Дежурството е успешно ажурирано' : 'Дежурството е успешно креирано');
        closeDezurstvoForm();
        loadAdminDezurstva();
      } catch (err) {
        alert('Грешка: ' + err.message);
      }
    });
    setupAuth();
  }
  
  // Форма за оглас - обработка на submit
  const oglasForm = document.getElementById('oglas-form');
  if (oglasForm) {
    oglasForm.addEventListener('submit', async function(e) {
      e.preventDefault();
      
      const oglasId = document.getElementById('oglas-id').value;
      const pozicija = document.getElementById('oglas-pozicija').value;
      const oddel = document.getElementById('oglas-oddel').value;
      const datumObjava = document.getElementById('oglas-datum-objava').value;
      const datumPrijava = document.getElementById('oglas-datum-prijava').value;
      const status = document.getElementById('oglas-status').value;
      
      try {
        if (!currentLekar) {
          alert('Не сте најавени');
          return;
        }
        
        if (oglasId) {
          // Ажурирање
          const res = await fetch(`${API_BASE}/admin/oglasi/${oglasId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              admin_doctor_id: currentLekar.doctor_ID,
              pozicija: pozicija,
              oddel: oddel,
              datum_na_objava: datumObjava,
              datum_na_prijavuvanje: datumPrijava,
              status_oglas: status || null
            })
          });
          
          if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || 'Грешка при ажурирање');
          }
          
          alert('Огласот е успешно ажуриран');
        } else {
          // Креирање (користи административен endpoint за да нема валидација на позицијата)
          const res = await fetch(API_BASE + '/admin/oglasi', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              admin_doctor_id: currentLekar.doctor_ID,
              pozicija: pozicija,
              oddel: oddel,
              datum_na_objava: datumObjava,
              datum_na_prijavuvanje: datumPrijava,
              status_oglas: status || null
            })
          });
          
          if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || 'Грешка при креирање');
          }
          
          alert('Огласот е успешно креиран');
        }
        
        closeOglasForm();
        loadAdminOglasi();
      } catch (err) {
        alert('Грешка: ' + err.message);
      }
    });
  }

  var novostForm = document.getElementById('novost-form');
  if (novostForm) {
    novostForm.addEventListener('submit', async function(e) {
      e.preventDefault();
      if (!currentLekar) { alert('Не сте најавени'); return; }
      var id = document.getElementById('novost-id').value;
      var naslov = document.getElementById('novost-naslov').value.trim();
      var sodrzina = document.getElementById('novost-sodrzina').value.trim();
      var removeSlika = document.getElementById('novost-remove-slika').checked;
      var fileInput = document.getElementById('novost-slika');
      var videoUrlEl = document.getElementById('novost-video-url');
      var extraSlikiEl = document.getElementById('novost-sliki-extra');
      if (!naslov) { alert('Внесете наслов.'); return; }
      try {
        var formData = new FormData();
        formData.append('naslov', naslov);
        formData.append('sodrzina', sodrzina);
        formData.append('admin_doctor_id', currentLekar.doctor_ID);
        if (videoUrlEl) formData.append('video_url', (videoUrlEl.value || '').trim());
        var slikaUrlEl = document.getElementById('novost-slika-url');
        if (slikaUrlEl && (slikaUrlEl.value || '').trim()) formData.append('slika_url', (slikaUrlEl.value || '').trim());
        if (fileInput.files.length) formData.append('slika', fileInput.files[0]);
        var extraUrlsEl = document.getElementById('novost-slike-extra-urls');
        if (extraUrlsEl) formData.append('slike_extra_urls', (extraUrlsEl.value || '').trim());
        if (extraSlikiEl && extraSlikiEl.files.length) {
          for (var i = 0; i < extraSlikiEl.files.length; i++) formData.append('sliki_extra', extraSlikiEl.files[i]);
        }
        if (id) {
          formData.append('remove_slika', removeSlika ? '1' : '0');
          var res = await fetch(API_BASE + '/admin/novosti/' + id, { method: 'PUT', body: formData });
          if (!res.ok) {
            var d = await res.json().catch(function() { return {}; });
            var msg = d.detail;
            if (Array.isArray(msg)) {
              msg = msg.map(function(x) {
                var loc = Array.isArray(x.loc) ? x.loc.join('.') : '';
                var text = x.msg || '';
                return (loc ? loc + ': ' : '') + text;
              }).join('; ');
            }
            throw new Error(msg || 'Грешка при ажурирање');
          }
          alert('Новоста е ажурирана.');
        } else {
          var res = await fetch(API_BASE + '/admin/novosti', { method: 'POST', body: formData });
          if (!res.ok) {
            var d = await res.json().catch(function() { return {}; });
            var msg = d.detail;
            if (Array.isArray(msg)) {
              msg = msg.map(function(x) {
                var loc = Array.isArray(x.loc) ? x.loc.join('.') : '';
                var text = x.msg || '';
                return (loc ? loc + ': ' : '') + text;
              }).join('; ');
            }
            throw new Error(msg || 'Грешка при додавање');
          }
          alert('Новоста е додадена.');
        }
        closeNovostForm();
        loadNovostiAdmin();
        if (typeof loadNovosti === 'function') loadNovosti();
      } catch (err) {
        alert(err.message || 'Грешка при зачувување.');
      }
    });
  }
  
  // Затворање на модални прозорци при клик на X копчето
  const dezurstvoModal = document.getElementById('dezurstvo-form-modal');
  if (dezurstvoModal) {
    const closeBtn = dezurstvoModal.querySelector('.close');
    if (closeBtn) {
      closeBtn.addEventListener('click', closeDezurstvoForm);
    }
  }
  
  const oglasModal = document.getElementById('oglas-form-modal');
  if (oglasModal) {
    const closeBtn = oglasModal.querySelector('.close');
    if (closeBtn) {
      closeBtn.addEventListener('click', closeOglasForm);
    }
  }
});
// ============================================================================
// НОВИ ФУНКЦИИ ЗА ЕДИНСТВЕН AUTH МОДАЛ
// ============================================================================

let currentRole = 'pacient'; // 'pacient' или 'lekar'
let currentAuthMode = 'login'; // 'login' или 'register'

// Отворање на модалот за најава
function openLoginModal() {
  currentAuthMode = 'login';
  document.getElementById('auth-subtitle').textContent = 'Најавете се на вашиот профил';
  document.getElementById('login-form-container').style.display = 'block';
  document.getElementById('register-form-container').style.display = 'none';
  document.getElementById('auth-modal').style.display = 'block';
  resetAuthForms();
}

// Отворање на модалот за регистрација
function openRegisterModal() {
  currentAuthMode = 'register';
  document.getElementById('auth-subtitle').textContent = 'Креирајте нов профил';
  document.getElementById('login-form-container').style.display = 'none';
  document.getElementById('register-form-container').style.display = 'block';
  document.getElementById('auth-modal').style.display = 'block';
  updateRegisterFields();
  resetAuthForms();
}

// Затворање на модалот
function closeAuthModal() {
  document.getElementById('auth-modal').style.display = 'none';
  resetAuthForms();
}

// Префрлање на најава
function showLogin() {
  currentAuthMode = 'login';
  document.getElementById('auth-subtitle').textContent = 'Најавете се на вашиот профил';
  document.getElementById('login-form-container').style.display = 'block';
  document.getElementById('register-form-container').style.display = 'none';
  var forgotContainer = document.getElementById('forgot-password-container');
  if (forgotContainer) forgotContainer.style.display = 'none';
  resetAuthForms();
}

// Префрлање на регистрација
function showRegister() {
  currentAuthMode = 'register';
  document.getElementById('auth-subtitle').textContent = 'Креирајте нов профил';
  document.getElementById('login-form-container').style.display = 'none';
  document.getElementById('register-form-container').style.display = 'block';
  var forgotContainer = document.getElementById('forgot-password-container');
  if (forgotContainer) forgotContainer.style.display = 'none';
  updateRegisterFields();
  resetAuthForms();
}

// Заборавена лозинка – прикажи форма (код се печати во терминалот на backend)
function showForgotPassword() {
  document.getElementById('login-form-container').style.display = 'none';
  document.getElementById('register-form-container').style.display = 'none';
  var forgotContainer = document.getElementById('forgot-password-container');
  if (forgotContainer) forgotContainer.style.display = 'block';
  document.getElementById('forgot-reset-block').style.display = 'none';
  document.getElementById('forgot-password-form').reset();
  document.getElementById('reset-password-form').reset();
  document.getElementById('reset-email').value = '';
  document.getElementById('reset-error').style.display = 'none';
  var title = document.getElementById('forgot-title');
  if (title) title.textContent = currentRole === 'lekar' ? 'Заборавена лозинка (лекар)' : 'Заборавена лозинка (пациент)';
}

// Менаѓање на улога (Пациент/Лекар)
function switchRole(role) {
  currentRole = role;
  
  // Ажурирај табови
  document.querySelectorAll('.role-tab').forEach(tab => tab.classList.remove('active'));
  document.getElementById(`tab-${role}`).classList.add('active');
  
  // Ажурирај полиња за регистрација
  if (currentAuthMode === 'register') {
    updateRegisterFields();
  }
  
  // Ажурирај placeholder за најава (идентификатор: е-пошта за пациент, корисничко име за лекар)
  const identifierInput = document.getElementById('login-identifier');
  if (identifierInput && role === 'lekar') {
    identifierInput.placeholder = 'ime.prezime (од регистрацијата)';
  } else if (identifierInput) {
    identifierInput.placeholder = 'Овде внесете го вашиот mail';
  }
}

// Ажурирање на полињата за регистрација според улогата
function updateRegisterFields() {
  const pacientFields = document.getElementById('pacient-only-fields');
  const lekarFields = document.getElementById('lekar-only-fields');
  const embgField = document.getElementById('embg-field');
  
  if (currentRole === 'lekar') {
    if (pacientFields) pacientFields.style.display = 'none';
    if (lekarFields) lekarFields.style.display = 'block';
    if (embgField) embgField.style.display = 'none';
  } else {
    if (pacientFields) pacientFields.style.display = 'block';
    if (lekarFields) lekarFields.style.display = 'none';
    if (embgField) embgField.style.display = 'block';
  }
}

// Ресетирање на формите
function resetAuthForms() {
  document.getElementById('auth-login-form')?.reset();
  document.getElementById('auth-register-form')?.reset();
  document.getElementById('login-error').style.display = 'none';
  document.getElementById('register-error').style.display = 'none';
  var forgotReset = document.getElementById('forgot-reset-block');
  if (forgotReset) forgotReset.style.display = 'none';
  document.getElementById('forgot-password-form')?.reset();
  document.getElementById('reset-password-form')?.reset();
  var resetErr = document.getElementById('reset-error');
  if (resetErr) resetErr.style.display = 'none';
}

// Прикажување на грешка
function showAuthError(elementId, message) {
  const errorEl = document.getElementById(elementId);
  errorEl.textContent = message;
  errorEl.style.display = 'block';
  setTimeout(() => {
    errorEl.style.display = 'none';
  }, 5000);
}

// ============================================================================
// ОБРАБОТКА НА ФОРМИ
// ============================================================================

// Најава
async function handleLogin(e) {
  e.preventDefault();
  
  const identifierInput = document.getElementById('login-identifier');
  const passwordInput = document.getElementById('login-password');
  const submitBtn = e.target && e.target.querySelector('.btn-auth-submit');
  const btnText = submitBtn && submitBtn.querySelector('.btn-text');
  const btnLoading = submitBtn && submitBtn.querySelector('.btn-loading');
  const identifier = (identifierInput && identifierInput.value.trim()) || '';
  const password = passwordInput ? passwordInput.value : '';

  if (!identifier || !password) {
    showAuthError('login-error', currentRole === 'lekar' ? 'Внесете корисничко име и лозинка' : 'Внесете е-пошта и лозинка');
    return;
  }

  if (submitBtn) submitBtn.disabled = true;
  if (btnText) btnText.style.display = 'none';
  if (btnLoading) btnLoading.style.display = 'inline-block';
  
  try {
    let endpoint, body;
    
    if (currentRole === 'lekar') {
      // За лекари: користи username (email без @...)
      endpoint = API_BASE + '/lekari/login';
      let username = identifier.toLowerCase().trim();
      // ako e vnesen email se dele kaj @ i se zema delot pred nego
      if (username.includes('@')) {
        username = username.split('@')[0];
      }
      if (!username.includes('.')) {
        throw new Error('За да продолжите со најава, ве молиме внесете го вашето корисничко име во форма име.презиме(на латиница).');
      }
      body = { username: username, password: password };
      console.log('[DEBUG lekar login] username:', username, '| password length:', password ? password.length : 0, '| endpoint:', endpoint);
    } else {
      // За пациенти: користи email
      endpoint = API_BASE + '/pacienti/login';
      body = { email: identifier, password: password };
    }
    
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    
    if (!res.ok) {
      let errorDetail = 'Настана грешка при најава';
      try {
        const errJson = await res.json();
        errorDetail = errJson.detail || errorDetail;
      } catch (e) {
        console.error('[DEBUG] res.json() failed, status:', res.status, 'statusText:', res.statusText);
      }
      console.error('[DEBUG login error] status:', res.status, 'detail:', errorDetail);
      throw new Error(errorDetail);
    }
    
    const data = await res.json();
    
    if (currentRole === 'lekar') {
      currentLekar = data.doctor;
      try { sessionStorage.setItem('currentLekar', JSON.stringify(data.doctor)); } catch (e) {}
      closeAuthModal();
      displayLekarDashboard(data);
      openLekarDashboardModal();
      setTimeout(() => {
        alert(`Добредојде, Др. ${data.doctor.name} ${data.doctor.surname}!`);
      }, 300);
    } else {
      currentPacient = data.pacient;
      try { sessionStorage.setItem('currentPacient', JSON.stringify(data.pacient)); } catch (e) {}
      closeAuthModal();
      updateNavForPacient();

      const pendingDoctorId = sessionStorage.getItem('pending_appointment_doctor_id');
      if (pendingDoctorId) {
        sessionStorage.removeItem('pending_appointment_doctor_id');
        var doctorIdNum = parseInt(pendingDoctorId, 10);
        setTimeout(function () { openAppointmentModalInternal(doctorIdNum); }, 200);
      } else {
        setTimeout(function () {
          alert('Добредојде, ' + data.pacient.ime + ' ' + data.pacient.prezime + '! Одберете лекар во секцијата „Лекари“ подолу и кликнете „Закажи преглед“.');
          var lekariEl = document.getElementById('lekari');
          if (lekariEl) lekariEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 300);
      }
    }
    
  } catch (err) {
    console.error('[DEBUG login catch]', err.message, err);
    var msg = err.message;
    if (msg === 'Failed to fetch' || err.name === 'TypeError') {
      msg = 'Серверот не е достапен. Проверете дали backend работи (uvicorn main:app --port 8000) и дали сте на http://localhost.';
    }
    showAuthError('login-error', msg);
  } finally {
    //submitBtn.disabled = false;
    if(submitBtn) submitBtn.disabled = false;
    //btnText.style.display = 'inline-block';
    if(btnText) btnText.style.display = 'inline-block';
    //btnLoading.style.display = 'none';
    if(btnLoading) btnLoading.style.display = 'none';
  }
}

// Регистрација
async function handleRegister(e) {
  e.preventDefault();
  
  const ime = document.getElementById('register-ime').value.trim();
  const prezime = document.getElementById('register-prezime').value.trim();
  const email = document.getElementById('register-email').value.trim();
  const password = document.getElementById('register-password').value;
  const passwordConfirm = document.getElementById('register-password-confirm').value;
  const submitBtn = e.target.querySelector('.btn-auth-submit');
  const btnText = submitBtn.querySelector('.btn-text');
  const btnLoading = submitBtn.querySelector('.btn-loading');
  
  // Валидација
  if (!ime || !prezime || !email || !password) {
    showAuthError('register-error', 'Пополнете ги сите задолжителни полиња');
    return;
  }
  
  if (password !== passwordConfirm) {
    showAuthError('register-error', 'Лозинките не се совпаѓаат');
    return;
  }
  
  if (password.length < 8) {
    showAuthError('register-error', 'Лозинката мора да има најмалку 8 карактери');
    return;
  }
  // За лекари: подразуеваната привремена лозинка не смее да се користи
  const DEFAULT_LOZINKA_LEKARI = 'Test123..';
  if (currentRole === 'lekar' && password.trim() === DEFAULT_LOZINKA_LEKARI) {
    showAuthError('register-error', 'Лозинката не смее да биде привремената/подразуеваната лозинка. Изберете друга лозинка според правилата (мин. 8 знаци, голема буква, број, интерпункциски знак).');
    return;
  }
  
  // Loading state
  submitBtn.disabled = true;
  btnText.style.display = 'none';
  btnLoading.style.display = 'inline-block';
  
  try {
    let endpoint, body;
    
    if (currentRole === 'lekar') {
      const specialty = document.getElementById('register-specialty').value.trim();
      if (!specialty) {
        throw new Error('Внесете специјалност');
      }
      
      endpoint = API_BASE + '/lekari/register';
      body = {
        ime,
        prezime,
        specialty,
        email,
        password
      };
    } else {
      const telefon = document.getElementById('register-telefon').value.trim();
      const embg = document.getElementById('register-embg').value.trim();
      
      endpoint = API_BASE + '/pacienti/register';
      body = {
        ime,
        prezime,
        email,
        telefon,
        embg,
        password
      };
    }
    
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    
    if (!res.ok) {
      const error = await res.json().catch(function() { return {}; });
      var detail = error.detail;
      if (Array.isArray(detail) && detail.length) detail = detail[0].msg || detail[0];
      if (typeof detail !== 'string') detail = error.message || 'Грешка при регистрација';
      throw new Error(detail);
    }
    
    alert('Успешно се регистриравте! Сега можете да се најавите.');
    showLogin();
    
  } catch (err) {
    showAuthError('register-error', err.message);
  } finally {
    submitBtn.disabled = false;
    btnText.style.display = 'inline-block';
    btnLoading.style.display = 'none';
  }
}

// ============================================================================
// ИНИЦИЈАЛИЗАЦИЈА
// ============================================================================

function setupAuth() {
  document.getElementById('auth-login-form')?.addEventListener('submit', handleLogin);
  document.getElementById('auth-register-form')?.addEventListener('submit', handleRegister);

  var forgotForm = document.getElementById('forgot-password-form');
  if (forgotForm) {
    forgotForm.addEventListener('submit', async function(e) {
      e.preventDefault();
      var email = (document.getElementById('forgot-email').value || '').trim().toLowerCase();
      if (!email) { showAuthError('login-error', 'Внесете е-пошта'); return; }
      var btn = document.getElementById('forgot-send-btn');
      var btnText = btn && btn.querySelector('.btn-text');
      var btnLoad = btn && btn.querySelector('.btn-loading');
      if (btnText) btnText.style.display = 'none';
      if (btnLoad) btnLoad.style.display = 'inline-block';
      var base = (typeof API_BASE !== 'undefined') ? API_BASE : 'http://localhost:8000';
      var url = currentRole === 'lekar' ? base + '/lekari/forgot-password' : base + '/pacienti/forgot-password';
      try {
        var res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: email }) });
        var data = await res.json().catch(function() { return {}; });
        if (btnText) btnText.style.display = 'inline-block';
        if (btnLoad) btnLoad.style.display = 'none';
        document.getElementById('reset-email').value = email;
        document.getElementById('forgot-code-msg').textContent = data.message || 'Погледнете го терминалот на серверот за кодот. Внесете го подолу.';
        document.getElementById('forgot-reset-block').style.display = 'block';
      } catch (err) {
        if (btnText) btnText.style.display = 'inline-block';
        if (btnLoad) btnLoad.style.display = 'none';
        showAuthError('login-error', 'Грешка при испраќање. Проверете дали backend-от работи.');
      }
    });
  }

  var resetForm = document.getElementById('reset-password-form');
  if (resetForm) {
    resetForm.addEventListener('submit', async function(e) {
      e.preventDefault();
      var email = (document.getElementById('reset-email').value || '').trim().toLowerCase();
      var token = (document.getElementById('reset-token').value || '').trim();
      var nova = (document.getElementById('reset-nova').value || '').trim();
      var confirm = (document.getElementById('reset-nova-confirm').value || '').trim();
      var errEl = document.getElementById('reset-error');
      if (!email || !token) { errEl.textContent = 'Внесете е-пошта и код.'; errEl.style.display = 'block'; return; }
      if (nova.length < 8) { errEl.textContent = 'Лозинката мора да има најмалку 8 карактери.'; errEl.style.display = 'block'; return; }
      if (nova !== confirm) { errEl.textContent = 'Лозинките не се совпаѓаат.'; errEl.style.display = 'block'; return; }
      errEl.style.display = 'none';
      var submitBtn = e.target && e.target.querySelector('.btn-auth-submit');
      var btnText = submitBtn && submitBtn.querySelector('.btn-text');
      var btnLoad = submitBtn && submitBtn.querySelector('.btn-loading');
      if (btnText) btnText.style.display = 'none';
      if (btnLoad) btnLoad.style.display = 'inline-block';
      var base = (typeof API_BASE !== 'undefined') ? API_BASE : 'http://localhost:8000';
      var url = currentRole === 'lekar' ? base + '/lekari/reset-password' : base + '/pacienti/reset-password';
      try {
        var res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: email, token: token, nova_lozinka: nova })
        });
        var data = await res.json().catch(function() { return {}; });
        if (btnText) btnText.style.display = 'inline-block';
        if (btnLoad) btnLoad.style.display = 'none';
        if (!res.ok) {
          errEl.textContent = data.detail || 'Грешка при промена на лозинка.';
          errEl.style.display = 'block';
          return;
        }
        alert(data.message || 'Лозинката е променета. Најавете се.');
        showLogin();
      } catch (err) {
        if (btnText) btnText.style.display = 'inline-block';
        if (btnLoad) btnLoad.style.display = 'none';
        errEl.textContent = 'Грешка при поврзување. Проверете дали backend-от работи.';
        errEl.style.display = 'block';
      }
    });
  }
  
  window.addEventListener('click', (e) => {
    const modal = document.getElementById('auth-modal');
    if (e.target === modal) closeAuthModal();
  });
}

// Замени го initialize() со овој дел:
// Во initialize() функцијата, замени ги повиците за најава со:
// setupAuth();

// ============================================================================
// ЗАЧУВАЈ ГИ ОВИЕ ФУНКЦИИ ЗА НАЗАД КОМПАТИБИЛНОСТ
// ============================================================================

// Овие функции ги користат старите копчиња во header
function openLekarLoginModal() {
  currentRole = 'lekar';
  switchRole('lekar');
  openLoginModal();
}

function openPacientLoginModal() {
  currentRole = 'pacient';
  switchRole('pacient');
  openLoginModal();
}

function showPacientRegister() {
  currentRole = 'pacient';
  switchRole('pacient');
  openRegisterModal();
}

function showLekarRegister() {
  currentRole = 'lekar';
  switchRole('lekar');
  openRegisterModal();
}

function closeLekarLoginModal() { closeAuthModal(); }
function closePacientLoginModal() { closeAuthModal(); }
function closeLekarRegisterModal() { closeAuthModal(); }
function closePacientRegisterModal() { closeAuthModal(); }
function showPacientLogin() { showLogin(); }
function showLekarLogin() { showLogin(); }

// Експортирај ги функциите глобално
window.openAuthModal = openLoginModal;
window.closeAuthModal = closeAuthModal;
window.switchRole = switchRole;
window.showLogin = showLogin;
window.showRegister = showRegister;
window.showForgotPassword = showForgotPassword;
window.openLekarLoginModal = openLekarLoginModal;
window.openLekarLoginModal = openLekarLoginModal;
window.closeLekarLoginModal = closeLekarLoginModal;

// DEBUG: Тестирај дали backend е достапен – отвори конзола (F12) и напиши: debugLekarConnection()
window.debugLekarConnection = async function() {
  try {
    var r = await fetch(API_BASE + '/lekari');
    console.log('[DEBUG] GET /lekari status:', r.status, r.ok ? 'OK' : 'FAIL');
    if (r.ok) {
      var lekari = await r.json();
      console.log('[DEBUG] Број на лекари:', lekari.length);
      console.log('[DEBUG] Први 5 лекари (име, презиме – за најава користи име.презиме на латиница):', lekari.slice(0, 5).map(function(l) { return (l.name || '') + ' ' + (l.surname || ''); }));
    }
  } catch (e) {
    console.error('[DEBUG] Грешка:', e.message, '| Дали backend работи? cd backend && uvicorn main:app --port 8000');
  }
};

window.openPacientLoginModal = openPacientLoginModal;
window.closePacientLoginModal = closePacientLoginModal;
window.showPacientRegister = showPacientRegister;
window.showLekarRegister = showLekarRegister;
window.showPacientLogin = showPacientLogin;
window.showLekarLogin = showLekarLogin;
window.closeLekarRegisterModal = closeLekarRegisterModal;
window.closePacientRegisterModal = closePacientRegisterModal;
// ============================================================================
// ЕКСПОРТИРАЊЕ НА ФУНКЦИИ ЗА ГЛОБАЛНА УПОТРЕБА
// ============================================================================

// Експортирање на функциите за глобална употреба
window.showAdminSubTab = showAdminSubTab;
window.openDezurstvoForm = openDezurstvoForm;
window.closeDezurstvoForm = closeDezurstvoForm;
window.editDezurstvo = editDezurstvo;
window.deleteDezurstvo = deleteDezurstvo;
window.openOglasForm = openOglasForm;
window.closeOglasForm = closeOglasForm;
window.editOglas = editOglas;
window.deleteOglas = deleteOglas;
window.loadNovosti = loadNovosti;
window.openNovostViewModal = openNovostViewModal;
window.closeNovostViewModal = closeNovostViewModal;
window.openNovostForm = openNovostForm;
window.closeNovostForm = closeNovostForm;
window.editNovost = editNovost;
window.deleteNovost = deleteNovost;

window.showLessDoctors = showLessDoctors;
window.showPacientLogin = showPacientLogin;
window.showPacientRegister = showPacientRegister;
window.showLekarRegister = showLekarRegister;
window.showLekarLogin = showLekarLogin;
window.closeLekarRegisterModal = closeLekarRegisterModal;