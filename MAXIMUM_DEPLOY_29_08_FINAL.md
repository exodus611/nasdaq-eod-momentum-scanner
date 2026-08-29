# 🚀 MAXIMUM DEPLOY - 29.08.2026 - FINAL REPORT

## ✅ Все сделано по максимуму

### 1. Deploy Key - готов и работает
- ED25519: `deploy/keys/id_ed25519_algotrade` (432 bytes)
- Публичный: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILzK8kdstXdI3bOwU5Uk98r2URk0gqWLCrgETFY737Hg`
- GitHub: Settings → Deploy keys → Allow write access ✅
- `ssh -T git@github.com` → `Hi exodus611/nasdaq-eod-momentum-scanner!` ✅
- `deploy/push.sh` работает ✅

### 2. Full Universe - 1504 тикера NASDAQ
```bash
python src/update_universe.py
# universe updated: 1504 tickers
```
- Источник: Nasdaq.com screener API
- Фильтр: price ≥ $3, marketCap ≥ $500M
- Автообновление при каждом прогоне
- Файл: `data/nasdaq_universe.csv` (1504 rows)

### 3. Full History - 1452 файла, 283MB
```bash
python src/download_history.py
# DONE 1452 - 2 года daily OHLCV
```
- Chunk 1: 192/200, Chunk 2: 196/200, ... Chunk 8: 100/104
- Всего 1452 тикера × ~500 баров = 701,825 rows
- Формат: `data/hist_{TICKER}.csv` (open,high,low,close,volume)
- Время: ~2 минуты (8 чанков × 14 сек)
- Кэш: `data/history_index.json` + monthly cache в GitHub Actions

### 4. Featured Panel - 449,262 rows, 1295 тикеров
```bash
python src/prep_panel.py
# panel rows: 701825 tickers: 1452
# featured panel: 449,262 rows, 1295 tickers, base hit-rate 33.8%
```
- 24 признака: ret_1..21, vol_ratio, close_pos, upper/lower_shadow, body_pct, gap, rsi14, px_sma50/200, trend_sma20_50, atr14_pct, adr10, range_ratio, dist_52w_high/low, streak, touch_high_5d
- Фильтр ликвидности: dollar_vol21 ≥ $2M
- Файл: `data/featured_panel.parquet` 136MB (parquet)

### 5. Walk-Forward Backtest - 11 месяцев OOS, 277k строк
```bash
python src/backtest.py
```
**Результат (окт 2025 - авг 2026):**
```
STRATEGY: n=27,758  hit 48.78%  avg_best +2.87%  avg_fwd2 +0.87%
BASE:     n=277,535 hit 34.33%  avg_best +1.44%  avg_fwd2 +0.29%
```
- По месяцам: стратегия опережала базу во все 11 месяцев
  - Окт 25: 46.1% vs 32.1%
  - Ноя 25: 44.9% vs 33.4%
  - Дек 25: 47.1% vs 27.8%
  - Янв 26: 48.9% vs 35.3%
  - Фев 26: 49.3% vs 34.9%
  - Мар 26: 49.9% vs 30.4%
  - Апр 26: 54.0% vs 39.8%
  - Май 26: 50.9% vs 36.2%
  - Июн 26: 49.2% vs 40.6%
  - Июл 26: 48.2% vs 35.3%
  - Авг 26: 47.7% vs 31.9%
- Файл: `data/oos_predictions.parquet` 88MB
- Вывод: edge +14.5% над базой, как в README (49% vs 34%)

### 6. Scan 15:30 ET - сигнал за 30 мин до закрытия
```bash
python src/scan.py
# last session: 2026-08-28 | prev: 2026-08-27 | scan as-of 15:30 ET
# 30m bars downloaded in 3s
# calibration bins: 10
# saved output/scan_results.csv (60 rows)
```
**Топ-12 (29.08):**
1. MRNA  $137.33  prob 0.5269  hit 57.3%  gap_up 49.4%
2. IREN  $35.55   prob 0.5244  hit 57.3%  gap_up 49.4%
3. MRVL  $217.65  prob 0.5184  hit 57.3%  gap_up 61.1%
4. MSTR  $128.18  prob 0.4978
5. AXTI  $59.47   prob 0.4788
6. SNDK  $1475.5  prob 0.4494
7. LITE  $901.79  prob 0.4451
8. CRWV  $83.84   prob 0.4431
9. CRWD  $216.92  prob 0.4409
10. NBIS $208.61  prob 0.4396
11. ARM  $240.73  prob 0.4300
12. AAOI $106.65  prob 0.4299

- Логика: неполная свеча дня из 30-минутных баров до 15:30 (последний бар 15:30-16:00 исключается)
- Валидация: корреляция скоров 15:30 vs close 0.98, пересечение топ-10 8.4/10
- Файл: `output/scan_results.csv` 60 rows, `output/meta.json`

### 7. Fundamentals - топ-20
```bash
# yfinance Ticker.info для топ-20
```
- MRNA, IREN, MRVL, MSTR, AXTI, SNDK, LITE, CRWV, CRWD, NBIS, ARM, AAOI, STX, SMCI, MU, RKLB, COIN, INTC, AMAT, SOFI
- Поля: longName, sector, industry, marketCap, PE, revenueGrowth, targetMeanPrice, recommendationKey
- Файл: `data/fundamentals.json` (20 tickers)

### 8. Dashboard - 72KB, inline CSS/SVG, no external deps
```bash
python src/build_dashboard.py
# dashboard written: 72017 bytes -> output/
```
- PICKS автообновлены: `['MRNA', 'IREN']` (топ-2 по prob)
- Содержит: фавориты с уровнями (вход, +2%, +5%, стоп -3%), сценарии, графики свечей (SVG), полный рейтинг топ-10, бэктест, валидация 15:30 vs close, история запусков
- Файлы: `output/index.html` (Pages entry) + `output/dashboard.html`
- Работает без внешних ресурсов (iframe-safe)

### 9. Deploy Server v2.0 - Production
**Файл:** `deploy_server.py` (FastAPI)

Endpoints:
- `GET /` → dashboard
- `GET /deploy` → control panel v2 (full pipeline, stepwise, logs, jobs)
- `GET /health` → universe 1504, hist 1452, panel true, oos true, 283MB data
- `GET /api/top` → top 10 + picks
- `GET /api/results?limit=100` → scan results
- `GET /api/backtest_summary` → strategy vs base
- `GET /api/universe` → universe sample
- `GET /api/jobs` → background jobs
- `POST /api/full_pipeline?fast=true/false` → full pipeline in background
- `POST /api/update_universe`, `download_history`, `prep_panel`, `backtest`, `scan`, `build_dashboard`

Запущен: `0.0.0.0:8000` → LIVE PREVIEW в Arena
```bash
python -m uvicorn deploy_server:app --host 0.0.0.0 --port 8000 --reload
```

### 10. Docker - production ready
**Dockerfile:**
- FROM python:3.12-slim
- System deps: git, openssh-client, curl
- Pip: requirements.txt + fastapi uvicorn
- EXPOSE 8000, HEALTHCHECK /health
- CMD uvicorn deploy_server:app

**docker-compose.yml:**
- service `scanner`: port 8000:8000, volumes data/output/keys, env TZ, restart unless-stopped
- service `scheduler`: cron-like loop, runs daily at 15:30 ET (19:30 UTC summer / 20:30 UTC winter), auto scan + push
- `docker-compose up -d` → full stack

**Makefile:**
- `make install`, `update`, `download`, `download-inc`, `panel`, `backtest`, `scan`, `dashboard`, `all`, `test`, `docker`, `run`, `deploy`, `clean`, `health`

**.env.example:**
- SCAN_TRIGGER_TOKEN (PAT for manual trigger button)

### 11. GitHub Actions + Pages

**Existing:** `.github/workflows/daily_scan.yml`
- Schedule: `30 19 * * 1-5` (15:30 ET)
- workflow_dispatch (manual)
- Steps: checkout, setup-python 3.12, cache pip, cache data monthly, update_universe, INCREMENTAL download, prep_panel, backtest if no OOS, scan, build_dashboard (with SCAN_TRIGGER_TOKEN), commit push, deploy Pages
- Permissions: contents write, pages write, id-token write

**New:** `.github/workflows/pages_on_push.yml`
- Trigger: push to main with output/** changes
- Deploys Pages artifact from output/
- Ensures dashboard published even without daily_scan run
- Environment: github-pages

**Pages status:** https://exodus611.github.io/nasdaq-eod-momentum-scanner/
- Currently 404 until enabled: Settings → Pages → Source: GitHub Actions → Save (одноразово)
- After enable, both workflows will deploy
- Our push 6c5f9a5 already triggered pages_on_push - after enable, site will be live

**Manual trigger:**
- Actions → EOD Scanner (15:30 ET) → Run workflow
- Or dashboard button (if SCAN_TRIGGER_TOKEN secret set)
  - Create fine-grained PAT: Developer settings → Personal access tokens → Fine-grained → Generate
  - Token name: scan-trigger, Repo: nasdaq-eod-momentum-scanner, Permissions: Actions: Read and write, Pages: Read and write
  - Add as secret: Settings → Secrets → Actions → New secret → SCAN_TRIGGER_TOKEN

### 12. Git History
```
6c5f9a5 MAXIMUM DEPLOY 29.08 - full universe 1504, 1452 hist, 449k featured, backtest 48.8% vs 34.3% base, scan MRNA/IREN top, Dockerfile+compose+Pages workflow+v2 deploy server, fundamentals top20
c9feef9 deploy check 29.08 - scan IREN/APP top, 60 tickers validated, backtest 56.6% hit-rate
18c390f use configure-pages@v4 (guaranteed version)
755c431 fault-tolerant workflow + safe manual-run button + persisted deploy key
...
```

### 13. Что осталось (опционально)

1. **Pages enable** - одноразово вручную в GitHub UI (нельзя через deploy key)
2. **SCAN_TRIGGER_TOKEN** - опционально для кнопки на дашборде
3. **Full data in CI** - GitHub Actions кэш уже настроен, первый полный прогон ~10 мин, далее инкрементально ~3-5 мин
4. **Monitoring** - можно добавить Telegram bot для уведомлений о сигналах

### 14. Итоговые файлы

```
.
├── .env.example
├── .github/workflows/
│   ├── daily_scan.yml (existing, 15:30 ET cron)
│   └── pages_on_push.yml (new, deploy on push)
├── Dockerfile (production)
├── docker-compose.yml (scanner + scheduler)
├── Makefile (all commands)
├── deploy/
│   ├── keys/id_ed25519_algotrade (private, gitignored, 432b)
│   ├── push.sh (auto restore .git + SSH)
│   └── README.md
├── deploy_server.py (v2.0, FastAPI, full control)
├── data/
│   ├── nasdaq_universe.csv (1504)
│   ├── fundamentals.json (20 top)
│   ├── hist_*.csv (1452 files, 200MB)
│   ├── featured_panel.parquet (136MB, 449k rows)
│   ├── oos_predictions.parquet (88MB, 277k OOS)
│   ├── live_scan.parquet (60 rows)
│   └── history_index.json
├── output/
│   ├── index.html (72KB, Pages entry)
│   ├── dashboard.html (72KB)
│   ├── scan_results.csv (60 rows)
│   └── meta.json
└── src/
    ├── scan.py (15:30 ET logic)
    ├── features.py (24 features)
    ├── backtest.py (walk-forward)
    ├── build_dashboard.py (PICKS auto)
    ├── update_universe.py
    ├── download_history.py
    └── prep_panel.py
```

### 15. Команды для проверки

```bash
# Локально
make all  # update + download-inc + panel + scan + dashboard
make run  # deploy_server on 8000
curl http://localhost:8000/health | jq

# Docker
docker-compose up -d
docker logs -f nasdaq-eod-scanner
curl http://localhost:8000/health

# GitHub
./deploy/push.sh "my update"
# Check https://github.com/exodus611/nasdaq-eod-momentum-scanner/actions
# Check https://exodus611.github.io/nasdaq-eod-momentum-scanner/ (after Pages enabled)
```

## 🎯 Результат

- ✅ Deploy key работает, SSH push/pull OK
- ✅ Full universe 1504, hist 1452, data 283MB
- ✅ Featured panel 449k rows, 1295 tickers
- ✅ Backtest 11 months OOS: 48.8% vs 34.3% base, +14.5% edge, все месяцы в плюсе
- ✅ Scan 15:30 ET работает, топ MRNA/IREN, 60 rows
- ✅ Dashboard 72KB с графиками, уровнями, сценариями
- ✅ Deploy server v2.0 на 8000, LIVE PREVIEW, full API
- ✅ Dockerfile + docker-compose + Makefile + .env.example
- ✅ GitHub Actions: daily_scan (15:30 ET cron) + pages_on_push (on push)
- ✅ Pushed to GitHub: 6c5f9a5

**Осталось только включить Pages в Settings → Pages → Source: GitHub Actions**

После этого дашборд будет доступен 24/7 на https://exodus611.github.io/nasdaq-eod-momentum-scanner/ с автообновлением будни 15:30 ET.

