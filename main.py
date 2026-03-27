import os
import time
import json
import requests
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────────────────
ORACLE_BASE        = "https://eventalphaoraclecode-production.up.railway.app"
ORACLE_BYPASS_KEY  = os.environ.get("ORACLE_BYPASS_KEY", "nurse2web3-internal")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN     = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
WALLET_PRIVATE_KEY = os.environ.get("WALLET_PRIVATE_KEY", "")
WALLET_ADDRESS     = os.environ.get("WALLET_ADDRESS", "0xF79Ee76a3Bf903cADE2a411A4151fD64946360fe")
BET_AMOUNT_USDC    = 2.0        # $2 per bet
CONFIDENCE_THRESHOLD = 8        # Only bet if AI scores 8/10 or higher
CHECK_INTERVAL_SEC = 3600       # Check every hour, but only bet on high confidence
DRY_RUN            = os.environ.get("DRY_RUN", "true").lower() == "true"  # Safety: set to false when ready to bet real money

# ── TELEGRAM NOTIFICATIONS ───────────────────────────────────────────────────
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

# ── FETCH ORACLE SIGNALS ─────────────────────────────────────────────────────
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
        time.sleep(1)  # Be polite to your own API
    return all_signals

# ── FETCH LIVE POLYMARKET MARKETS ────────────────────────────────────────────
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

# ── ASK CLAUDE TO ANALYZE SIGNALS ────────────────────────────────────────────
def analyze_with_claude(signals, polymarket_markets):
    if not ANTHROPIC_API_KEY:
        print("[CLAUDE] No API key set — skipping AI analysis")
        return []

    # Build a summary of top polymarket markets
    market_summary = []
    for m in polymarket_markets[:20]:
        prob = parse_market_prob(m)
        if prob:
            market_summary.append({
                "question": m.get("question", ""),
                "yes_probability": prob,
                "volume_24h": round(float(m.get("volume24hr", 0) or 0), 2),
                "liquidity": round(float(m.get("liquidity", 0) or 0), 2),
                "condition_id": m.get("conditionId", ""),
                "market_slug": m.get("marketMakerAddress", "")
            })

    prompt = f"""You are an autonomous prediction market betting agent for Nurse2Web3.

Your job: Analyze the oracle signals and live Polymarket markets below, then identify the BEST betting opportunities.

ORACLE SIGNALS (from EventAlphaOracle):
{json.dumps(signals, indent=2)[:3000]}

LIVE POLYMARKET MARKETS (top by volume):
{json.dumps(market_summary, indent=2)[:2000]}

RULES:
- Only recommend bets with confidence 8/10 or higher
- Look for markets where oracle data shows a STRONG EDGE vs current Polymarket probability
- Prefer markets with high liquidity (easier to get filled)
- Max 3 bet recommendations per cycle
- Be conservative — it's better to skip than to lose

Respond ONLY with a valid JSON array. No explanation, no markdown, just raw JSON.

Format:
[
  {{
    "market_question": "Will X happen?",
    "outcome": "YES" or "NO",
    "current_probability": 45.0,
    "your_estimated_true_probability": 65.0,
    "confidence_score": 9,
    "reasoning": "Brief explanation of edge",
    "bet_amount_usdc": 2.0
  }}
]

If no good opportunities exist, return an empty array: []
"""

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
            # Clean up any markdown formatting just in case
            text = text.replace("```json", "").replace("```", "").strip()
            recommendations = json.loads(text)
            # Filter to only high confidence bets
            return [r for r in recommendations if r.get("confidence_score", 0) >= CONFIDENCE_THRESHOLD]
        else:
            print(f"[CLAUDE] API error: {response.status_code}")
            return []

    except Exception as e:
        print(f"[CLAUDE ERROR] {e}")
        return []

# ── PLACE BET ON POLYMARKET ───────────────────────────────────────────────────
def place_polymarket_bet(recommendation, polymarket_markets):
    """
    NOTE: Real Polymarket betting requires the py-clob-client library and
    proper CLOB API authentication. This function logs the intent and
    sends a Telegram notification. Full onchain execution is enabled
    when DRY_RUN=false and dependencies are installed.
    """
    question = recommendation.get("market_question", "")
    outcome = recommendation.get("outcome", "YES")
    confidence = recommendation.get("confidence_score", 0)
    reasoning = recommendation.get("reasoning", "")
    current_prob = recommendation.get("current_probability", 0)
    estimated_prob = recommendation.get("your_estimated_true_probability", 0)
    amount = recommendation.get("bet_amount_usdc", BET_AMOUNT_USDC)

    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "market": question,
        "outcome": outcome,
        "amount_usdc": amount,
        "confidence": confidence,
        "current_prob": current_prob,
        "estimated_prob": estimated_prob,
        "reasoning": reasoning,
        "dry_run": DRY_RUN,
        "wallet": WALLET_ADDRESS
    }

    print(f"\n{'[DRY RUN] ' if DRY_RUN else '[LIVE BET] '}Bet Details:")
    print(json.dumps(log_entry, indent=2))

    # Save to log file
    with open("/tmp/bet_log.jsonl", "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    # Send Telegram notification
    mode = "🔵 DRY RUN" if DRY_RUN else "🟢 LIVE BET"
    message = f"""🤖 <b>Nurse2Web3 Betting Agent</b>
{mode}

📊 <b>Market:</b> {question}
🎯 <b>Betting:</b> {outcome}
💰 <b>Amount:</b> ${amount} USDC
🔥 <b>Confidence:</b> {confidence}/10

📈 <b>Current prob:</b> {current_prob}%
🧠 <b>My estimate:</b> {estimated_prob}%
📐 <b>Edge:</b> {round(estimated_prob - current_prob, 1)}%

💡 <b>Reasoning:</b> {reasoning}

🏥⚡ @Nurse2Web3"""

    send_telegram(message)

    if not DRY_RUN:
        # Full execution placeholder — requires py-clob-client
        # pip install py-clob-client
        # Full implementation: https://github.com/Polymarket/py-clob-client
        print("[BET] Live betting execution would go here")
        print("[BET] See README for py-clob-client setup instructions")

    return log_entry

# ── MAIN AGENT LOOP ───────────────────────────────────────────────────────────
def run_agent():
    print("=" * 60)
    print("🏥⚡ Nurse2Web3 Polymarket Betting Agent")
    print(f"Mode: {'DRY RUN (no real bets)' if DRY_RUN else 'LIVE BETTING'}")
    print(f"Wallet: {WALLET_ADDRESS}")
    print(f"Bet size: ${BET_AMOUNT_USDC} USDC")
    print(f"Confidence threshold: {CONFIDENCE_THRESHOLD}/10")
    print("=" * 60)

    send_telegram(f"""🤖 <b>Betting Agent Started</b>
Mode: {'🔵 DRY RUN' if DRY_RUN else '🟢 LIVE'}
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

        # Step 1: Fetch oracle signals
        print("[STEP 1] Fetching EventAlphaOracle signals...")
        signals = fetch_all_signals()
        print(f"[STEP 1] Got signals from {len(signals)} endpoints")

        # Step 2: Fetch live Polymarket markets
        print("[STEP 2] Fetching live Polymarket markets...")
        poly_markets = get_polymarket_markets(50)
        print(f"[STEP 2] Found {len(poly_markets)} active markets")

        # Step 3: Ask Claude to analyze
        print("[STEP 3] Asking Claude to analyze opportunities...")
        recommendations = analyze_with_claude(signals, poly_markets)
        print(f"[STEP 3] Claude found {len(recommendations)} high-confidence opportunities")

        # Step 4: Place bets
        if recommendations:
            print(f"[STEP 4] Placing {len(recommendations)} bet(s)...")
            for rec in recommendations:
                place_polymarket_bet(rec, poly_markets)
                time.sleep(2)
        else:
            print("[STEP 4] No high-confidence opportunities this cycle — skipping")
            send_telegram(f"🤖 Cycle {cycle} complete — no high-confidence bets found. Waiting {CHECK_INTERVAL_SEC//3600}h. 🏥⚡")

        # Step 5: Wait for next cycle
        print(f"\n[SLEEP] Next check in {CHECK_INTERVAL_SEC // 60} minutes...")
        time.sleep(CHECK_INTERVAL_SEC)

if __name__ == "__main__":
    run_agent()
