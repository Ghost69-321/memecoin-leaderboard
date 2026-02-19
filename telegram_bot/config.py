"""
config.py – centralised settings loaded from environment variables.

Required env vars:
  TELEGRAM_BOT_TOKEN       – Token from @BotFather
  BOT_MASTER_KEY           – Random secret (≥32 chars) used to derive per-user
                             encryption keys for stored private keys

Optional env vars:
  FEE_RECIPIENT_ADDRESS    – Base (EVM) 0x address that receives the 1% fee.
                             Defaults to the owner's treasury address below.
  BASE_RPC_URL             – defaults to the public Base mainnet endpoint
  DATABASE_PATH            – defaults to ./bot_data.db
"""
import os

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# ── Security ──────────────────────────────────────────────────────────────────
# Must be set before running the bot.  Used to derive per-user Fernet keys.
BOT_MASTER_KEY: str = os.environ.get("BOT_MASTER_KEY", "")

# ── Fee ───────────────────────────────────────────────────────────────────────
# Owner's treasury wallet on Base (EVM).  All 1% fees are sent here.
# Can be overridden with the FEE_RECIPIENT_ADDRESS env var.
TREASURY_WALLET_ID: str = "CfyjfkdfVchdvtKyPbBxBoScfSUPBVMwnGbYeXBs5uKw"
TREASURY_EVM_ADDRESS: str = "0x5D47D3388504824408dBf8943fd6711fEF3cBEfe"

FEE_RECIPIENT_ADDRESS: str = os.environ.get(
    "FEE_RECIPIENT_ADDRESS", TREASURY_EVM_ADDRESS
)
FEE_PERCENT: float = 0.01  # 1%

# ── Base network ──────────────────────────────────────────────────────────────
BASE_RPC_URL: str = os.environ.get(
    "BASE_RPC_URL", "https://mainnet.base.org"
)
BASE_CHAIN_ID: int = 8453

# Canonical WETH address on Base (same as the official bridged WETH)
WETH_ADDRESS: str = "0x4200000000000000000000000000000000000006"

# Uniswap V3 SwapRouter02 deployed on Base
UNISWAP_V3_ROUTER: str = "0x2626664c2603336E57B271c5C0b26F421741e481"

# Gas limits (conservative upper-bounds)
GAS_LIMIT_TRANSFER: int = 21_000
GAS_LIMIT_SWAP: int = 350_000

# ── Storage ───────────────────────────────────────────────────────────────────
DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "bot_data.db")
