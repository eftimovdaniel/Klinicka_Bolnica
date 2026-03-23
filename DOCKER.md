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

---

## VM со постоечки MySQL контејнер (klinicka_bolnica_db_1)

Ако веќе имаш MySQL контејнер со податоци и добиваш:
- `Can't connect to MySQL server on 'localhost:3306'`
- `Bind for 0.0.0.0:3306 failed: port is already allocated`

### Решение

1. **НЕ користи** `--profile with-db` – не стартувај нов MySQL (порт 3306 е зафатен).

2. **Креирај `backend/.env`** со:
   ```env
   DB_HOST=klinicka_bolnica_db_1
   DB_USER=root
   DB_PASSWORD=rootpassword
   DB_NAME=Klinicka_Bolnica_Stip
   ```

3. **Стартувај само backend и frontend:**
   ```bash
   docker-compose up -d --build
   ```
   (без `--profile with-db`)

4. Backend ќе се поврзе со постоечкиот db контејнер преку името `klinicka_bolnica_db_1`.

### Adminer – пристап до базата преку прелистувач

Ако Workbench не работи (SSH грешки), користи **Adminer** – веб-интерфејс за MySQL.

1. На VM, во папката на проектот:
   ```bash
   # Најди ја мрежата на db контејнерот:
   docker inspect klinicka_bolnica_db_1 --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}'

   # Стартувај Adminer (замени NETWORK_NAME со резултатот од горната команда):
   docker run -d --name adminer --network NETWORK_NAME -p 8080:8080 adminer
   ```
   Пример: ако мрежата е `klinicka_bolnica_default`:
   ```bash
   docker run -d --name adminer --network klinicka_bolnica_default -p 8080:8080 adminer
   ```

2. Отвори во прелистувач: **http://20.199.137.96:8080**

3. Најава:
   - **System:** MySQL
   - **Server:** `klinicka_bolnica_db_1`
   - **Username:** `root`
   - **Password:** `rootpassword`
   - **Database:** `Klinicka_Bolnica_Stip`

4. Кликни **Login** – ќе видиш табели и можеш да внесуваш/уредуваш податоци.

**Azure VM:** Отвори порт 8080 во Network Security Group (NSG):
- Azure Portal → VM → Networking → Add inbound port rule
- Port: 8080, Protocol: TCP, Source: Any (или твоја IP за безбедност)

---

### Ако порт 3306 е сè уште зафатен

Стопирај го стариот db контејнер пред да стартуваш нов compose:
```bash
docker stop klinicka_bolnica_db_1
docker-compose up -d
```
Потоа повторно стартувај го db (ако е потребен):
```bash
docker start klinicka_bolnica_db_1
```
