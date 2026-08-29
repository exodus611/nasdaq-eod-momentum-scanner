#!/usr/bin/env bash
# Публикация приватного репозитория nasdaq-eod-momentum-scanner на GitHub
# Требование: fine-grained PAT с Account permissions -> Administration: Read and write
# Использование:  ./publish.sh <GITHUB_PAT_TOKEN>
set -euo pipefail

TOKEN="${1:-}"
if [[ -z "$TOKEN" ]]; then
  echo "Ошибка: передай токен аргументом:  ./publish.sh ghp_XXXX"
  exit 1
fi

REPO="nasdaq-eod-momentum-scanner"
cd "$(dirname "$0")"

echo "→ Авторизуюсь в gh ..."
echo "$TOKEN" | gh auth login --with-token
gh auth status

echo "→ Создаю приватный репозиторий ${REPO} и пушу ..."
gh repo create "$REPO" --private --source . --remote origin --push

echo ""
echo "✅ Готово!"
echo "   Репозиторий: https://github.com/$(gh api user -q .login)/${REPO}"
echo "   Дашборд:     https://github.com/$(gh api user -q .login)/${REPO}/blob/main/output/dashboard.html"
echo ""
echo "⚠️ Токен после публикации лучше отозвать: github.com/settings/tokens"
