===== BASKETBALL ODDS: SPORTYBET vs STAKE =====

1. SETUP (one time):
   pip install -r requirements.txt

2. USAGE:
   python arbitrage.py --sample                    # demo spreadsheet
   python arbitrage.py --once                      # one live fetch
   python arbitrage.py --daemon 30                 # loop every 30min

3. TELEGRAM BOT:
   Create a bot via @BotFather on Telegram, get token + your chat ID.
   Set env vars or pass via CLI:
     set TG_TOKEN=123456:ABC-DEF...
     set TG_CHAT_ID=123456789
   Then:
     python arbitrage.py --once --tg-token %TG_TOKEN% --tg-chat %TG_CHAT_ID%

4. HOSTING (24/7):

   Option A - Railway (easiest free tier):
     - Push these files to a GitHub repo
     - Go to railway.app -> New Project -> Deploy from GitHub
     - Add env vars: ODDS_API_KEY, TG_TOKEN, TG_CHAT_ID
     - Start command: python arbitrage.py --daemon 30

   Option B - Render:
     - Create Web Service from your GitHub repo
     - Start command: python arbitrage.py --daemon 30
     - Add env vars in dashboard

   Option C - PythonAnywhere:
     - Upload files, create a scheduled task:
       python /home/you/arbitrage/arbitrage.py --once

5. ENV VARIABLES:
   ODDS_API_KEY  - from odds-api.io (free: 100 req/hr, paid: 5000/hr)
   TG_TOKEN      - Telegram bot token from @BotFather
   TG_CHAT_ID    - Your Telegram user/group chat ID
