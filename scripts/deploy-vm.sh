#!/usr/bin/env bash
# Скрипта за на VM: git pull (ако има repo) + build + стартување на стекот.
# Употреба од корен на проектот на серверот:
#   chmod +x scripts/deploy-vm.sh
#   ./scripts/deploy-vm.sh azure-db    # без mysql контејнер (Azure/надворешна MySQL)
#   ./scripts/deploy-vm.sh local       # mysql + backend + frontend на истата VM

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-azure-db}"

if [[ -d .git ]] && command -v git >/dev/null 2>&1; then
  echo "=== git pull ==="
  git pull --rebase || git pull || true
fi

exec "$ROOT/scripts/docker-up.sh" "$MODE"
