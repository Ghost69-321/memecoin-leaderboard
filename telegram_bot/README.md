# Base-Chain Volume Bump Telegram Bot

A Telegram bot that lets users deposit ETH on the **Base** network into a
dedicated wallet and bump the trading volume of any ERC-20 token by executing
a swap on Uniswap V3.  A 1% service fee is deducted automatically; gas costs
are covered by the user's deposited ETH.

---

## Features

| Command | Description |
|---|---|
| `/wallet` | Create or view your Base deposit address |
| `/balance` | Check ETH balance of your wallet |
| `/bump <token> <amount_eth>` | Swap ETH → token to bump volume (1% fee + gas) |
| `/withdraw <address> <amount_eth>` | Withdraw leftover ETH to any address |
| `/history` | View last 5 bump operations |
| `/help` | Command reference |

---

## Requirements

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Base-network RPC endpoint (the default `https://mainnet.base.org` works)
- An EVM address to receive the 1% fee

---

## Setup

### 1. Install dependencies

```bash
cd telegram_bot
pip install -r requirements.txt
```

### 2. Set environment variables

Create a `.env` file (or export them in your shell):

```dotenv
# Required
TELEGRAM_BOT_TOKEN=7123456789:AAFxxxx
BOT_MASTER_KEY=a-long-random-secret-key-at-least-32-chars

# Optional – defaults to the owner's treasury address below
# FEE_RECIPIENT_ADDRESS=0x5D47D3388504824408dBf8943fd6711fEF3cBEfe

# Optional (shown with defaults)
BASE_RPC_URL=https://mainnet.base.org
DATABASE_PATH=bot_data.db
```

> **Fee address**: All 1% fees default to the owner's treasury wallet
> `0x5D47D3388504824408dBf8943fd6711fEF3cBEfe` on Base.
> Override with the `FEE_RECIPIENT_ADDRESS` env var if needed.

> **Security note**: `BOT_MASTER_KEY` is used to derive per-user encryption
> keys for stored private keys.  Choose a high-entropy random string and keep
> it secret.  Losing it means losing access to all stored wallets.

### 3. Run

```bash
python bot.py
```

Or with `python-dotenv` for automatic `.env` loading:

```bash
pip install python-dotenv
python -c "from dotenv import load_dotenv; load_dotenv()" && python bot.py
# or simply prefix:
env $(cat .env | xargs) python bot.py
```

---

## How Bumping Works

1. A fresh Ethereum keypair is generated for each Telegram user and the
   private key is stored **encrypted** in a local SQLite database.
2. The user deposits Base-network ETH to their address.
3. On `/bump`, the bot:
   - Sends **1% of the bump amount** as a fee to `FEE_RECIPIENT_ADDRESS`.
   - Calls `exactInputSingle` on the Uniswap V3 SwapRouter02 (deployed on
     Base at `0x2626664c2603336E57B271c5C0b26F421741e481`), swapping ETH
     (wrapped internally) for the target token.
   - Both transactions are signed locally – the private key never leaves the
     process.
4. Gas fees are paid from the user's wallet and are estimated before the
   transaction is sent.

---

## Security Considerations

- Private keys are encrypted at rest using **Fernet** (AES-128-CBC +
  HMAC-SHA256). Fernet keys are 32 bytes (256-bit) encoded as URL-safe
  base64; the AES cipher itself uses 128-bit keys as per the Fernet spec.
  Each user gets a unique key derived via HKDF-SHA256 from `BOT_MASTER_KEY`.
- The database (`bot_data.db`) contains only encrypted key material.
- **Back up `BOT_MASTER_KEY`** – it is required to decrypt stored keys.
- Run the bot in a trusted environment (VPS, container) with restricted
  file-system access.

---

## Deployment (systemd)

```ini
[Unit]
Description=Base Volume Bump Telegram Bot
After=network.target

[Service]
WorkingDirectory=/opt/bump-bot/telegram_bot
EnvironmentFile=/opt/bump-bot/.env
ExecStart=/usr/bin/python3 bot.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now bump-bot
```
