# Docker – хостирање и решавање на проблеми

## Проблем: HTTP 500 и „Серверот не одговара“

Кога добиваш **HTTP грешка 500** на услуги/лекари или **„Серверот не одговара“**, најчесто причината е **конекцијата со базата**.

### 1. DB_HOST во Docker – најчеста грешка

Во Docker контејнер, **`localhost` не е иста машина како MySQL**. Backend-от мора да се поврзе со базата преку **име на сервисот** или **IP на host-от**.

#### Ако MySQL е во Docker (docker-compose):

Во `backend/.env` или во `docker-compose.yml`:

```env
DB_HOST=mysql
DB_USER=root
DB_PASSWORD=твоја_лозинка
DB_NAME=Klinicka_Bolnica_Stip
```

`mysql` е името на сервисот во docker-compose (исто како `services: mysql:`).

#### Ако MySQL е на host машината (надвор од Docker):

- **Mac/Windows:** `DB_HOST=host.docker.internal`
- **Linux:** `DB_HOST=172.17.0.1` (или IP на host-от)

#### Ако користиш Azure MySQL:

```env
DB_HOST=tvoja-server.mysql.database.azure.com
DB_USER=tvoja_korisnicko@tvoja-server
DB_PASSWORD=...
DB_SSL=1
```

### 2. Проверка на конекцијата

Отвори во прелистувач:

```
http://20.199.137.96:8000/debug-db
```

- Ако видиш `"connection": "OK"` → базата работи.
- Ако видиш грешка → провери `DB_HOST`, `DB_USER`, `DB_PASSWORD` во `.env`.

### 3. Порти – backend мора да е достапен

Frontend-от бара API на **порт 8000**. Backend-от мора да е достапен:

```yaml
# docker-compose.yml
backend:
  ports:
    - "8000:8000"
```

Ако користиш само backend (без nginx), пристапуваш на:
- **Страница:** `http://20.199.137.96:8000`
- **API:** `http://20.199.137.96:8000/lekari`, `/uslugi`, итн.

### 4. Нова IP адреса

Кога се менува IP (на пр. `20.199.137.96`), **ништо не треба да се менува во кодот**. Frontend автоматски го користи `window.location.hostname`, па API_BASE ќе биде `http://20.199.137.96:8000`.

### 5. Кратка процедура за Docker

1. Во `backend/.env` постави `DB_HOST` според тоа каде е MySQL (види погоре).
2. Стартувај: `docker-compose up -d`
3. Провери: `http://ТВОЈ_IP:8000/debug-db`
4. Отвори апликација:
   - **Порт 80:** `http://ТВОЈ_IP` (frontend преку nginx)
   - **Порт 8000:** `http://ТВОЈ_IP:8000` (само API – frontend треба да е на друг начин)

### 6. Логови за дебаг

```bash
docker-compose logs -f backend
```

Ќе ги видиш грешките од базата (на пр. „Не може да се поврзе со базата“).
