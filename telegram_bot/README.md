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

## Quick-start (Docker — recommended)

### Option A – Pull pre-built image from GHCR (fastest)

```bash
# On your server (Linux VPS / cloud VM):

# 1. Download the compose file
mkdir bump-bot && cd bump-bot
curl -O https://raw.githubusercontent.com/Ghost69-321/memecoin-leaderboard/main/telegram_bot/docker-compose.yml
curl -O https://raw.githubusercontent.com/Ghost69-321/memecoin-leaderboard/main/telegram_bot/.env.example

# 2. Fill in your credentials
cp .env.example .env
nano .env   # set TELEGRAM_BOT_TOKEN and BOT_MASTER_KEY

# 3. Pull and run
docker compose pull
docker compose up -d
```

### Option B – Build from source

```bash
git clone https://github.com/Ghost69-321/memecoin-leaderboard.git
cd memecoin-leaderboard/telegram_bot

cp .env.example .env
nano .env   # set TELEGRAM_BOT_TOKEN and BOT_MASTER_KEY

# Comment out 'image:' and uncomment 'build:' in docker-compose.yml, then:
docker compose up -d --build
```

The SQLite database is persisted in a Docker volume (`bot_data`) so data
survives container restarts and upgrades.

### Useful commands

```bash
docker compose logs -f          # stream logs
docker compose restart          # restart after config change
docker compose pull && docker compose up -d   # upgrade to latest image
docker compose down             # stop (data is safe in the volume)
```

---

## Manual Setup (Python)

### 1. Install dependencies

```bash
cd telegram_bot
pip install -r requirements.txt
```

### 2. Set environment variables

Copy `.env.example` to `.env` and fill in the values:

```dotenv
# Required
TELEGRAM_BOT_TOKEN=7123456789:AAFxxxx
BOT_MASTER_KEY=a-long-random-secret-key-at-least-32-chars

# Optional – defaults to the owner's treasury address
# FEE_RECIPIENT_ADDRESS=0x5D47D3388504824408dBf8943fd6711fEF3cBEfe

# Optional
# BASE_RPC_URL=https://mainnet.base.org
# DATABASE_PATH=bot_data.db
```

> **Fee address**: All 1% fees default to the owner's treasury wallet
> `0x5D47D3388504824408dBf8943fd6711fEF3cBEfe` on Base.

> **Security**: `BOT_MASTER_KEY` encrypts every user's private key.  Choose a
> high-entropy random string, keep it secret, and **back it up** — losing it
> means losing access to all stored wallets.

### 3. Run

```bash
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
   - Both transactions are signed locally — the private key never leaves the
     process.
4. Gas fees are paid from the user's wallet and estimated before submission.

---

## Security Considerations

- Private keys are encrypted at rest using **Fernet** (AES-128-CBC +
  HMAC-SHA256). Each user gets a unique key derived via HKDF-SHA256 from
  `BOT_MASTER_KEY`.
- The database (`bot_data.db`) contains only encrypted key material.
- **Back up `BOT_MASTER_KEY`** — it is required to decrypt stored keys.
- Run the bot in a trusted environment (VPS, container) with restricted
  file-system access.

---

## Deployment (systemd alternative)

```ini
[Unit]
Description=Base Volume Bump Telegram Bot
After=network.target

[Service]
WorkingDirectory=/opt/bump-bot/telegram_bot
EnvironmentFile=/opt/bump-bot/telegram_bot/.env
ExecStart=/usr/bin/python3 bot.py
Restart=on-failure
User=botuser

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now bump-bot
```

