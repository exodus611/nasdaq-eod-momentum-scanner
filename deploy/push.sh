#!/usr/bin/env bash
# Публикация изменений в GitHub через SSH-деплой-ключ.
# Ключ хранится в deploy/keys/ (переживает перезапуски песочницы; ~/.ssh и .git — нет).
# Скрипт сам восстанавливает git-репозиторий, если среда его сбросила.
set -euo pipefail

REPO="exodus611/nasdaq-eod-momentum-scanner"
KEY="$(dirname "$0")/keys/id_ed25519_algotrade"
MSG="${1:-update}"

cd "$(dirname "$0")/.."

SSH_CMD="ssh -i $KEY -o IdentitiesOnly=yes"

# --- восстановить git-репозиторий, если среда его сбросила ---
if [ ! -d .git ]; then
  echo "→ .git отсутствует — пересоздаю и подтягиваю origin/main ..."
  git init -b main -q
  git remote add origin "git@github.com:${REPO}.git"
  GIT_SSH_COMMAND="$SSH_CMD" git fetch origin main -q
  GIT_SSH_COMMAND="$SSH_CMD" git reset --hard origin/main -q
fi

git -c user.email="scanner@algotrade.local" -c user.name="EOD Scanner" add -A
git -c user.email="scanner@algotrade.local" -c user.name="EOD Scanner" \
    commit -m "$MSG" 2>/dev/null || echo "(нечего коммитить — пропускаю)"

echo "→ push в $REPO (SSH deploy key) ..."
GIT_SSH_COMMAND="$SSH_CMD" git push origin main

echo ""
echo "✅ Репозиторий обновлён: https://github.com/${REPO}"
