#!/usr/bin/env python3
"""
Basketball odds from SportyBet (Ghana)
Scrapes directly - no API key needed.
"""
import json, csv, sys, os, time, logging
from dataclasses import dataclass
from datetime import datetime, timezone
import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("sportybet")

TG_TOKEN = os.environ.get("TG_TOKEN", "8725819448:AAFaQo5_MXQxRGin3CuTaqVqMmuC0UxlsjI")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "786312246")

@dataclass
class Game:
    home: str; away: str
    market: str; line: str
    outcome1: str; odds1: float
    outcome2: str; odds2: float
    start_time: str

SB_URL = "https://www.sportybet.com/api/gh/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A2&marketId=219%2C18%2C223%2C1%2C14%2C11&pageSize=100&pageNum=1&option=1"
SB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.sportybet.com/gh/sport/basketball",
}

def ms_to_str(ms):
    try: return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%d %b %H:%M")
    except: return ""

def fetch_games() -> list[Game]:
    for attempt in range(3):
        try:
            r = requests.get(SB_URL, headers=SB_HEADERS, timeout=15)
            log.info(f"SportyBet: {r.status_code} len={len(r.text)}")
            if r.status_code != 200 or len(r.text) < 100:
                time.sleep(5); continue

            data = r.json()
            games = []
            seen = set()

            for tournament in data.get("data", {}).get("tournaments", []):
                for event in tournament.get("events", []):
                    home = event.get("homeTeamName", "")
                    away = event.get("awayTeamName", "")
                    start = ms_to_str(event.get("estimateStartTime"))
                    if not home or not away: continue

                    for market in event.get("markets", []):
                        mn = market.get("name", "")
                        st = market.get("status", 1)
                        outcomes = market.get("outcomes", [])
                        if len(outcomes) != 2 or st != 0: continue
                        desc = market.get("desc", "")
                        mg = market.get("farNearOdds")

                        if mn == "Winner (incl. overtime)":
                            mk = "Winner"
                            ln = ""
                        elif mn == "Over/Under" and mg == 1:
                            mk = "O/U"
                            ln = desc
                        elif mn == "Handicap (incl. overtime)" and mg == 1:
                            mk = "HCP"
                            ln = desc
                        else:
                            continue

                        key = (home, away, mk, ln)
                        if key in seen: continue
                        seen.add(key)

                        games.append(Game(home, away, mk, ln,
                            outcomes[0]["desc"], float(outcomes[0]["odds"]),
                            outcomes[1]["desc"], float(outcomes[1]["odds"]),
                            start))

            log.info(f"Games: {len(games)} markets")
            return games

        except Exception as e:
            log.warning(f"Attempt {attempt+1}: {e}"), time.sleep(5)

    log.error("SportyBet failed after 3 attempts")
    return []

# ── Telegram ─────────────────────────────────────────

TG_OK = True
TG_MAX = 4000

def tg_send(token: str, chat_id: str, text: str):
    global TG_OK
    try:
        chunks = [text[i:i+TG_MAX] for i in range(0, len(text), TG_MAX)] if len(text) > TG_MAX else [text]
        for c in chunks:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": c, "parse_mode": "HTML"}, timeout=15)
            if r.status_code != 200:
                log.warning(f"TG error: {r.text}"); return
        log.info(f"TG sent ({len(chunks)} chunk{'s' if len(chunks)>1 else ''})")
    except Exception as e:
        log.warning(f"TG unreachable: {e}"); TG_OK = False

# ── Interactive Bot ──────────────────────────────────

CACHE = {"games": [], "updated": ""}

def start_healthcheck():
    import http.server, threading
    PORT = int(os.environ.get("PORT", 8080))
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *a): pass
    t = threading.Thread(target=lambda: http.server.HTTPServer(("0.0.0.0", PORT), H).serve_forever(), daemon=True)
    t.start()
    log.info(f"Healthcheck on port {PORT}")

def format_games(games: list[Game]) -> str:
    if not games: return "No games available."
    lines = ["<b>SportyBet Basketball Odds</b>\n"]
    for g in games:
        lines.append(f"<b>{g.home} vs {g.away}</b>  <code>{g.start_time}</code>")
        lines.append(f"  {g.market} {g.line}: {g.outcome1} @ {g.odds1}  |  {g.outcome2} @ {g.odds2}")
    lines.append(f"\n{len(games)} markets")
    return "\n".join(lines)

def bot_refresh() -> str:
    global CACHE
    gs = fetch_games()
    CACHE = {"games": gs, "updated": datetime.now().strftime("%H:%M:%S")}
    if not gs: return "No data from SportyBet."
    return f"Refreshed: {len(gs)} markets."

def bot_listen(tg_token: str, tg_chat: str):
    start_healthcheck()
    log.info("Bot started")
    bot_refresh()
    last = 0

    while True:
        try:
            r = requests.post(f"https://api.telegram.org/bot{tg_token}/getUpdates",
                json={"offset": last + 1, "timeout": 30}, timeout=35)
            if r.status_code != 200: time.sleep(5); continue
            for u in r.json().get("result", []):
                last = u["update_id"]
                msg = u.get("message", {})
                cid = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text") or "").strip().lower()
                if not cid or not text: continue

                if text == "/start":
                    tg_send(tg_token, cid,
                        "<b>SportyBet Basketball Odds Bot</b>\n\n"
                        "/sportybet - show odds\n/refresh - refresh data\n/status - status\n/help - this")

                elif text in ("/help", "/start@"):
                    tg_send(tg_token, cid,
                        "/sportybet - SportyBet odds\n/refresh - refresh\n/status - status")

                elif text == "/status":
                    c = CACHE
                    tg_send(tg_token, cid,
                        f"<b>Status</b>\nMarkets: {len(c['games'])}\nUpdated: {c['updated'] or 'never'}")

                elif text == "/refresh":
                    tg_send(tg_token, cid, bot_refresh())

                elif text in ("/sportybet", "/sporty"):
                    tg_send(tg_token, cid, format_games(CACHE["games"]))

        except Exception as e:
            log.warning(f"Bot error: {e}"), time.sleep(5)

def main():
    import argparse
    ap = argparse.ArgumentParser(description="SportyBet basketball odds bot")
    ap.add_argument("--tg-token", default=TG_TOKEN)
    ap.add_argument("--tg-chat", default=TG_CHAT_ID)
    ap.add_argument("--once", action="store_true", help="Fetch and send once")
    ap.add_argument("--bot", action="store_true", help="Interactive bot")
    ap.add_argument("--test-tg", action="store_true", help="Test Telegram")
    args = ap.parse_args()

    if args.test_tg:
        global TG_OK
        if not args.tg_token: print("No TG_TOKEN"); return
        TG_OK = True
        tg_send(args.tg_token, args.tg_chat, "Test - Bot working.")
        print("OK" if TG_OK else "FAIL")
        return

    if not args.tg_token:
        print("TG_TOKEN required"); return

    if args.bot:
        bot_listen(args.tg_token, args.tg_chat)
    elif args.once:
        gs = fetch_games()
        if gs: tg_send(args.tg_token, args.tg_chat, format_games(gs))
    else:
        gs = fetch_games()
        if gs: print(format_games(gs))

if __name__ == "__main__":
    main()
