#!/usr/bin/env bash
# Обновление репозитория на GitHub через SSH-деплой-ключ.
# Работает без токенов: ключ ~/.ssh/id_ed25519_algotrade уже добавлен
# в настройки репозитория (Settings -> Deploy keys, "Allow write access").
#
# Использование:
#   ./deploy/push.sh "комментарий к коммиту"     (push в main)
set -euo pipefail

REPO="exodus611/nasdaq-eod-momentum-scanner"
MSG="${1:-update}"

cd "$(dirname "$0")/.."

# git-конфиг не переживает перезапуски окружения — задаём на лету
git -c user.email="scanner@algotrade.local" -c user.name="EOD Scanner" add -A
git -c user.email="scanner@algotrade.local" -c user.name="EOD Scanner" \
    commit -m "$MSG" 2>/dev/null || echo "(нечего коммитить — пропускаю)"

# remote тоже настраиваем заново (приватный ключ остаётся в ~/.ssh)
git remote remove origin 2>/dev/null || true
git remote add origin "git@github.com:${REPO}.git"

echo "→ push в $REPO (SSH deploy key) ..."
GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519_algotrade -o IdentitiesOnly=yes" \
    git push -u origin main

echo ""
echo "✅ Репозиторий обновлён: https://github.com/${REPO}"
