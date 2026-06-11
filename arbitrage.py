#!/usr/bin/env python3
"""
Basketball odds: SportyBet vs Stake.com
Fetches odds via odds-api.io -> Excel -> Telegram bot.
"""
import json, csv, sys, os, time, logging
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("odds")

API_BASE = "https://api.odds-api.io/v3"
API_KEY = os.environ.get("ODDS_API_KEY", "61ff4a3c83aeefaf678b4684ab1926f0ac193a56b2cc782e2278934002816289")
BOOKMAKERS = "SportyBet,Stake"

# Telegram -- set these env vars or pass via CLI
TG_TOKEN = os.environ.get("TG_TOKEN", "8725819448:AAFaQo5_MXQxRGin3CuTaqVqMmuC0UxlsjI")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "786312246")

# ── Models ───────────────────────────────────────────────────────────────────

class RateLimitExceeded(Exception): pass

@dataclass
class MarketRow:
    event_id: int; home: str; away: str; league: str; status: str
    market_name: str; line: str
    sb_outcome1: str=""; sb_odds1: float=0; sb_outcome2: str=""; sb_odds2: float=0
    st_outcome1: str=""; st_odds1: float=0; st_outcome2: str=""; st_odds2: float=0

# ── Helpers ──────────────────────────────────────────────────────────────────

LABELS = {"home":"Home","away":"Away","draw":"Draw","over":"Over","under":"Under"}
def l(key): return LABELS.get(key, key.title())
def fv(v):
    try: return float(v)
    except: return 0.0

def _2way(m):
    out = [(k, fv(v)) for k,v in m.items() if k not in {"hdp"} and fv(v) > 0]
    return out if len(out) == 2 else None

# ── API Fetch ────────────────────────────────────────────────────────────────

def fetch_odds(api_key: str) -> list[MarketRow]:
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent":"ArbitrageBot/1.0","Accept":"application/json"})
    bp = {"apiKey": api_key}
    ratelimited = False

    def get(path, extra=None):
        nonlocal ratelimited
        p = {**bp, **(extra or {})}
        for a in range(3):
            try:
                r = s.get(f"{API_BASE}{path}", params=p, timeout=60)
                if r.status_code == 401: log.error("Invalid API key"); return []
                if r.status_code == 429:
                    ratelimited = True
                    if a < 2: log.warning("Rate limited, waiting 60s..."); time.sleep(60); continue
                    log.error("Rate limit exceeded."); return []
                r.raise_for_status(); return r.json()
            except Exception as e:
                if a < 2: log.warning(f"Retry {a+1}: {e}"); time.sleep(10)
                else: log.error(f"Failed: {e}"); return []
        return []

    events = get("/events", {"sport":"basketball","limit":30,"status":"pending"})
    if not events:
        if ratelimited: raise RateLimitExceeded()
        log.error("No pending events"); return []

    log.info(f"Found {len(events)} events\n")
    results = []

    for i in range(0, len(events), 10):
        batch = events[i:i+10]
        ids = [e["id"] for e in batch if e.get("id")]
        if not ids: continue

        data = get("/odds/multi", {"eventIds":",".join(str(x) for x in ids),"bookmakers":BOOKMAKERS})
        if not data: time.sleep(1); continue

        for ev in batch:
            eid = str(ev.get("id",""))
            if not eid or eid not in data: continue
            od = data[eid]
            if not isinstance(od, dict) or not od.get("bookmakers"): continue
            bms = od["bookmakers"]
            if "SportyBet" not in bms or "Stake" not in bms: continue

            home, away = od.get("home","?"), od.get("away","?")
            league = ev.get("league",{}).get("name","?")
            status = ev.get("status","?")

            sb = {m["name"]:m for m in bms["SportyBet"]}
            st = {m["name"]:m for m in bms["Stake"]}
            cnt = 0
            for mk in sorted(set(sb.keys()) & set(st.keys())):
                if mk == "ML": continue
                so, to = sb[mk].get("odds",[{}])[0], st[mk].get("odds",[{}])[0]
                p1, p2 = _2way(so), _2way(to)
                if not p1 or not p2: continue
                results.append(MarketRow(int(eid), home, away, league, status, mk, str(so.get("hdp","")),
                    l(p1[0][0]),p1[0][1],l(p1[1][0]),p1[1][1],
                    l(p2[0][0]),p2[0][1],l(p2[1][0]),p2[1][1]))
                cnt += 1
            if cnt: log.info(f"  {home} vs {away} ({league}) - {cnt} markets")
        time.sleep(0.5)

    return results

# ── Excel Export (to memory) ─────────────────────────────────────────────────

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

# ── Telegram ─────────────────────────────────────────────────────────────────

TG_OK = True

def tg_send_msg(token: str, chat_id: str, text: str):
    global TG_OK
    import requests
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
    import requests
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

# ── Sample Data ──────────────────────────────────────────────────────────────

def sample_data() -> list[MarketRow]:
    return [
        MarketRow(1,"Lakers","Celtics","NBA","pending","Spread","5.5",
            sb_outcome1="Home",sb_odds1=1.91,sb_outcome2="Away",sb_odds2=1.91,
            st_outcome1="Home",st_odds1=2.00,st_outcome2="Away",st_odds2=1.80),
        MarketRow(1,"Lakers","Celtics","NBA","pending","Totals","215.5",
            sb_outcome1="Over",sb_odds1=1.87,sb_outcome2="Under",sb_odds2=1.95,
            st_outcome1="Over",st_odds1=1.91,st_outcome2="Under",st_odds2=1.91),
        MarketRow(2,"Bulls","Heat","NBA","pending","Spread","3.5",
            sb_outcome1="Home",sb_odds1=2.05,sb_outcome2="Away",sb_odds2=1.75,
            st_outcome1="Home",st_odds1=1.83,st_outcome2="Away",st_odds2=2.00),
        MarketRow(2,"Bulls","Heat","NBA","pending","Totals","220.5",
            sb_outcome1="Over",sb_odds1=2.10,sb_outcome2="Under",sb_odds2=1.73,
            st_outcome1="Over",st_odds1=1.95,st_outcome2="Under",st_odds2=1.87),
        MarketRow(4,"Bucks","Sixers","NBA","pending","Spread","2.5",
            sb_outcome1="Home",sb_odds1=2.20,sb_outcome2="Away",sb_odds2=1.65,
            st_outcome1="Home",st_odds1=1.70,st_outcome2="Away",st_odds2=2.30),
    ]

# ── Daemon Mode ──────────────────────────────────────────────────────────────

def run_once(api_key: str, tg_token: str, tg_chat: str) -> bool:
    rows = fetch_odds(api_key)
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
    # Fallback: save locally if no Telegram or if it failed
    if not tg_token or not tg_chat or not TG_OK:
        with open(f"basketball_odds_{ts}.xlsx", "wb") as f:
            f.write(buf.getvalue())
        log.info(f"Saved locally -> basketball_odds_{ts}.xlsx")
    else:
        log.info("Telegram delivery complete")

    return True

def daemon_loop(api_key: str, tg_token: str, tg_chat: str, interval: int):
    log.info(f"Daemon mode: every {interval}min")
    log.info(f"Telegram: {'configured' if tg_token and tg_chat else 'NOT configured'}")
    log.info(f"API key: {'set' if api_key else 'NOT set'}")
    cycle = 0
    while True:
        cycle += 1
        log.info(f"[Cycle {cycle}] Starting fetch...")
        try:
            run_once(api_key, tg_token, tg_chat)
        except RateLimitExceeded:
            log.warning("Rate limited, waiting 60min...")
            time.sleep(3600)
            continue
        except Exception as e:
            log.error(f"Error: {e}")
        log.info(f"[Cycle {cycle}] Done. Sleeping {interval}min...")
        time.sleep(interval * 60)

# ── Interactive Bot Mode ─────────────────────────────────────────────────────

CACHE = {"rows": [], "arbs": [], "updated": ""}

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
        lines.append(f"<b>{r.home} vs {r.away}</b> ({r.league})")
        lines.append(f"  {r.market_name} ({r.line})")
        lines.append(f"  SportyBet: {sb}  |  {r.sb_outcome2} @ {r.sb_odds2}")
        lines.append(f"  Stake:    {st}  |  {r.st_outcome2} @ {r.st_odds2}")
        lines.append("")
    return "\n".join(lines)

def bot_format_bookmaker(rows: list[MarketRow], bookmaker: str) -> str:
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

def bot_refresh(api_key: str) -> str:
    global CACHE
    try:
        rows = fetch_odds(api_key) if api_key else sample_data()
    except RateLimitExceeded:
        return "Rate limited. Try again later."
    if not rows:
        return "No data returned."
    arbs = find_arbs(rows)
    CACHE = {"rows": rows, "arbs": arbs, "updated": datetime.now().strftime("%H:%M:%S")}
    return f"Refreshed: {len(rows)} markets, {len(arbs)} arbitrage opportunities."

def bot_listen(api_key: str, tg_token: str, tg_chat: str):
    import requests
    log.info("Interactive bot mode started")
    log.info(f"Bot: @{tg_token.split(':')[0]}")

    # Initial fetch
    bot_refresh(api_key)
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

                # Responses
                if text == "/start":
                    tg_send_msg(tg_token, chat_id,
                        "<b>Basketball Arbitrage Bot</b>\n\n"
                        "Commands:\n"
                        "/games - all games with odds\n"
                        "/sportybet - SportyBet odds only\n"
                        "/stake - Stake odds only\n"
                        "/arb - arbitrage opportunities\n"
                        "/refresh - fetch latest odds\n"
                        "/help - this message")

                elif text in ("/help", "/start@"):
                    tg_send_msg(tg_token, chat_id,
                        "/games - all games\n/sportybet - SportyBet odds\n"
                        "/stake - Stake odds\n/arb - arbitrage\n/refresh - refresh data")

                elif text == "/refresh":
                    result = bot_refresh(api_key)
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
    ap = argparse.ArgumentParser(description="Basketball odds: SportyBet vs Stake -> Excel + Telegram")
    ap.add_argument("--api-key", default=API_KEY)
    ap.add_argument("--tg-token", default=TG_TOKEN, help="Telegram bot token")
    ap.add_argument("--tg-chat", default=TG_CHAT_ID, help="Telegram chat ID")
    ap.add_argument("--sample", action="store_true", help="Demo data, no API key")
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

    if args.sample:
        rows = sample_data()
        buf, arb_count = build_xlsx(rows)
        arbs = find_arbs(rows)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        TG_OK = True
        if args.tg_token and args.tg_chat:
            tg_send_msg(args.tg_token, args.tg_chat, build_summary(rows, arbs))
            tg_send_file(args.tg_token, args.tg_chat, buf, f"basketball_odds_{ts}.xlsx",
                         f"Sample: {len(rows)} markets, {arb_count} arbs")
        if not args.tg_token or not args.tg_chat or not TG_OK:
            with open(f"basketball_odds_{ts}.xlsx", "wb") as f:
                f.write(buf.getvalue())
            print(f"Sample spreadsheet -> basketball_odds_{ts}.xlsx ({arb_count} arbs)")
        else:
            print("Sample report sent to Telegram.")
        return

    if not args.api_key:
        print("No API key. Use --sample, or set ODDS_API_KEY env var.")
        return

    if not args.tg_token:
        print("Telegram bot token required for --daemon, --once, or --bot. Set TG_TOKEN.")
        return

    if args.daemon:
        daemon_loop(args.api_key, args.tg_token, args.tg_chat, args.daemon)
    elif args.once:
        run_once(args.api_key, args.tg_token, args.tg_chat)
    elif args.bot:
        bot_listen(args.api_key, args.tg_token, args.tg_chat)
    else:
        # Single run, save locally
        try:
            rows = fetch_odds(args.api_key)
        except RateLimitExceeded:
            print("\nRate limited (100 req/hr on free tier). Use --sample or wait.")
            return
        if not rows: print("No data."); return
        buf, arb_count = build_xlsx(rows)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(f"basketball_odds_{ts}.xlsx", "wb") as f:
            f.write(buf.getvalue())
        print(f"\n{len(rows)} market rows -> basketball_odds_{ts}.xlsx ({arb_count} arbs)")

if __name__ == "__main__":
    main()
