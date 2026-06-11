#!/usr/bin/env python3
"""
Basketball odds: SportyBet vs Stake.com
Scrapes directly from both bookmakers - no API key needed.
"""
import json, csv, sys, os, time, logging
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("odds")

# Telegram -- set these env vars or pass via CLI
TG_TOKEN = os.environ.get("TG_TOKEN", "8725819448:AAFaQo5_MXQxRGin3CuTaqVqMmuC0UxlsjI")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "786312246")

# ── Models ───────────────────────────────────────────────────────────────────

@dataclass
class MarketRow:
    event_id: int; home: str; away: str; league: str; status: str
    market_name: str; line: str
    sb_outcome1: str=""; sb_odds1: float=0; sb_outcome2: str=""; sb_odds2: float=0
    st_outcome1: str=""; st_odds1: float=0; st_outcome2: str=""; st_odds2: float=0

# ── Stake session ─────────────────────────────────────

stake_session = requests.Session()
stake_session.headers.update({
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://stake.com/sports/basketball",
    "Origin": "https://stake.com",
    "x-language": "en",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
})

def init_stake_session():
    try:
        stake_session.cookies.clear()
        stake_session.get("https://stake.com/sports/basketball", timeout=15)
        log.info("Stake session initialized")
    except Exception as e:
        log.warning(f"Stake session init error: {e}")

# ── SportyBet fetch ──────────────────────────────────

def fetch_sportybet():
    URL = "https://www.sportybet.com/api/gh/factsCenter/pcUpcomingEvents?sportId=sr%3Asport%3A2&marketId=219%2C18%2C223%2C1%2C14%2C11&pageSize=100&pageNum=1&option=1"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.sportybet.com/gh/sport/basketball",
    }

    for attempt in range(3):
        try:
            r = requests.get(URL, headers=HEADERS, timeout=15)
            log.info(f"SportyBet status: {r.status_code} length: {len(r.text)}")
            if r.status_code == 200 and len(r.text) > 100:
                data = r.json()
                games = {}
                for tournament in data.get("data", {}).get("tournaments", []):
                    for event in tournament.get("events", []):
                        home = event.get("homeTeamName", "")
                        away = event.get("awayTeamName", "")
                        base_key = f"{home.lower().strip()} vs {away.lower().strip()}"

                        for market in event.get("markets", []):
                            market_name = market.get("name", "")
                            status = market.get("status", 1)
                            outcomes = market.get("outcomes", [])
                            if len(outcomes) != 2: continue
                            d = market.get("desc", "")

                            if market_name == "Winner (incl. overtime)" and status == 0:
                                key = f"{base_key}|winner"
                                games[key] = {"home": home, "away": away, "market": "Winner",
                                    "o1n": outcomes[0]["desc"], "o2n": outcomes[1]["desc"],
                                    "o1o": float(outcomes[0]["odds"]), "o2o": float(outcomes[1]["odds"]),
                                    "source": "SportyBet"}

                            elif market_name == "Over/Under" and status == 0 and market.get("farNearOdds") == 1:
                                key = f"{base_key}|ou|{d.lower()}"
                                games[key] = {"home": home, "away": away, "market": f"O/U {d}",
                                    "o1n": outcomes[0]["desc"], "o2n": outcomes[1]["desc"],
                                    "o1o": float(outcomes[0]["odds"]), "o2o": float(outcomes[1]["odds"]),
                                    "source": "SportyBet"}

                            elif market_name == "Handicap (incl. overtime)" and status == 0 and market.get("farNearOdds") == 1:
                                key = f"{base_key}|hcp|{d.lower()}"
                                games[key] = {"home": home, "away": away, "market": f"HCP {d}",
                                    "o1n": outcomes[0]["desc"], "o2n": outcomes[1]["desc"],
                                    "o1o": float(outcomes[0]["odds"]), "o2o": float(outcomes[1]["odds"]),
                                    "source": "SportyBet"}

                log.info(f"SportyBet: {len(games)} markets")
                return games
            log.warning(f"SportyBet attempt {attempt+1} failed, retry...")
            time.sleep(5)
        except Exception as e:
            log.warning(f"SportyBet error: {e}"), time.sleep(5)
    log.error("SportyBet failed after 3 attempts")
    return {}

# ── Stake fetch ──────────────────────────────────────

def fetch_stake():
    QUERY = """
    query SportTournamentFixtureList($sport: String!, $groups: String!, $tournamentLimit: Int = 25, $fixtureCountLimit: Int = 20, $type: SportSearchEnum!) {
      slugSport(sport: $sport) {
        tournamentList(type: $type, limit: $tournamentLimit) {
          name
          fixtureList(type: $type, limit: $fixtureCountLimit) {
            name
            data { ... on SportFixtureDataMatch { competitors { name } } }
            groups(groups: [$groups], status: [active]) {
              templates(limit: 10, includeEmpty: false) {
                markets(limit: 5) { name status specifiers outcomes { name odds active } }
              }
            }
          }
        }
      }
    }
    """
    payload = {"query": QUERY, "variables": {"sport": "basketball", "type": "upcoming", "groups": "main", "tournamentLimit": 25, "fixtureCountLimit": 20}}

    for attempt in range(3):
        try:
            r = stake_session.post("https://stake.com/_api/graphql", json=payload, timeout=15)
            log.info(f"Stake status: {r.status_code} length: {len(r.text)}")
            if r.status_code == 200 and len(r.text) > 100:
                data = r.json()
                games = {}
                for tournament in data.get("data", {}).get("slugSport", {}).get("tournamentList", []):
                    for fixture in tournament.get("fixtureList", []):
                        competitors = fixture.get("data", {}).get("competitors", [])
                        if len(competitors) < 2: continue
                        home, away = competitors[0]["name"], competitors[1]["name"]
                        base_key = f"{home.lower().strip()} vs {away.lower().strip()}"

                        for group in fixture.get("groups", []):
                            for template in group.get("templates", []):
                                for market in template.get("markets", []):
                                    mn = market.get("name", "")
                                    outcomes = market.get("outcomes", [])
                                    if market.get("status") != "active" or len(outcomes) != 2: continue
                                    sp = market.get("specifiers", "")

                                    if mn == "Winner (Incl. Overtime)":
                                        key = f"{base_key}|winner"
                                        games[key] = {"home": home, "away": away, "market": "Winner",
                                            "o1n": outcomes[0]["name"], "o2n": outcomes[1]["name"],
                                            "o1o": float(outcomes[0]["odds"]), "o2o": float(outcomes[1]["odds"]),
                                            "source": "Stake"}

                                    if "over/under" in mn.lower() or "total" in mn.lower():
                                        key = f"{base_key}|ou|{mn.lower()}"
                                        games[key] = {"home": home, "away": away, "market": f"O/U {sp}",
                                            "o1n": outcomes[0]["name"], "o2n": outcomes[1]["name"],
                                            "o1o": float(outcomes[0]["odds"]), "o2o": float(outcomes[1]["odds"]),
                                            "source": "Stake"}

                                    if "handicap" in mn.lower():
                                        key = f"{base_key}|hcp|{mn.lower()}"
                                        games[key] = {"home": home, "away": away, "market": f"HCP {sp}",
                                            "o1n": outcomes[0]["name"], "o2n": outcomes[1]["name"],
                                            "o1o": float(outcomes[0]["odds"]), "o2o": float(outcomes[1]["odds"]),
                                            "source": "Stake"}

                log.info(f"Stake: {len(games)} markets")
                return games
            log.warning(f"Stake attempt {attempt+1} failed, reinit...")
            init_stake_session()
            time.sleep(5)
        except Exception as e:
            log.warning(f"Stake error: {e}"), time.sleep(5)
    log.error("Stake failed after 3 attempts")
    return {}

# ── Merge both bookmakers into MarketRow list ────────

def fetch_odds() -> list[MarketRow]:
    sb = fetch_sportybet()
    st = fetch_stake()
    all_keys = sorted(set(sb.keys()) | set(st.keys()))
    rows, eid = [], 0
    for key in all_keys:
        s, t = sb.get(key), st.get(key)
        if not s or not t: continue
        eid += 1
        rows.append(MarketRow(eid, s["home"], s["away"], "Basketball", "pending",
            s["market"], "",
            s["o1n"], s["o1o"], s["o2n"], s["o2o"],
            t["o1n"], t["o1o"], t["o2n"], t["o2o"]))
    log.info(f"Merged: {len(rows)} markets (both bookmakers)")
    return rows

# ── Arbitrage Finder (works on MarketRow) ────────────

def find_arbs(rows: list[MarketRow]):
    arbs = []
    for r in rows:
        sb = {r.sb_outcome1: r.sb_odds1, r.sb_outcome2: r.sb_odds2}
        st = {r.st_outcome1: r.st_odds1, r.st_outcome2: r.st_odds2}
        labs = list(set(list(sb.keys())+list(st.keys())))
        if len(labs) != 2: continue
        l1,l2 = labs
        o1 = max(sb.get(l1,0), st.get(l1,0))
        o2 = max(sb.get(l2,0), st.get(l2,0))
        if o1<=0 or o2<=0 or 1/o1+1/o2 >= 1: continue
        s1 = "SportyBet" if sb.get(l1,0)>=st.get(l1,0) else "Stake"
        s2 = "SportyBet" if sb.get(l2,0)>=st.get(l2,0) else "Stake"
        arbs.append((r, (l1,o1,s1), (l2,o2,s2), 1/o1, 1/o2))
    return arbs

# ── Excel Export ─────────────────────────────────────

def build_xlsx(rows: list[MarketRow]) -> BytesIO:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    hf = PatternFill(start_color="4472C4",end_color="4472C4",fill_type="solid")
    hfn = Font(bold=True,color="FFFFFF")
    gf = PatternFill(start_color="C6EFCE",end_color="C6EFCE",fill_type="solid")
    th = Border(left=Side("thin"),right=Side("thin"),top=Side("thin"),bottom=Side("thin"))

    ws = wb.active; ws.title = "Combined Odds"
    hd = ["Event ID","Home","Away","League","Status","Market","Line",
          "SB Pick 1","SB Odds 1","SB Pick 2","SB Odds 2",
          "Stake Pick 1","Stake Odds 1","Stake Pick 2","Stake Odds 2"]
    for c,h in enumerate(hd,1):
        cl = ws.cell(row=1,column=c,value=h); cl.font=hfn; cl.fill=hf; cl.alignment=Alignment(horizontal="center"); cl.border=th
    for r in rows:
        ws.append([r.event_id,r.home,r.away,r.league,r.status,r.market_name,r.line,
                    r.sb_outcome1,r.sb_odds1,r.sb_outcome2,r.sb_odds2,
                    r.st_outcome1,r.st_odds1,r.st_outcome2,r.st_odds2])
    for c in ws.columns:
        ws.column_dimensions[c[0].column_letter].width = min(max(len(str(x.value or "")) for x in c)+3, 28)

    ws2 = wb.create_sheet("Arbitrage")
    ah = ["Event","League","Market","Line",
          "Outcome 1","Best Odds 1","Bookmaker 1",
          "Outcome 2","Best Odds 2","Bookmaker 2",
          "Arb %","Stake 1 ($)","Stake 2 ($)","Profit ($)"]
    for c,h in enumerate(ah,1):
        cl = ws2.cell(row=1,column=c,value=h); cl.font=hfn; cl.fill=hf; cl.alignment=Alignment(horizontal="center"); cl.border=th

    arbs = find_arbs(rows)
    banks = 1000.0
    for i,(r,o1,o2,s1,s2) in enumerate(arbs):
        vals = [f"{r.home} vs {r.away}",r.league,r.market_name,r.line,
                o1[0],o1[1],o1[2],o2[0],o2[1],o2[2],
                round((1/(1/o1[1]+1/o2[1])-1)*100,2),
                round(banks/(1/o1[1]+1/o2[1])/o1[1],2),
                round(banks/(1/o1[1]+1/o2[1])/o2[1],2),
                round(banks*(1/(1/o1[1]+1/o2[1])-1),2)]
        for c,v in enumerate(vals,1):
            cl = ws2.cell(row=i+2,column=c,value=v); cl.border=th; cl.fill=gf
    for c in ws2.columns:
        ws2.column_dimensions[c[0].column_letter].width = min(max(len(str(x.value or "")) for x in c)+3, 28)

    buf = BytesIO()
    wb.save(buf); buf.seek(0)
    return buf, len(arbs)

# ── Telegram ─────────────────────────────────────────

TG_OK = True

def tg_send_msg(token: str, chat_id: str, text: str):
    global TG_OK
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code != 200: log.warning(f"Telegram msg error: {r.text}")
        else: log.info("Telegram message sent")
    except Exception as e:
        log.warning(f"Telegram unreachable (msg): {e}")
        TG_OK = False

def tg_send_file(token: str, chat_id: str, buf: BytesIO, filename: str, caption: str = ""):
    global TG_OK
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
            files={"document": (filename, buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"chat_id": chat_id, "caption": caption}, timeout=30)
        if r.status_code != 200: log.warning(f"Telegram file error: {r.text}")
        else: log.info("Telegram file sent")
    except Exception as e:
        log.warning(f"Telegram unreachable (file): {e}")
        TG_OK = False

def build_summary(rows: list[MarketRow], arbs: list) -> str:
    lines = [f"<b>[BB] Basketball Odds Report</b>", f"<code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>", ""]
    lines.append(f"Markets compared: {len(rows)}")
    if arbs:
        lines.append(f"\n<b>[FIRE] Arbitrage: {len(arbs)} opportunities</b>\n")
        for r,o1,o2,_,_ in arbs:
            pct = round((1/(1/o1[1]+1/o2[1])-1)*100, 2)
            lines.append(f"• {r.home} vs {r.away} ({r.market_name})")
            lines.append(f"  {o1[0]}: {o1[1]} @ {o1[2]}  |  {o2[0]}: {o2[1]} @ {o2[2]}")
            lines.append(f"  <b>Profit: {pct}%</b>")
    else:
        lines.append("\nNo arbitrage opportunities found.")
    return "\n".join(lines)

# ── Daemon Mode ──────────────────────────────────────

def run_once(tg_token: str, tg_chat: str) -> bool:
    rows = fetch_odds()
    if not rows:
        log.warning("No data fetched")
        return False
    buf, arb_count = build_xlsx(rows)
    arbs = find_arbs(rows)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log.info(f"Got {len(rows)} market rows, {arb_count} arbs")

    global TG_OK
    TG_OK = True
    if tg_token and tg_chat:
        summary = build_summary(rows, arbs)
        tg_send_msg(tg_token, tg_chat, summary)
        tg_send_file(tg_token, tg_chat, buf, f"basketball_odds_{ts}.xlsx",
                     f"{len(rows)} markets, {arb_count} arbitrage opportunities")
    if not tg_token or not tg_chat or not TG_OK:
        with open(f"basketball_odds_{ts}.xlsx", "wb") as f:
            f.write(buf.getvalue())
        log.info(f"Saved locally -> basketball_odds_{ts}.xlsx")
    else:
        log.info("Telegram delivery complete")
    return True

def daemon_loop(tg_token: str, tg_chat: str, interval: int):
    log.info(f"Daemon mode: every {interval}min")
    log.info(f"Telegram: {'configured' if tg_token and tg_chat else 'NOT configured'}")
    cycle = 0
    while True:
        cycle += 1
        log.info(f"[Cycle {cycle}] Starting fetch...")
        try:
            run_once(tg_token, tg_chat)
        except Exception as e:
            log.error(f"Error: {e}")
        log.info(f"[Cycle {cycle}] Done. Sleeping {interval}min...")
        time.sleep(interval * 60)

# ── Interactive Bot Mode ─────────────────────────────

CACHE = {"rows": [], "arbs": [], "updated": ""}

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
    log.info(f"Healthcheck server on port {PORT}")

def bot_format_games(rows: list[MarketRow]) -> str:
    if not rows: return "No games available."
    lines = ["<b>Available Games</b>\n"]
    seen = {}
    for r in rows:
        key = (r.event_id, r.market_name)
        if key in seen: continue
        seen[key] = True
        sb = f"{r.sb_outcome1} @ {r.sb_odds1}" if r.sb_odds1 else "-"
        st = f"{r.st_outcome1} @ {r.st_odds1}" if r.st_odds1 else "-"
        lines.append(f"<b>{r.home} vs {r.away}</b>")
        lines.append(f"  {r.market_name} ({r.line})")
        lines.append(f"  SportyBet: {sb}  |  {r.sb_outcome2} @ {r.sb_odds2}")
        lines.append(f"  Stake:    {st}  |  {r.st_outcome2} @ {r.st_odds2}")
        lines.append("")
    return "\n".join(lines)

def bot_format_bookmaker(rows: list[MarketRow], bookmaker: str) -> str:
    if not rows: return "No games available right now."
    tag = "SportyBet" if "sporty" in bookmaker.lower() else "Stake"
    lines = [f"<b>{tag} Odds</b>\n"]
    for r in rows:
        if tag == "SportyBet":
            o1, o2 = r.sb_outcome1, r.sb_odds1
            o3, o4 = r.sb_outcome2, r.sb_odds2
        else:
            o1, o2 = r.st_outcome1, r.st_odds1
            o3, o4 = r.st_outcome2, r.st_odds2
        lines.append(f"<b>{r.home} vs {r.away}</b>")
        lines.append(f"  {r.market_name}: {o1} @ {o2}  |  {o3} @ {o4}")
    lines.append(f"\n{len(rows)} markets total")
    return "\n".join(lines)

def bot_format_arbs(arbs: list) -> str:
    if not arbs: return "No arbitrage opportunities right now."
    lines = ["<b>Arbitrage Opportunities</b>\n"]
    bank = 1000.0
    for r, o1, o2, ip1, ip2 in arbs:
        pct = round((1/(1/o1[1]+1/o2[1])-1)*100, 2)
        s1 = round(bank/(1/o1[1]+1/o2[1])/o1[1], 2)
        s2 = round(bank/(1/o1[1]+1/o2[1])/o2[1], 2)
        profit = round(bank*(1/(1/o1[1]+1/o2[1])-1), 2)
        lines.append(f"<b>{r.home} vs {r.away}</b> ({r.market_name})")
        lines.append(f"  {o1[0]}: {o1[1]} @ {o1[2]}  |  {o2[0]}: {o2[1]} @ {o2[2]}")
        lines.append(f"  Profit: {pct}% | Stake ${s1}+${s2} = ${profit} profit")
        lines.append("")
    return "\n".join(lines)

def bot_refresh() -> str:
    global CACHE
    rows = fetch_odds()
    arbs = find_arbs(rows) if rows else []
    CACHE = {"rows": rows or [], "arbs": arbs, "updated": datetime.now().strftime("%H:%M:%S")}
    if not rows:
        return "No data returned from SportyBet or Stake."
    return f"Refreshed: {len(rows)} markets, {len(arbs)} arbitrage opportunities."

def bot_listen(tg_token: str, tg_chat: str):
    start_healthcheck()
    log.info("Interactive bot mode started")
    log.info(f"Bot: @{tg_token.split(':')[0]}")

    init_stake_session()
    bot_refresh()
    last_update = 0

    while True:
        try:
            r = requests.post(f"https://api.telegram.org/bot{tg_token}/getUpdates",
                json={"offset": last_update + 1, "timeout": 30}, timeout=35)
            if r.status_code != 200: time.sleep(5); continue
            updates = r.json().get("result", [])
            for u in updates:
                last_update = u["update_id"]
                msg = u.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text") or "").strip().lower()

                if not chat_id or not text:
                    continue

                if text == "/start":
                    tg_send_msg(tg_token, chat_id,
                        "<b>Basketball Arbitrage Bot</b>\n\n"
                        "Commands:\n"
                        "/games - all games with odds\n"
                        "/sportybet - SportyBet odds only\n"
                        "/stake - Stake odds only\n"
                        "/arb - arbitrage opportunities\n"
                        "/refresh - fetch latest odds\n"
                        "/status - cache status\n"
                        "/help - this message")

                elif text in ("/help", "/start@"):
                    tg_send_msg(tg_token, chat_id,
                        "/games - all games\n/sportybet - SportyBet odds\n"
                        "/stake - Stake odds\n/arb - arbitrage\n/refresh - refresh data\n/status - cache status")

                elif text == "/status":
                    c = CACHE
                    tg_send_msg(tg_token, chat_id,
                        f"<b>Bot Status</b>\n"
                        f"Markets cached: {len(c['rows'])}\n"
                        f"Arbitrage: {len(c['arbs'])}\n"
                        f"Last updated: {c['updated'] or 'never'}\n"
                        f"Data source: direct scraping (no API key needed)")

                elif text == "/refresh":
                    result = bot_refresh()
                    tg_send_msg(tg_token, chat_id, result)

                elif text == "/games":
                    tg_send_msg(tg_token, chat_id, bot_format_games(CACHE["rows"]))

                elif text in ("/sportybet", "/sporty"):
                    tg_send_msg(tg_token, chat_id, bot_format_bookmaker(CACHE["rows"], "sportybet"))

                elif text in ("/stake", "/stakecom"):
                    tg_send_msg(tg_token, chat_id, bot_format_bookmaker(CACHE["rows"], "stake"))

                elif text == "/arb":
                    tg_send_msg(tg_token, chat_id, bot_format_arbs(CACHE["arbs"]))

        except Exception as e:
            log.warning(f"Bot loop error: {e}")
            time.sleep(5)

def main():
    global TG_OK
    import argparse
    ap = argparse.ArgumentParser(description="Basketball odds: SportyBet vs Stake (direct scraping)")
    ap.add_argument("--tg-token", default=TG_TOKEN, help="Telegram bot token")
    ap.add_argument("--tg-chat", default=TG_CHAT_ID, help="Telegram chat ID")
    ap.add_argument("--daemon", type=int, default=0, metavar="MIN", help="Push mode: send report every N min")
    ap.add_argument("--once", action="store_true", help="Run once, send to Telegram if configured")
    ap.add_argument("--bot", action="store_true", help="Interactive bot mode (listens for commands)")
    ap.add_argument("--test-tg", action="store_true", help="Test Telegram bot connection")
    args = ap.parse_args()

    if args.test_tg:
        if not args.tg_token:
            print("No TG_TOKEN configured."); return
        TG_OK = True
        tg_send_msg(args.tg_token, args.tg_chat, "Test message - Bot is working.")
        if TG_OK:
            print("OK: Telegram message sent. Check your Telegram.")
        else:
            print("FAIL: Could not reach Telegram. Check network/firewall.")
        return

    if not args.tg_token:
        print("Telegram bot token required. Set TG_TOKEN env var.")
        return

    if args.daemon:
        init_stake_session()
        daemon_loop(args.tg_token, args.tg_chat, args.daemon)
    elif args.once:
        init_stake_session()
        run_once(args.tg_token, args.tg_chat)
    elif args.bot:
        bot_listen(args.tg_token, args.tg_chat)
    else:
        init_stake_session()
        rows = fetch_odds()
        if not rows: print("No data."); return
        buf, arb_count = build_xlsx(rows)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(f"basketball_odds_{ts}.xlsx", "wb") as f:
            f.write(buf.getvalue())
        print(f"\n{len(rows)} market rows -> basketball_odds_{ts}.xlsx ({arb_count} arbs)")

if __name__ == "__main__":
    main()
