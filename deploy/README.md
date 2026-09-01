# Deploy-ключ для связи с GitHub

SSH-деплой-ключ даёт этому workspace доступ на запись к репозиторию
`exodus611/nasdaq-eod-momentum-scanner` **без токенов**.

## Важно: среда песочницы

Песочница **не сохраняет** между перезапусками: папку `~/.ssh` и папку `.git`.
Поэтому:
- ключ хранится в **`deploy/keys/id_ed25519_algotrade`** (обычный файл в workspace — сохраняется);
- `deploy/push.sh` сам восстанавливает `.git` (init → fetch origin/main → reset) и подключает ключ.

## Как обновить дашборд на GitHub

```bash
python src/scan.py              # 1) свежий скан
python src/build_dashboard.py   # 2) свежий дашборд
./deploy/push.sh "сигнал 04.09" # 3) залить на GitHub
```

## Если ключ потерян (песочница пересоздана)

1. Сгенерировать новый ключ:
   ```bash
   mkdir -p deploy/keys && chmod 700 deploy/keys
   ssh-keygen -t ed25519 -N "" -f deploy/keys/id_ed25519_algotrade
   cat deploy/keys/id_ed25519_algotrade.pub
   ```
2. На GitHub: **Settings → Deploy keys → удалить старый → Add deploy key**,
   вставить новый публичный ключ, **Allow write access**.
3. Проверка: `./deploy/push.sh "test"`.

## Безопасность

- Приватный ключ в `deploy/keys/` — он в `.gitignore`, никогда не коммитится.
- Деплой-ключ привязан только к одному репозиторию.

## Восстановление ключа после перезапуска песочницы

Приватная часть deploy-ключа хранится в **двух** местах:
- `deploy/keys/agent_deploy` (этот каталог — в .gitignore, не пушится)
- `/home/user/deploy_key/agent_deploy` (корень workspace — переживает перезапуски)

Если после перезапуска ключа нет (push даёт `Permission denied (publickey)`):
```bash
cp /home/user/deploy_key/agent_deploy* deploy/keys/ 2>/dev/null || true
cat > ~/.ssh/config <<'CFG'
Host github.com
  IdentityFile /home/user/deploy_key/agent_deploy
  IdentitiesOnly yes
  StrictHostKeyChecking no
CFG
```
Если приватная часть потеряна полностью (в обоих местах) — сгенерировать новый ключ
(`ssh-keygen -t ed25519 -f /home/user/deploy_key/agent_deploy -N ""`), на GitHub удалить старый
deploy key и добавить новый с **Allow write access**. Текущий публичный ключ
(agent-push-3, fingerprint SHA256:umDutdQgk5/wtL7spw+8ZXpysEuhXUGV8i1VXpZ7tyw)
добавлен в Settings → Deploy keys 01.09.2026.
