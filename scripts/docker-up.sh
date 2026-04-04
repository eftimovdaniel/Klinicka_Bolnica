#!/usr/bin/env bash
# Стартување на стекот со Docker Compose од коренот на проектот.
#
# Употреба (од папката Klinicka_Bolnica_Stip_XML):
#   chmod +x scripts/docker-up.sh
#   ./scripts/docker-up.sh local          # mysql + backend + frontend (локална база во Docker)
#   ./scripts/docker-up.sh azure-db       # само backend + frontend (DB_HOST = Azure или надворешен MySQL)
#
# Пред тоа: копирај backend/.env.example → backend/.env и пополни ги променливите.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-}"

usage() {
  echo "Употреба: $0 local | azure-db"
  echo "  local     — стартува mysql, па backend и frontend (DB_HOST=mysql во backend/.env)"
  echo "  azure-db  — само backend и frontend (без mysql контејнер; DB_HOST во .env кон надворешна база)"
  exit 1
}

[[ -f backend/.env ]] || { echo "Нема backend/.env — копирај од backend/.env.example и пополни."; exit 1; }

case "$MODE" in
  local)
    echo "=== build ==="
    docker compose build
    echo "=== стартување mysql ==="
    docker compose up -d mysql
    echo "Чекам MySQL (~25s)..."
    sleep 25
    echo "=== стартување backend + frontend ==="
    docker compose up -d backend frontend
    ;;
  azure-db)
    echo "=== build ==="
    docker compose build
    echo "=== стартување backend + frontend (без mysql) ==="
    docker compose up -d backend frontend
    ;;
  *)
    usage
    ;;
esac

echo ""
echo "=== статус ==="
docker compose ps

echo ""
echo "=== проверка (треба JSON листа на лекари, не грешка) ==="
echo "curl -s http://127.0.0.1:8000/lekari | head -c 400"
curl -sS http://127.0.0.1:8000/lekari | head -c 400 || true
echo ""
echo ""
echo "curl -s http://127.0.0.1/lekari | head -c 400"
curl -sS http://127.0.0.1/lekari | head -c 400 || true
echo ""
echo ""
echo "Документација на API: http://127.0.0.1:8000/docs"
echo "Сајт преку nginx:     http://127.0.0.1/"
echo ""
echo "Логови:  docker compose logs -f backend"
echo "Стоп:    docker compose down"
if [[ "$MODE" == "local" ]]; then
  echo ""
  echo "Ако /lekari дава грешка — увези schema (еднаш):"
  echo "  docker compose exec -T mysql mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" \"\$DB_NAME\" < backend/schema.sql"
  echo "(изврши го од корен на проектот со вчитан backend/.env:  set -a && source backend/.env && set +a)"
fi
