# Деплой — уже сделан

Репозиторий: https://github.com/exodus611/nasdaq-eod-momentum-scanner  
Дашборд: https://exodus611.github.io/nasdaq-eod-momentum-scanner/  
Прежний сканер: ветка `legacy-scanner` (история сохранена полностью).

## Как это работает

- `.github/workflows/daily.yml` — 10 cron-слотов каждые 15 минут с 20:17 до 23:02 UTC (16:17–19:02 ET летом). GitHub задерживает cron на 5 мин – 2 ч; первый слот, реально стартовавший после 16:15 ET, делает скан, остальные выходят за секунды (день уже есть в `state/daily_log.csv`). Вход всё равно завтра по открытию, поэтому задержка не критична.
- Каждый запуск: скан → `state/journal.csv`, `state/scans/<дата>.json`, `state/daily_log.csv` → `docs/index.html` + блок в README → коммит `scan: …` встроенным `GITHUB_TOKEN` → публикация `docs/` в GitHub Pages.
- Секреты не нужны. Telegram, брокер, ордера — отсутствуют.
- По понедельникам обновляется список акций NASDAQ (`data/universe_nasdaq.csv`).

## Ручной запуск

Actions → «Dip-Buyer daily scan» → Run workflow:
- `run` — обычный дневной скан (если рынок ещё не закрыт, обрабатывается последняя завершённая сессия; частичный бар дня не используется никогда);
- `run` + `asof=YYYY-MM-DD` — реплей прошлой сессии (помечается `replay`);
- `test` — проверка данных и пересборка дашборда;
- `rebuild-page` — пересобрать дашборд из `state/`.

## Если что-то не так

- Workflow упал на `git push` → Settings → Actions → General → Workflow permissions → «Read and write permissions».
- Дашборд не обновляется → Settings → Pages → Source должен быть **GitHub Actions**.
- На дашборде «нет дневного бара» → праздник или задержка Yahoo; перезапустить `run` позже.

## Настройки (необязательно)

Settings → Secrets and variables → Actions → **Variables**: `CAPITAL` (100000), `PER_NAME` (0.25), `MAX_POS` (4), `MAX_NEW` (2), `RSI_THR` (10), `EXIT_SMA` (10), `MAX_HOLD` (20), `PAGES_URL`.

## Deploy key

Ключ `dip-buyer deploy` использовался только для первоначальной заливки кода. Для ежедневной работы он не нужен — его можно удалить: Settings → Deploy keys → Delete.
