# Telegram Notifications - Optional

## Setup (2 min)

1. Create bot:
   - Open @BotFather in Telegram
   - /newbot → name: nasdaq-eod-scanner → username: nasdaq_eod_xxxx_bot
   - Copy token: 123456:ABC-DEF...

2. Get chat ID:
   - Open your bot in Telegram, send /start
   - Visit: https://api.telegram.org/bot<TOKEN>/getUpdates
   - Find chat id: e.g. 123456789

3. Add secrets in GitHub:
   - https://github.com/exodus611/nasdaq-eod-momentum-scanner/settings/secrets/actions
   - New secret: TELEGRAM_BOT_TOKEN = your bot token
   - New secret: TELEGRAM_CHAT_ID = your chat id

4. Add step to daily_scan.yml after "Build dashboard":

```yaml
      - name: Send Telegram notification
        if: ${{ secrets.TELEGRAM_BOT_TOKEN != '' }}
        env:
          BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: |
          TOP=$(head -20 output/scan_results.csv)
          curl -s -X POST https://api.telegram.org/bot${BOT_TOKEN}/sendMessage \
            -d chat_id=${CHAT_ID} \
            -d parse_mode=Markdown \
            -d text="🚀 EOD Scan $(date +%F) 15:30 ET
          Top: $(python -c "import pandas as pd; df=pd.read_csv('output/scan_results.csv'); print(', '.join(df.head(3)['ticker'].tolist()))")
          Dashboard: https://exodus611.github.io/nasdaq-eod-momentum-scanner/
          CSV: $(wc -l < output/scan_results.csv) tickers"
```

## Local test

```bash
BOT_TOKEN="123456:ABC"
CHAT_ID="123456789"
curl -X POST https://api.telegram.org/bot${BOT_TOKEN}/sendMessage \
  -d chat_id=${CHAT_ID} \
  -d text="Test from EOD Scanner"
```
