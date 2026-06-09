# Falcon FX Bot

Automated TradingView webhook executor for South African retail traders. It validates alerts with Falcon FX multi-timeframe logic, applies ZAR-based risk controls, and routes orders to OANDA, FXCM, or MetaTrader 5 brokers.

CFDs and leveraged forex products are high risk. `LIVE_TRADING=false` is the default safety mode and must be explicitly changed before real order execution.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`, keep `LIVE_TRADING=false` while testing, then start the webhook server:

```powershell
python -m falcon_fx_bot.main
```

Webhook endpoint:

```text
POST http://localhost:5000/webhook
X-Webhook-Secret: change-me
```

TradingView alert body:

```json
{"signal":"BUY","pair":"XAUUSD","timeframe":"15","price":2345.50,"sl":2330.00,"tp1":2360.00,"tp2":2380.00,"timestamp":"2024-01-15T10:30:00Z"}
```

Run the dashboard:

```powershell
streamlit run falcon_fx_bot/dashboard/app.py --server.port 8501
```

## Broker Setup for South Africa

OANDA:
- Account opening: [OANDA register](https://www.oanda.com/register/)
- API URLs used by the bot: practice `https://api-fxpractice.oanda.com/v3`, live `https://api-fxtrade.oanda.com/v3`
- Set `BROKER=oanda`, `OANDA_ENVIRONMENT=practice`, `OANDA_API_KEY`, and `OANDA_ACCOUNT_ID`.
- The bot maps common symbols such as `XAUUSD` to `XAU_USD` and `EURUSD` to `EUR_USD`.

FXCM South Africa:
- Account opening: [FXCM ZA open account](https://www.fxcm.com/za/open-account/)
- FXCM’s South Africa page notes card, bank wire, Skrill, and Neteller funding routes and displays rand-equivalent deposit guidance.
- Set `BROKER=fxcm`, `FXCM_TOKEN`, and `FXCM_SERVER=demo` or `real`.

MetaTrader 5 brokers:
- Use `BROKER=mt5` plus `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, and optionally `MT5_PATH`.
- Exness ZAR accounts commonly use MT5 real servers following the `Exness-MT5Real*` pattern.
- HFM / HF Markets MT5 server requested for this configuration: `HFMarkets-Live 3`.
- Blackstone Futures is a South African broker with MT5 support; use the MT5 credentials and server name supplied in the client portal.

### MT5 Demo Testing With SA-Friendly Brokers

The bot works with any broker that gives you a MetaTrader 5 account. That includes RCG Markets, Exness, XM, HFM, Blackstone Futures, Deriv, IC Markets and many others. You do not connect the bot to the broker website directly; you create a demo account on the broker website, then use the MT5 login details in `.env`.

General MT5 demo process:

1. Open a demo account with the broker.
2. Choose MetaTrader 5, not MT4.
3. Copy the MT5 login number, password, and server name from the broker portal.
4. Install the broker's MT5 desktop terminal or the official MetaTrader 5 terminal.
5. Log into the demo account in MT5 first and confirm you can see demo balance and prices.
6. Put the same credentials into `.env`.
7. Keep `LIVE_TRADING=false` for local testing.
8. Switch to `LIVE_TRADING=true` only for demo execution after you have confirmed everything is correct.

RCG Markets:
- Official site: [RCG Markets](https://www.rcgmarkets.com/)
- Demo registration: [RCG Markets demo portal](https://portal.rcgmarkets.com/register-demo)
- RCG Markets advertises MT4/MT5 accounts and FSCA regulation on its official site.
- Example `.env`:

```env
BROKER=mt5
LIVE_TRADING=true
MT5_BROKER_PRESET=rcgmarkets
MT5_LOGIN=12345678
MT5_PASSWORD=your-demo-password
MT5_SERVER=RCGMarkets-Demo
```

Exness:
- Official site: [Exness](https://www.exness.com/)
- Exness says new Personal Areas include MT5 real and demo accounts, and demo accounts use virtual equity.
- Example `.env`:

```env
BROKER=mt5
LIVE_TRADING=true
MT5_BROKER_PRESET=exness_demo
MT5_LOGIN=12345678
MT5_PASSWORD=your-demo-password
MT5_SERVER=Exness-MT5Trial
```

If your Exness portal shows a different server such as `Exness-MT5Real` or `Exness-MT5Trial2`, use exactly what Exness shows.

XM:
- Official help: [XM demo and platform FAQ](https://www.xm.com/help-center/trading-accounts/faq-what-are-the-differences-between-a-demo-and-a-real-account)
- XM notes that multi-asset trading is available on MT5 accounts.
- Example `.env`:

```env
BROKER=mt5
LIVE_TRADING=true
MT5_BROKER_PRESET=xm_demo
MT5_LOGIN=12345678
MT5_PASSWORD=your-demo-password
MT5_SERVER=XMGlobal-Demo
```

HFM:
- Official MT5 page: [HFM MT5 WebTerminal](https://www.hfm.com/hf/platforms/mt5-webterminal)
- HFM provides MT5 WebTerminal and demo account access.
- Example `.env`:

```env
BROKER=mt5
LIVE_TRADING=true
MT5_BROKER_PRESET=hfm_demo
MT5_LOGIN=12345678
MT5_PASSWORD=your-demo-password
MT5_SERVER=HFMarkets-Demo
```

Generic MT5 broker:

```env
BROKER=mt5
LIVE_TRADING=true
MT5_BROKER_PRESET=generic
MT5_LOGIN=12345678
MT5_PASSWORD=your-demo-password
MT5_SERVER=Exact-Server-Name-From-Broker
```

The server name must match exactly, including spaces, hyphens, and capitalization. If MT5 desktop cannot log in, the Python bot cannot log in either.

## Safety and Compliance Controls

- `LIVE_TRADING=false` prevents real broker execution and uses dry-run order logging.
- Risk defaults to 1% of ZAR account balance per trade.
- Maximum daily loss is 3%; when reached, new trades are blocked.
- Maximum simultaneous open trades is 3.
- Minimum R:R is 1.5 based on TP1 versus stop loss.
- All times are handled in SAST with `Africa/Johannesburg`.

## Trading Pipeline

1. Flask accepts the TradingView webhook and responds immediately.
2. Processing continues asynchronously.
3. Session filter checks London, New York, gold Asian session, and SAST open/close buffers.
4. News filter blocks configured high-impact events from a CSV.
5. Duplicate filter enforces one trade per pair per four hours.
6. MTF checker fetches D1 and H4 data from yfinance and checks EMA bias.
7. Risk manager calculates ZAR risk and units.
8. Selected broker executes the order only when `LIVE_TRADING=true`.
9. SQLite trade journal and WhatsApp/email notifications are updated.

## News CSV Format

Set `NEWS_EVENTS_CSV` to a CSV file with:

```csv
timestamp,currency,title
2026-06-10T14:30:00+02:00,USD,US CPI
2026-06-12T11:00:00+02:00,ZAR,SARB statement
```

## Notes

The dashboard shows account balance, open trades, today’s P&L, win rate, weekly trade count, live prices for configured instruments, trade history, equity curve, and an emergency close button.
