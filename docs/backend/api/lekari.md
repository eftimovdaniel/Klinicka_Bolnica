# API — Лекари

Сите endpoints за **лекари** живеат под префиксот `/lekari` и се дефинирани во `backend/routers/lekari.py`. Покриваат листа на лекари, најава, регистрација, лозинки, термини и дежурства.

> **Интерактивно тестирање:** под секој endpoint има вграден **OpenAPI блок** со копче **„Test it"** (powered by Scalar). Пополни ги параметрите/телото и испрати го барањето директно од документацијата кон живиот сервер (`klinicka-bolnica-stip2026.onrender.com`).

## Содржина

* [1. Преглед](#1-pregled)
* [2. Корисничко име (име.презиме)](#2-username)
* [3. GET `/lekari`](#3-lista)
* [4. POST `/lekari/login`](#4-login)
* [5. POST `/lekari/register`](#5-register)
* [6. PATCH `/lekari/promeni-lozinka`](#6-lozinka)
* [7. POST `/lekari/forgot-password`](#7-forgot)
* [8. POST `/lekari/reset-password`](#8-reset)
* [9. GET `/lekari/termini`](#9-termini)
* [10. GET `/lekari/{doctor_id}/dezurstva`](#10-dezurstva)

> Поврзани: [Конвенции](conventions.md) · [Автентикација](authentication.md) ·
> [Пациенти](pacienti.md) · [Термини](termini.md) ·
> [База — Doctors](../the_database.md#tab-doctors)

---

## 1. Преглед <a id="1-pregled"></a>

| Метод | Патека | Намена |
|-------|--------|--------|
| `GET` | `/lekari` | Сите лекари (опц. филтер по специјалност) |
| `POST` | `/lekari/login` | Најава (враќа и термини) |
| `POST` | `/lekari/register` | Регистрација на лекар |
| `PATCH` | `/lekari/promeni-lozinka` | Смена на лозинка (најавен лекар) |
| `POST` | `/lekari/forgot-password` | Барање код за ресет |
| `POST` | `/lekari/reset-password` | Нова лозинка со код |
| `GET` | `/lekari/termini` | Термини на лекар по е-пошта |
| `GET` | `/lekari/{doctor_id}/dezurstva` | Распоред на дежурства |

---

## 2. Корисничко име (име.презиме) <a id="2-username"></a>

Лекарите **немаат** посебно корисничко име во базата — тоа се пресметува од името и презимето, транслитерирани на **латиница**, споени со точка:

```
Ана Стојановска → ana.stojanovska
```

При најава, backend-от ги зема сите лекари, го транслитерира секое `име.презиме` и го споредува со внесеното. Има и **флексибилно совпаѓање** за различни транслитерации (на пр. `sh`↔`s`, `zh`↔`z`, `ch`↔`c`) и мали печатни грешки во презимето. Логиката е во `routers/utils.py` (`transliterate_mk_to_lat`).

> Привремената лозинка за сите примерни лекари е `Test123..`. По најава со неа, `must_change_password` е `true` и лекарот мора да ја смени.

---

## 3. GET `/lekari` <a id="3-lista"></a>

**Враќа листа на сите лекари.** Опционално филтрира по специјалност.

**Query параметри:**
- `specijalnost` (опц.) — точно име на специјалност (на пр. `Кардиологија`)

**Успешен одговор (200):**

```json
[
  { "doctor_ID": 28, "name": "Александар", "surname": "Серафимов", "specijalnost": "Кардиологија", "email": "aleksandarserafimov@KBstip.com" }
]
```

Лекарите без специјалност се враќаат со празно `specijalnost` (frontend прикажува „Н/П").

{% openapi src="https://klinicka-bolnica-stip2026.onrender.com/openapi.json" path="/lekari" method="get" %}
https://klinicka-bolnica-stip2026.onrender.com/openapi.json
{% endopenapi %}

---

## 4. POST `/lekari/login` <a id="4-login"></a>

**Најава на лекар** со корисничко име (`име.презиме`) и лозинка. Покрај податоците за лекарот, веднаш ги враќа и неговите **термини** (за да не треба втор повик).

**Тело (JSON):**

```json
{
  "username": "ana.stojanovska",
  "password": "Test123.."
}
```

**Успешен одговор (200):**

```json
{
  "doctor": {
    "doctor_ID": 2,
    "name": "Ана",
    "surname": "Стојановска",
    "email": "ana.stojanovska@kbstip.mk",
    "specijalnost": "Кардиологија"
  },
  "termini": [
    {
      "termin_ID": 5,
      "ime_pacient": "Иван Ивановски",
      "datum_pregled": "2026-06-20",
      "vreme_pregled": "10:00",
      "email_pacient": "ivan@example.com",
      "telefon_pacient": "070123456",
      "dijagnoza": "",
      "terapija": "",
      "status_pregled": "закажан"
    }
  ],
  "must_change_password": true
}
```

- **`must_change_password`** — `true` само ако тековната лозинка е сè уште привремената `Test123..`.
- Терминаите се сортирани: прво `закажан`, па по датум/време; **откажаните** се исфрлени.

**Можни грешки:** `400` (празно поле) · `401` (невалидно име/лозинка) · `403` (лекарот нема поставено лозинка — треба регистрација) · `500`

{% openapi src="https://klinicka-bolnica-stip2026.onrender.com/openapi.json" path="/lekari/login" method="post" %}
https://klinicka-bolnica-stip2026.onrender.com/openapi.json
{% endopenapi %}

---

## 5. POST `/lekari/register` <a id="5-register"></a>

**Регистрација на лекар** (поставување профил и лозинка).

**Тело (JSON):**

```json
{
  "name": "Тест",
  "prezime": "Лекар",
  "specialty": "Кардиологија",
  "email": "test.lekar@kbstip.mk",
  "password": "Nova123.."
}
```

**Правила за лозинка** (`_validna_lozinka_lekar`):
- минимум **8** карактери
- барем една **голема буква**
- барем еден **број**
- барем еден **интерпункциски знак**
- **не смее** да биде привремената `Test123..`

**Можни грешки:** `400` (невалидни полиња/лозинка, зафатена е-пошта) · `500`

{% openapi src="https://klinicka-bolnica-stip2026.onrender.com/openapi.json" path="/lekari/register" method="post" %}
https://klinicka-bolnica-stip2026.onrender.com/openapi.json
{% endopenapi %}

---

## 6. PATCH `/lekari/promeni-lozinka` <a id="6-lozinka"></a>

**Смена на лозинка** за најавен лекар. Бара ја **тековната** лозинка за верификација.

**Тело (JSON):**

```json
{
  "doctor_id": 2,
  "trenutna_lozinka": "Test123..",
  "nova_lozinka": "Nova123.."
}
```

Новата лозинка ги почитува истите правила како кај регистрација. По успех, `must_change_password` се поставува на `0`.

**Можни грешки:** `400` (недостасува `doctor_id`, невалидна нова лозинка) · `401` (погрешна тековна лозинка) · `403` (нема поставено лозинка) · `404` · `500`

{% openapi src="https://klinicka-bolnica-stip2026.onrender.com/openapi.json" path="/lekari/promeni-lozinka" method="patch" %}
https://klinicka-bolnica-stip2026.onrender.com/openapi.json
{% endopenapi %}

---

## 7. POST `/lekari/forgot-password` <a id="7-forgot"></a>

**Барање код за ресет** на лозинка. Кодот (валиден **1 час**) се зачувува во `password_reset_tokens` со `user_type = 'lekar'` и се печати во терминалот/логовите.

**Тело (JSON):**

```json
{ "email": "ana.stojanovska@kbstip.mk" }
```

Одговорот е секогаш иста порака (без откривање дали е-поштата постои).

**Можни грешки:** `400` (невалидна е-пошта) · `500`

{% openapi src="https://klinicka-bolnica-stip2026.onrender.com/openapi.json" path="/lekari/forgot-password" method="post" %}
https://klinicka-bolnica-stip2026.onrender.com/openapi.json
{% endopenapi %}

---

## 8. POST `/lekari/reset-password` <a id="8-reset"></a>

**Нова лозинка** со код (без најава).

**Тело (JSON):**

```json
{
  "email": "ana.stojanovska@kbstip.mk",
  "token": "код_од_терминал_или_лог",
  "nova_lozinka": "Nova123.."
}
```

Новата лозинка ги почитува правилата за лекарска лозинка. По успех кодот се брише и `must_change_password = 0`.

**Можни грешки:** `400` (невалиден код или лозинка) · `404` · `500`

{% openapi src="https://klinicka-bolnica-stip2026.onrender.com/openapi.json" path="/lekari/reset-password" method="post" %}
https://klinicka-bolnica-stip2026.onrender.com/openapi.json
{% endopenapi %}

---

## 9. GET `/lekari/termini` <a id="9-termini"></a>

**Термини на лекар** пронајден по **е-пошта**. Враќа податоци за лекарот + листа термини (без откажани).

**Query параметри:**
- `email` (задолжителен)

**Успешен одговор (200):**

```json
{
  "doctor": {
    "doctor_ID": 2,
    "name": "Ана",
    "surname": "Стојановска",
    "email": "ana.stojanovska@kbstip.mk",
    "specijalnost": "Кардиологија"
  },
  "termini": [ "..." ]
}
```

**Можни грешки:** `400` (нема е-пошта) · `404` (нема лекар со таа е-пошта) · `500`

{% openapi src="https://klinicka-bolnica-stip2026.onrender.com/openapi.json" path="/lekari/termini" method="get" %}
https://klinicka-bolnica-stip2026.onrender.com/openapi.json
{% endopenapi %}

---

## 10. GET `/lekari/{doctor_id}/dezurstva` <a id="10-dezurstva"></a>

**Распоред на дежурства** за лекар. Прво проверува дали има дежурства во базата (`Dezurstva`); ако нема, користи **динамичко пресметување** (fallback врз основа на име и специјалност).

**Path параметри:**
- `doctor_id` (задолжителен)

**Успешен одговор (200):**

```json
[
  {
    "datum": "2026-06-20",
    "den": "20",
    "oddel": "Кардиологија",
    "vreme_od": "08:00",
    "vreme_do": "20:00",
    "napomena": null
  }
]
```

**Можни грешки:** `404` (лекар не постои) · `500`

{% openapi src="https://klinicka-bolnica-stip2026.onrender.com/openapi.json" path="/lekari/{doctor_id}/dezurstva" method="get" %}
https://klinicka-bolnica-stip2026.onrender.com/openapi.json
{% endopenapi %}

---

Следно: [Термини](termini.md) · [Автентикација](authentication.md) ·
[Пациенти](pacienti.md)
