# Поставување на сервер (Azure VM + Docker)

Сајтот е замислен така: **nginx на порт 80** го сервира статичкиот `frontend/`, а барањата кон API (`/lekari`, `/pacienti`, …) ги проследува кон **FastAPI на `backend:8000`** внатре во Docker мрежата. Јавно отвораш само **22** (SSH) и **80** (HTTP); **8000** не мора да биде отворен кон интернет.

## 1. Мрежа (Azure)

- **NSG (Network Security Group):** дозволи **Inbound** — **22** (SSH), **80** (HTTP). По потреба **3306** само ако директно пристапуваш до MySQL од надвор (обично не е потребно).
- Ако користиш **Azure Database for MySQL**: во **Firewall** на сервисот додади **јавната IP на VM** (или „Allow Azure services“ ако е поддржано), за backend да може да се поврзе.
- Во **`backend/.env`** на серверот: `DB_HOST=...mysql.database.azure.com`, **`DB_SSL=1`**, корисник и лозинка од Azure.

## 2. На VM: Docker

На Ubuntu пример:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME:-stable}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
# одјави се и најави повторно за групата docker
```

Проверка: `docker run --rm hello-world`

## 3. Код на серверот

**Опција A — git**

```bash
cd ~
git clone <твојот-repo-url> Klinicka_Bolnica_Stip_XML
cd Klinicka_Bolnica_Stip_XML
```

**Опција B — копирање од лаптоп** (од твојот компјутер):

```bash
rsync -avz --exclude '.git' --exclude '__pycache__' \
  ./Klinicka_Bolnica_Stip_XML/ user@ТВОЈА_VM_IP:~/Klinicka_Bolnica_Stip_XML/
```

## 4. `backend/.env` на серверот

На VM **нема** да го комитуваш `.env`. Копирај го рачно:

```bash
# од твојот лаптоп:
scp backend/.env user@ТВОЈА_VM_IP:~/Klinicka_Bolnica_Stip_XML/backend/.env
```

Или на сервер: `cp backend/.env.example backend/.env` и уреди го (`nano backend/.env`).

- За **MySQL во Docker** на истата VM: `DB_HOST=mysql`, `MYSQL_ROOT_PASSWORD`, `DB_PASSWORD`, итн. (види `backend/.env.example`).
- За **само Azure MySQL:** `DB_HOST` кон Azure, **`DB_SSL=1`**; не мора `MYSQL_ROOT_PASSWORD` за compose.

## 5. Стартување / ажурирање

Од **коренот** на проектот на VM:

```bash
chmod +x scripts/docker-up.sh scripts/deploy-vm.sh

# Само backend + nginx (база = Azure MySQL или надворешна)
./scripts/deploy-vm.sh azure-db

# Или цел стек со MySQL во Docker на VM
./scripts/deploy-vm.sh local
```

`deploy-vm.sh` прави `git pull` (ако има `.git`), па `docker compose build` и стартување според режимот.

## 6. Проверка

На VM:

```bash
curl -sS http://127.0.0.1/lekari | head -c 300
docker compose logs -f backend
```

Од твојот прелистувач: `http://ТВОЈА_VM_IP/` — почетна; API преку nginx: `http://ТВОЈА_VM_IP/lekari`.

## 7. Чести проблеми

| Симптом | Што да провериш |
|--------|------------------|
| Празна страница / 502 | `docker compose ps` — дали `backend` и `frontend` се `Up`. `docker compose logs backend`. |
| API 500 | Конекција до база: `DB_HOST`, лозинка, **SSL за Azure**, firewall на MySQL кон VM IP. |
| Табели недостасуваат | Увези `backend/schema.sql` (или твојот dump) во базата. |

## 8. По промена во код

На VM:

```bash
cd ~/Klinicka_Bolnica_Stip_XML
git pull
./scripts/deploy-vm.sh azure-db
```

(или `local` ако користиш mysql контејнер.)
