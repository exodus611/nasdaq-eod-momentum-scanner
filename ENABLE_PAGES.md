# Включение Pages - новый UI GitHub

## Прямая ссылка:
https://github.com/exodus611/nasdaq-eod-momentum-scanner/settings/pages

## Где искать:
Settings → слева найди раздел **Code and automation** → **Pages**

Если нет такого раздела:
- Причина: приватный репо + Free аккаунт = Pages не доступен. 
- Решение 1: Сделать репо публичным: Settings → General → Danger Zone → Change visibility → Make public → затем Pages → Source: GitHub Actions → Save
- Решение 2: Авто-включение через токен (см ниже)

## Авто-включение через токен (самый простой, работает даже если UI не видно):

1. Создай токен: https://github.com/settings/personal-access-tokens/fine-grained/new
   - Name: scan-trigger-pages
   - Repo: only exodus611/nasdaq-eod-momentum-scanner
   - Permissions: Actions Read and write, Pages Read and write
   - Generate → скопируй github_pat_...

2. Добавь секрет: https://github.com/exodus611/nasdaq-eod-momentum-scanner/settings/secrets/actions
   - New secret → Name: SCAN_TRIGGER_TOKEN, Value: токен → Add

3. Запусти workflow: https://github.com/exodus611/nasdaq-eod-momentum-scanner/actions/workflows/daily_scan.yml → Run workflow

Workflow сам включит Pages (configure-pages action с enablement:true).

## Альтернатива - деплой уже работает тут:
- LIVE PREVIEW порт 8000 в этом чате
- /deploy → панель управления
- Docker: docker-compose up -d
