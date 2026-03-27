import os
import time
import json
import requests
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
ORACLE_BASE         = "https://eventalphaoraclecode-production.up.railway.app"
ORACLE_BYPASS_KEY   = os.environ.get("ORACLE_BYPASS_KEY", "nurse2web3-internal")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
WALLET_PRIVATE_KEY  = os.environ.get("WALLET_PRIVATE_KEY", "")
WALLET_ADDRESS      = os.environ.get("WALLET_ADDRESS", "0xF79Ee76a3Bf903cADE2a411A4151fD64946360fe")
POLY_API_KEY        = os.environ.get("POLY_API_KEY", "")
POLY_API_SECRET     = os.environ.get("POLY_API_SECRET", "")
POLY_API_PASSPHRASE = os.environ.get("POLY_API_PASSPHRASE", "")
BET_AMOUNT_USDC     = 2.0
CONFIDENCE_THRESHOLD = 8
CHECK_INTERVAL_SEC  = 3600
DRY_RUN             = os.environ.get("DRY_RUN", "true").lower() == "true"

# Polymarket CLOB
POLY_HOST           = "https://clob.polymarket.com"
CHAIN_ID            = 137  # Polygon

# ── SETUP POLYMARKET CLIENT ───────────────────────────────────────────────────
def get_poly_client():
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        creds = ApiCreds(
            api_key=POLY_API_KEY,
            api_secret=POLY_API_SECRET,
            api_passphrase=POLY_API_PASSPHRASE
        )
        client = ClobClient(
            POLY_HOST,
            key=WALLET_PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=0,
            funder=WALLET_ADDRESS,
            creds=creds
        )
        return client
    except Exception as e:
        print(f"[POLYMARKET CLIENT ERROR] {e}")
        return None

# ── TELEGRAM ──────────────────────────────────────────────────────────────────
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[TELEGRAM] {message}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

# ── FETCH ORACLE SIGNALS ──────────────────────────────────────────────────────
def fetch_signal(endpoint):
    try:
        url = f"{ORACLE_BASE}/signal/{endpoint}"
        headers = {"x-payment-signature": ORACLE_BYPASS_KEY}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"[ORACLE] {endpoint} returned {r.status_code}")
            return None
    except Exception as e:
        print(f"[ORACLE ERROR] {endpoint}: {e}")
        return None

def fetch_all_signals():
    endpoints = ["nba", "nfl", "mma", "boxing", "politics", "trending", "arb"]
    all_signals = {}
    for ep in endpoints:
        print(f"[ORACLE] Fetching {ep}...")
        data = fetch_signal(ep)
        if data:
            all_signals[ep] = data
        time.sleep(1)
    return all_signals

# ── FETCH LIVE POLYMARKET MARKETS ─────────────────────────────────────────────
def get_polymarket_markets(limit=50):
    try:
        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "active": "true",
            "limit": limit,
            "order": "volume24hr",
            "ascending": "false"
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"[POLYMARKET] Error fetching markets: {e}")
    return []

def parse_market_prob(market):
    try:
        prices = market.get("outcomePrices")
        if isinstance(prices, list) and len(prices) > 0:
            return round(float(prices[0]) * 100, 1)
        if isinstance(prices, str):
            parsed = json.loads(prices)
            if isinstance(parsed, list) and len(parsed) > 0:
                return round(float(parsed[0]) * 100, 1)
    except:
        pass
    return None

def get_token_id(market, outcome="YES"):
    try:
        token_ids = market.get("clobTokenIds")
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)
        if isinstance(token_ids, list):
            return token_ids[0] if outcome == "YES" else token_ids[1]
    except:
        pass
    return None

# ── ASK CLAUDE TO ANALYZE ─────────────────────────────────────────────────────
def analyze_with_claude(signals, polymarket_markets):
    if not ANTHROPIC_API_KEY:
        print("[CLAUDE] No API key — skipping analysis")
        return []

    market_summary = []
    for m in polymarket_markets[:20]:
        prob = parse_market_prob(m)
        token_id = get_token_id(m, "YES")
        if prob and token_id:
            market_summary.append({
                "question": m.get("question", ""),
                "yes_probability": prob,
                "volume_24h": round(float(m.get("volume24hr", 0) or 0), 2),
                "liquidity": round(float(m.get("liquidity", 0) or 0), 2),
                "token_id": token_id
            })

    prompt = f"""You are an autonomous prediction market betting agent for Nurse2Web3.

Analyze the oracle signals and live Polymarket markets below, then identify the BEST betting opportunities.

ORACLE SIGNALS (from EventAlphaOracle):
{json.dumps(signals, indent=2)[:3000]}

LIVE POLYMARKET MARKETS (top by volume):
{json.dumps(market_summary, indent=2)[:2000]}

RULES:
- Only recommend bets with confidence 8/10 or higher
- Look for markets where oracle data shows a STRONG EDGE vs current probability
- Prefer markets with high liquidity (over $1000)
- Max 3 recommendations per cycle
- Be conservative — skipping is better than losing

Respond ONLY with a valid JSON array. No explanation, no markdown, just raw JSON.

Format:
[
  {{
    "market_question": "Will X happen?",
    "token_id": "the exact token_id from the market data above",
    "outcome": "YES",
    "current_probability": 45.0,
    "your_estimated_true_probability": 65.0,
    "confidence_score": 9,
    "reasoning": "Brief explanation",
    "bet_amount_usdc": 2.0
  }}
]

If no good opportunities exist return: []"""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        if response.status_code == 200:
            text = response.json()["content"][0]["text"].strip()
            text = text.replace("```json", "").replace("```", "").strip()
            recommendations = json.loads(text)
            return [r for r in recommendations if r.get("confidence_score", 0) >= CONFIDENCE_THRESHOLD]
        return []
    except Exception as e:
        print(f"[CLAUDE ERROR] {e}")
        return []

# ── PLACE REAL BET ────────────────────────────────────────────────────────────
def place_bet(recommendation):
    question    = recommendation.get("market_question", "")
    outcome     = recommendation.get("outcome", "YES")
    token_id    = recommendation.get("token_id", "")
    confidence  = recommendation.get("confidence_score", 0)
    reasoning   = recommendation.get("reasoning", "")
    current_prob = recommendation.get("current_probability", 0)
    est_prob    = recommendation.get("your_estimated_true_probability", 0)
    amount      = recommendation.get("bet_amount_usdc", BET_AMOUNT_USDC)
    price       = round(current_prob / 100, 4)  # Convert % to decimal

    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "market": question,
        "outcome": outcome,
        "token_id": token_id,
        "amount_usdc": amount,
        "price": price,
        "confidence": confidence,
        "current_prob": current_prob,
        "estimated_prob": est_prob,
        "reasoning": reasoning,
        "dry_run": DRY_RUN,
        "wallet": WALLET_ADDRESS
    }

    print(f"\n{'[DRY RUN]' if DRY_RUN else '[LIVE BET]'} {question}")
    print(f"  Outcome: {outcome} | Amount: ${amount} | Price: {price} | Confidence: {confidence}/10")

    if not DRY_RUN and token_id and WALLET_PRIVATE_KEY:
        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            client = get_poly_client()
            if client:
                side = BUY if outcome == "YES" else SELL
                order_args = MarketOrderArgs(
                    token_id=token_id,
                    amount=amount,
                    side=side,
                    order_type=OrderType.FOK
                )
                signed_order = client.create_market_order(order_args)
                resp = client.post_order(signed_order, OrderType.FOK)
                log_entry["order_response"] = str(resp)
                print(f"[BET PLACED] Response: {resp}")
                send_telegram(f"""✅ <b>REAL BET PLACED!</b>

📊 <b>Market:</b> {question}
🎯 <b>Outcome:</b> {outcome}
💰 <b>Amount:</b> ${amount} USDC
🔥 <b>Confidence:</b> {confidence}/10
📈 <b>Edge:</b> {round(est_prob - current_prob, 1)}%
💡 <b>Reasoning:</b> {reasoning}

🏥⚡ @Nurse2Web3""")
            else:
                print("[BET] Could not initialize Polymarket client")
        except Exception as e:
            print(f"[BET ERROR] {e}")
            log_entry["error"] = str(e)
            send_telegram(f"⚠️ Bet failed: {question}\nError: {e}\n🏥⚡")
    else:
        send_telegram(f"""🔵 <b>DRY RUN — Would Bet:</b>

📊 <b>Market:</b> {question}
🎯 <b>Outcome:</b> {outcome}
💰 <b>Amount:</b> ${amount} USDC
🔥 <b>Confidence:</b> {confidence}/10
📈 <b>Edge:</b> {round(est_prob - current_prob, 1)}%
💡 <b>Reasoning:</b> {reasoning}

🏥⚡ @Nurse2Web3""")

    with open("/tmp/bet_log.jsonl", "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    return log_entry

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────
def run_agent():
    print("=" * 60)
    print("🏥⚡ Nurse2Web3 Polymarket Betting Agent")
    print(f"Mode: {'DRY RUN' if DRY_RUN else '🟢 LIVE BETTING'}")
    print(f"Wallet: {WALLET_ADDRESS}")
    print(f"Bet size: ${BET_AMOUNT_USDC} USDC")
    print(f"Confidence threshold: {CONFIDENCE_THRESHOLD}/10")
    print("=" * 60)

    send_telegram(f"""🤖 <b>Betting Agent Started</b>
Mode: {'🔵 DRY RUN' if DRY_RUN else '🟢 LIVE BETTING'}
Wallet: <code>{WALLET_ADDRESS}</code>
Bet size: ${BET_AMOUNT_USDC} USDC
Confidence required: {CONFIDENCE_THRESHOLD}/10
🏥⚡ Nurse2Web3""")

    cycle = 0
    while True:
        cycle += 1
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        print(f"\n[CYCLE {cycle}] {now}")
        print("-" * 40)

        print("[STEP 1] Fetching EventAlphaOracle signals...")
        signals = fetch_all_signals()
        print(f"[STEP 1] Got {len(signals)} signal endpoints")

        print("[STEP 2] Fetching live Polymarket markets...")
        poly_markets = get_polymarket_markets(50)
        print(f"[STEP 2] Found {len(poly_markets)} active markets")

        print("[STEP 3] Asking Claude to analyze...")
        recommendations = analyze_with_claude(signals, poly_markets)
        print(f"[STEP 3] {len(recommendations)} high-confidence opportunities found")

        if recommendations:
            print(f"[STEP 4] Processing {len(recommendations)} bet(s)...")
            for rec in recommendations:
                place_bet(rec)
                time.sleep(2)
        else:
            print("[STEP 4] No high-confidence opportunities — skipping")
            send_telegram(f"🤖 Cycle {cycle} — no high-confidence bets found. Checking again in 1 hour. 🏥⚡")

        print(f"\n[SLEEP] Next check in {CHECK_INTERVAL_SEC // 60} minutes...")
        time.sleep(CHECK_INTERVAL_SEC)

if __name__ == "__main__":
    run_agent()
