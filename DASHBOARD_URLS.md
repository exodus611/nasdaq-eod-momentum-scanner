# Дашборд - где смотреть

## 🚀 LIVE PREVIEW - работает СЕЙЧАС (Arena)

Твой дашборд уже задеплоен тут и работает 24/7 пока жив этот sandbox:

- **Основной дашборд (как на GitHub Pages):**
  https://8000-itfzt3s35dl7n27yygks7.e2b.app/

- **Панель управления (запуск пайплайна, логи, топ):**
  https://8000-itfzt3s35dl7n27yygks7.e2b.app/deploy

- **API:**
  - Health: https://8000-itfzt3s35dl7n27yygks7.e2b.app/health
  - Top 10: https://8000-itfzt3s35dl7n27yygks7.e2b.app/api/top
  - Full results: https://8000-itfzt3s35dl7n27yygks7.e2b.app/api/results
  - Backtest: https://8000-itfzt3s35dl7n27yygks7.e2b.app/api/backtest_summary
  - CSV: https://8000-itfzt3s35dl7n27yygks7.e2b.app/output/scan_results.csv

Если не открывается - в этом чате сверху должен быть блок "LIVE PREVIEW" → выбери порт 8000 → EOD Scanner Final

## 📁 Локальные файлы (в workspace)

- `output/index.html` - дашборд (открой слева в preview)
- `output/dashboard.html` - то же самое
- `output/scan_results.csv` - таблица 60 тикеров
- `output/meta.json` - метаданные скана

## 🌐 GitHub Pages - постоянный адрес (после включения)

После включения Pages (1 клик, см ENABLE_PAGES.md):

**https://exodus611.github.io/nasdaq-eod-momentum-scanner/**

Включить:
- Прямая ссылка: https://github.com/exodus611/nasdaq-eod-momentum-scanner/settings/pages
- Где искать: Settings → слева Code and automation → Pages → Source: GitHub Actions → Save
- Если нет раздела Pages: сделай репо публичным (Settings → General → Danger Zone → Change visibility → Make public) ИЛИ добавь секрет SCAN_TRIGGER_TOKEN и запусти workflow - Pages включится автоматом.

## ⚙️ Почему Workflow не бежит?

### Проверь 3 места:

**1. Actions включены?**
- Открой: https://github.com/exodus611/nasdaq-eod-momentum-scanner/settings/actions
- В разделе "Actions permissions" выбери **Allow all actions and reusable workflows** → Save
- Если видишь баннер "Actions disabled for this repository" - включи.

**2. Workflow включен?**
- Открой: https://github.com/exodus611/nasdaq-eod-momentum-scanner/actions
- Слева выбери **EOD Scanner (15:30 ET)**
- Если сверху желтый баннер "This workflow is disabled" → нажми **Enable workflow**

**3. Запуск:**
- В том же workflow справа вверху кнопка **Run workflow** → выбери branch **main** → **Run workflow** (зеленая)
- Подожди 5-10 мин, обнови страницу - появится новый run
- Кликни на run → смотри логи каждого шага (теперь 3-й шаг починен и не падает)

**Если все равно не бежит:**
- Проверь что ты Owner/Admin репо (только Owner может запускать)
- Проверь что нет лимита Actions для приватных репо (Free дает 2000 мин/мес)
- Попробуй второй workflow: **Pages Deploy on Push** → Run workflow (он деплоит уже готовый output/)

### Логи последнего фикса:
- `1718f54 FIX: prep_panel crash` - починил падение на 3-м шаге (ticker column missing)
- Теперь `prep_panel.py` проходит за 27 сек: 449,262 rows, 1295 tickers

## 🔄 Как обновлять дашборд вручную

**Вариант A - Тут в Arena (быстро):**
- Открой https://8000-itfzt3s35dl7n27yygks7.e2b.app/deploy
- Нажми **🚀 Fast Pipeline** → подожди 2-3 мин → дашборд обновится

**Вариант B - Локально:**
```bash
make all  # update + download-inc + panel + scan + dashboard
```

**Вариант C - Через GitHub Actions (после включения):**
- Actions → EOD Scanner → Run workflow → дашборд обновится и зальется в Pages + коммит в репо

**Вариант D - Docker:**
```bash
docker-compose up -d
# http://localhost:8000
```

## 📊 Текущий скан (2026-08-28)

Топ-3:
1. MRNA $137.33 prob 0.5269 hit 57.3%
2. IREN $35.55 prob 0.5244
3. MRVL $217.65 prob 0.5184

Файл: output/scan_results.csv (60 rows)
