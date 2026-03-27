# 🏥⚡ Nurse2Web3 Polymarket Betting Agent

An autonomous AI agent that:
1. Calls EventAlphaOracle for sports + politics signals
2. Asks Claude AI to find high-confidence betting edges
3. Places $2 USDC bets on Polymarket automatically
4. Sends Telegram notifications for every decision

---

## Railway Environment Variables

Add these in your Railway service settings:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `TELEGRAM_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `WALLET_PRIVATE_KEY` | Private key for 0xF79Ee76a3Bf903cADE2a411A4151fD64946360fe |
| `WALLET_ADDRESS` | 0xF79Ee76a3Bf903cADE2a411A4151fD64946360fe |
| `ORACLE_BYPASS_KEY` | nurse2web3-internal |
| `DRY_RUN` | true (change to false when ready for live bets) |

---

## How It Works

- Runs every hour
- Only bets when Claude scores confidence 8/10 or higher
- Max 3 bets per cycle
- $2 USDC per bet
- Logs every decision to /tmp/bet_log.jsonl
- Telegram alert for every bet placed or skipped

---

## IMPORTANT: DRY RUN Mode

The bot starts in DRY RUN mode by default.
This means it will analyze markets and send Telegram notifications
but will NOT place real bets.

When you're satisfied with its decisions, change DRY_RUN to false
in Railway environment variables to go live.

---

## Also update EventAlphaOracle

Add this to your EventAlphaOracle Railway environment variables:
ORACLE_BYPASS_KEY=nurse2web3-internal

Then add this check at the top of require_payment in main.py:

```python
bypass_key = request.headers.get("x-payment-signature")
if bypass_key == os.environ.get("ORACLE_BYPASS_KEY"):
    return f(*args, **kwargs)
```

This lets your own bot call your own API for free.
