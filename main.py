import os
import time
import json
import requests
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
ORACLE_BASE          = "https://eventalphaoraclecode-production.up.railway.app"
ORACLE_BYPASS_KEY    = os.environ.get("ORACLE_BYPASS_KEY", "nurse2web3-internal")
ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN       = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID     = os.environ.get("TELEGRAM_CHAT_ID", "")
WALLET_PRIVATE_KEY   = os.environ.get("WALLET_PRIVATE_KEY", "")
WALLET_ADDRESS       = os.environ.get("WALLET_ADDRESS", "0xF79Ee76a3Bf903cADE2a411A4151fD64946360fe")
POLY_API_KEY         = os.environ.get("POLY_API_KEY", "")
POLY_API_SECRET      = os.environ.get("POLY_API_SECRET", "")
POLY_API_PASSPHRASE  = os.environ.get("POLY_API_PASSPHRASE", "")
BET_AMOUNT_USDC      = 2.0
CONFIDENCE_THRESHOLD = 7          # ✅ FIXED: lowered from 8 to 7 (more realistic)
CHECK_INTERVAL_SEC   = 3600
DRY_RUN              = os.environ.get("DRY_RUN", "true").lower() == "true"

POLY_HOST  = "https://clob.polymarket.com"
CHAIN_ID   = 137

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

# ── POLYMARKET CLIENT ─────────────────────────────────────────────────────────
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

# ── FETCH ORACLE SIGNALS ──────────────────────────────────────────────────────
def fetch_signal(endpoint, params=None):
    try:
        url = f"{ORACLE_BASE}/signal/{endpoint}"
        headers = {"x-payment-signature": ORACLE_BYPASS_KEY}
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"[ORACLE] {endpoint} returned {r.status_code}: {r.text[:200]}")
            return None
    except Exception as e:
        print(f"[ORACLE ERROR] {endpoint}: {e}")
        return None

def fetch_all_signals():
    """Fetch signals and extract key entities (team names, fighter names, topics)"""
    all_signals = {}

    # ✅ FIXED: fetch trending first to get actual current events
    print("[ORACLE] Fetching trending...")
    trending = fetch_signal("trending")
    if trending:
        all_signals["trending"] = trending

    # Fetch each sport
    for ep in ["nba", "nfl", "mma", "boxing", "politics"]:
        print(f"[ORACLE] Fetching {ep}...")
        data = fetch_signal(ep)
        if data:
            all_signals[ep] = data
        time.sleep(0.5)

    # Fetch ARB scanner
    print("[ORACLE] Fetching arb...")
    arb = fetch_signal("arb")
    if arb:
        all_signals["arb"] = arb

    return all_signals

# ── ✅ NEW: EXTRACT SEARCH KEYWORDS FROM SIGNALS ──────────────────────────────
def extract_search_keywords(signals):
    """
    Pull out team names, fighter names, and topics from oracle signals
    so we can search Polymarket for MATCHING markets specifically.
    """
    keywords = []

    for category, data in signals.items():
        if not data:
            continue

        # Handle list responses
        items = data if isinstance(data, list) else [data]

        for item in items:
            if not isinstance(item, dict):
                continue

            # Extract team names from sports signals
            for field in ["team", "home_team", "away_team", "opponent", "subject"]:
                val = item.get(field, "")
                if val and isinstance(val, str) and len(val) > 2:
                    keywords.append(val.strip())

            # Extract fighter names
            for field in ["fighter", "fighter_a", "fighter_b", "player"]:
                val = item.get(field, "")
                if val and isinstance(val, str) and len(val) > 2:
                    keywords.append(val.strip())

            # Extract event/topic
            for field in ["event", "topic", "market", "title", "name"]:
                val = item.get(field, "")
                if val and isinstance(val, str) and len(val) > 3:
                    keywords.append(val.strip())

    # Add category-level keywords
    if "nba" in signals:
        keywords.append("NBA")
    if "nfl" in signals:
        keywords.append("NFL")
    if "mma" in signals or "boxing" in signals:
        keywords.extend(["UFC", "boxing", "fight"])
    if "politics" in signals:
        keywords.extend(["Trump", "election", "president", "Congress"])

    # Deduplicate and limit
    seen = set()
    unique = []
    for k in keywords:
        if k.lower() not in seen:
            seen.add(k.lower())
            unique.append(k)

    print(f"[KEYWORDS] Extracted: {unique[:15]}")
    return unique[:15]

# ── ✅ NEW: SEARCH POLYMARKET BY KEYWORD ──────────────────────────────────────
def search_polymarket_by_keyword(keyword, limit=5):
    """Search Polymarket for markets matching a specific keyword"""
    try:
        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "active": "true",
            "limit": limit,
            "q": keyword,           # ✅ keyword search — the key fix
            "order": "volume24hr",
            "ascending": "false"
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            results = r.json()
            return results if isinstance(results, list) else []
    except Exception as e:
        print(f"[POLYMARKET SEARCH] Error for '{keyword}': {e}")
    return []

def get_targeted_markets(keywords):
    """
    ✅ FIXED: Instead of grabbing random top-volume markets,
    search Polymarket for markets that MATCH our oracle signals.
    """
    all_markets = {}  # Use dict to deduplicate by market ID

    for keyword in keywords[:10]:  # Limit API calls
        print(f"[POLYMARKET] Searching for '{keyword}'...")
        results = search_polymarket_by_keyword(keyword, limit=5)
        for market in results:
            mid = market.get("id") or market.get("conditionId", "")
            if mid and mid not in all_markets:
                all_markets[mid] = market
        time.sleep(0.3)

    markets = list(all_markets.values())
    print(f"[POLYMARKET] Found {len(markets)} targeted markets across all keywords")
    return markets

# ── PARSE MARKET DATA ─────────────────────────────────────────────────────────
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

    if not polymarket_markets:
        print("[CLAUDE] No targeted markets found to analyze")
        return []

    market_summary = []
    for m in polymarket_markets[:25]:
        prob = parse_market_prob(m)
        token_id = get_token_id(m, "YES")
        if prob is not None and token_id:
            market_summary.append({
                "question": m.get("question", ""),
                "yes_probability": prob,
                "volume_24h": round(float(m.get("volume24hr", 0) or 0), 2),
                "liquidity": round(float(m.get("liquidity", 0) or 0), 2),
                "token_id": token_id
            })

    if not market_summary:
        print("[CLAUDE] No markets with valid probabilities found")
        return []

    prompt = f"""You are an autonomous prediction market betting agent for Nurse2Web3.

These Polymarket markets were specifically selected because they MATCH the oracle signals below.
Your job is to find where the oracle data gives us an edge over the current market probability.

ORACLE SIGNALS (from EventAlphaOracle):
{json.dumps(signals, indent=2)[:3000]}

TARGETED POLYMARKET MARKETS (matched to oracle signals):
{json.dumps(market_summary, indent=2)[:2500]}

INSTRUCTIONS:
- These markets were chosen because they relate to the oracle data — look for direct matches
- Find markets where oracle probability differs significantly from Polymarket probability (10%+ edge)
- Only recommend confidence 7/10 or higher
- Prefer markets with liquidity over $500
- Max 3 recommendations
- If oracle says team A wins at 70% but Polymarket says 45% — that's a strong YES bet
- If oracle says team B loses but Polymarket has them at 80% — that's a NO bet

Respond ONLY with a valid JSON array. No explanation, no markdown, just raw JSON.

Format:
[
  {{
    "market_question": "Will X happen?",
    "token_id": "exact token_id from market data",
    "outcome": "YES or NO",
    "current_probability": 45.0,
    "your_estimated_true_probability": 68.0,
    "confidence_score": 8,
    "reasoning": "Oracle shows Lakers at 68% win probability, Polymarket only pricing them at 45%",
    "bet_amount_usdc": 2.0
  }}
]

If no clear edge exists, return exactly: []"""

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
            if isinstance(recommendations, list):
                filtered = [r for r in recommendations if r.get("confidence_score", 0) >= CONFIDENCE_THRESHOLD]
                print(f"[CLAUDE] {len(recommendations)} recommendations, {len(filtered)} above threshold")
                return filtered
        else:
            print(f"[CLAUDE] API error: {response.status_code} {response.text[:200]}")
        return []
    except Exception as e:
        print(f"[CLAUDE ERROR] {e}")
        return []

# ── PLACE BET ─────────────────────────────────────────────────────────────────
def place_bet(recommendation):
    question     = recommendation.get("market_question", "")
    outcome      = recommendation.get("outcome", "YES")
    token_id     = recommendation.get("token_id", "")
    confidence   = recommendation.get("confidence_score", 0)
    reasoning    = recommendation.get("reasoning", "")
    current_prob = recommendation.get("current_probability", 0)
    est_prob     = recommendation.get("your_estimated_true_probability", 0)
    amount       = recommendation.get("bet_amount_usdc", BET_AMOUNT_USDC)
    price        = round(current_prob / 100, 4)

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
    print(f"  Outcome: {outcome} | Amount: ${amount} | Confidence: {confidence}/10")

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
                send_telegram(f"""✅ <b>REAL BET PLACED!</b>

📊 <b>Market:</b> {question}
🎯 <b>Outcome:</b> {outcome}
💰 <b>Amount:</b> ${amount} USDC
🔥 <b>Confidence:</b> {confidence}/10
📈 <b>Edge:</b> {round(est_prob - current_prob, 1)}%
💡 <b>Reasoning:</b> {reasoning}

🏥⚡ @Nurse2Web3""")
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
    print("🏥⚡ Nurse2Web3 Polymarket Betting Agent v2")
    print(f"Mode: {'🔵 DRY RUN' if DRY_RUN else '🟢 LIVE BETTING'}")
    print(f"Wallet: {WALLET_ADDRESS}")
    print(f"Bet size: ${BET_AMOUNT_USDC} USDC")
    print(f"Confidence threshold: {CONFIDENCE_THRESHOLD}/10")
    print("=" * 60)

    send_telegram(f"""🤖 <b>Betting Agent v2 Started</b>
Mode: {'🔵 DRY RUN' if DRY_RUN else '🟢 LIVE BETTING'}
Wallet: <code>{WALLET_ADDRESS}</code>
Bet size: ${BET_AMOUNT_USDC} USDC
Confidence required: {CONFIDENCE_THRESHOLD}/10
✅ Smart signal matching enabled
🏥⚡ Nurse2Web3""")

    cycle = 0
    while True:
        cycle += 1
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        print(f"\n[CYCLE {cycle}] {now}")
        print("-" * 40)

        # Step 1: Get oracle signals
        print("[STEP 1] Fetching EventAlphaOracle signals...")
        signals = fetch_all_signals()
        print(f"[STEP 1] Got {len(signals)} signal categories")

        # Step 2: Extract keywords from signals
        print("[STEP 2] Extracting search keywords from signals...")
        keywords = extract_search_keywords(signals)

        # Step 3: Search Polymarket for MATCHING markets
        print("[STEP 3] Searching Polymarket for targeted markets...")
        poly_markets = get_targeted_markets(keywords)

        # Step 4: Claude analyzes the matched pairs
        print("[STEP 4] Asking Claude to find edges in matched markets...")
        recommendations = analyze_with_claude(signals, poly_markets)
        print(f"[STEP 4] {len(recommendations)} high-confidence opportunities found")

        # Step 5: Place bets
        if recommendations:
            print(f"[STEP 5] Processing {len(recommendations)} bet(s)...")
            for rec in recommendations:
                place_bet(rec)
                time.sleep(2)
        else:
            msg = f"🤖 Cycle {cycle} complete\n📊 Searched {len(poly_markets)} targeted markets\n🔍 No edge found above {CONFIDENCE_THRESHOLD}/10 threshold\n⏰ Next check in 1 hour\n🏥⚡"
            print("[STEP 5] No high-confidence opportunities this cycle")
            send_telegram(msg)

        print(f"\n[SLEEP] Next check in {CHECK_INTERVAL_SEC // 60} minutes...")
        time.sleep(CHECK_INTERVAL_SEC)

if __name__ == "__main__":
    run_agent()
