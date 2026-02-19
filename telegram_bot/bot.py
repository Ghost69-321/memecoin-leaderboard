"""
bot.py – Telegram bot entry-point for the Base-chain volume-bump service.

Commands
--------
/start          – Welcome message and short how-to
/wallet         – Show (or generate) the user's dedicated Base wallet address
/balance        – Current ETH balance of the user's wallet
/bump <token_contract> <amount_eth>
                – Bump trading volume on the chosen token contract using
                  <amount_eth> ETH.  1% fee + gas is charged on top.
/withdraw <destination_address> <amount_eth>
                – Withdraw ETH from the bot wallet to any external address
/history        – Show the 5 most recent bump operations
/help           – Repeat the command reference

Environment variables required (see config.py for details):
  TELEGRAM_BOT_TOKEN
  BOT_MASTER_KEY
  FEE_RECIPIENT_ADDRESS
"""

import logging
from decimal import Decimal, InvalidOperation

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from web3 import Web3

import config
import storage
import transactions
import wallet

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s – %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── formatting helpers ────────────────────────────────────────────────────────

def _basescan_tx(tx_hash: str) -> str:
    return f"https://basescan.org/tx/{tx_hash}"


def _basescan_addr(address: str) -> str:
    return f"https://basescan.org/address/{address}"


def _escape(text: str) -> str:
    """Minimal HTML-safe escaping for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 <b>Base Volume Bump Bot</b>\n\n"
        "This bot lets you bump trading volume for any token on the Base chain.\n\n"
        "<b>How it works</b>\n"
        "1️⃣ /wallet – Get your dedicated deposit address\n"
        "2️⃣ Send ETH (Base) to that address\n"
        "3️⃣ /bump &lt;token_address&gt; &lt;amount_eth&gt; – Execute the bump\n"
        "    • Gas fees + <b>1% service fee</b> are deducted automatically\n"
        "4️⃣ /balance – Check your current balance\n"
        "5️⃣ /withdraw &lt;address&gt; &lt;amount_eth&gt; – Withdraw leftover ETH\n\n"
        "Type /help for the full command reference.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Command reference</b>\n\n"
        "/wallet – Show (or create) your Base deposit address\n"
        "/balance – Check ETH balance of your wallet\n"
        "/bump &lt;token_contract&gt; &lt;amount_eth&gt;\n"
        "    Swap <i>amount_eth</i> of ETH into the token to bump its volume.\n"
        "    1% fee + gas is charged on top of the amount.\n"
        "/withdraw &lt;destination_address&gt; &lt;amount_eth&gt;\n"
        "    Send ETH back to your own wallet.\n"
        "/history – Last 5 bump operations\n"
        "/help – This message\n\n"
        "⚠️ <b>Important</b>: Only send Base-network (L2) ETH to your deposit address.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    row = storage.get_user_wallet(user_id)

    if row:
        address = row["address"]
        await update.message.reply_text(
            f"💳 <b>Your Base deposit address</b>\n\n"
            f"<code>{_escape(address)}</code>\n\n"
            f"<a href='{_basescan_addr(address)}'>View on BaseScan</a>\n\n"
            "Send Base-network ETH to this address, then use /bump.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    # Generate a new wallet
    address, private_key_hex = wallet.generate_wallet()
    encrypted = wallet.encrypt_private_key(private_key_hex, user_id)
    storage.save_user_wallet(user_id, address, encrypted)
    logger.info("Generated wallet for user %d: %s", user_id, address)

    await update.message.reply_text(
        f"✅ <b>New wallet created!</b>\n\n"
        f"💳 <b>Deposit address (Base network):</b>\n"
        f"<code>{_escape(address)}</code>\n\n"
        f"<a href='{_basescan_addr(address)}'>View on BaseScan</a>\n\n"
        "⚠️ Only send <b>Base-network ETH</b> to this address.\n"
        "Once your deposit arrives, use /bump to start bumping volume.",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    row = storage.get_user_wallet(user_id)
    if not row:
        await update.message.reply_text(
            "You don't have a wallet yet. Use /wallet to create one."
        )
        return

    address = row["address"]
    try:
        balance_eth = transactions.get_balance_eth(address)
    except Exception as exc:
        logger.error("Balance check failed for user %d: %s", user_id, exc)
        await update.message.reply_text(
            "⚠️ Could not fetch balance right now. Please try again shortly."
        )
        return

    await update.message.reply_text(
        f"💰 <b>Wallet balance</b>\n\n"
        f"Address: <code>{_escape(address)}</code>\n"
        f"Balance: <b>{balance_eth:.6f} ETH</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_bump(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args or []

    if len(args) != 2:
        await update.message.reply_text(
            "Usage: /bump <token_contract> <amount_eth>\n"
            "Example: /bump 0xABC...123 0.01"
        )
        return

    token_address_raw, amount_eth_str = args

    # ── validate token address ────────────────────────────────────────────
    if not Web3.is_address(token_address_raw):
        await update.message.reply_text(
            "❌ Invalid token contract address. Please provide a valid EVM address."
        )
        return
    token_address = Web3.to_checksum_address(token_address_raw)

    # ── validate amount ───────────────────────────────────────────────────
    try:
        amount_eth = Decimal(amount_eth_str)
        if amount_eth <= 0:
            raise ValueError("amount must be positive")
    except (InvalidOperation, ValueError):
        await update.message.reply_text(
            "❌ Invalid amount. Provide a positive number, e.g. 0.01"
        )
        return

    amount_wei = Web3.to_wei(amount_eth, "ether")

    # ── wallet lookup ─────────────────────────────────────────────────────
    row = storage.get_user_wallet(user_id)
    if not row:
        await update.message.reply_text(
            "You don't have a wallet yet. Use /wallet to create one, then deposit ETH."
        )
        return

    address       = row["address"]
    encrypted_key = row["encrypted_key"]

    # ── cost estimation ───────────────────────────────────────────────────
    try:
        fee_wei, gas_cost_wei, total_required_wei = (
            transactions.estimate_total_cost_wei(amount_wei)
        )
    except Exception as exc:
        logger.error("Cost estimation failed for user %d: %s", user_id, exc)
        await update.message.reply_text(
            "⚠️ Could not estimate costs. Please try again shortly."
        )
        return

    fee_eth      = float(Web3.from_wei(fee_wei, "ether"))
    gas_cost_eth = float(Web3.from_wei(gas_cost_wei, "ether"))
    total_eth    = float(Web3.from_wei(total_required_wei, "ether"))

    # ── balance check ─────────────────────────────────────────────────────
    try:
        balance_wei = transactions.get_balance_wei(address)
    except Exception as exc:
        logger.error("Balance check failed for user %d: %s", user_id, exc)
        await update.message.reply_text(
            "⚠️ Could not fetch balance. Please try again shortly."
        )
        return

    if balance_wei < total_required_wei:
        balance_eth_val = float(Web3.from_wei(balance_wei, "ether"))
        await update.message.reply_text(
            f"❌ <b>Insufficient balance</b>\n\n"
            f"Available:  <b>{balance_eth_val:.6f} ETH</b>\n"
            f"Required:   <b>{total_eth:.6f} ETH</b>\n"
            f"  • Bump:   {float(amount_eth):.6f} ETH\n"
            f"  • Fee:    {fee_eth:.6f} ETH (1%)\n"
            f"  • Gas:    ~{gas_cost_eth:.6f} ETH\n\n"
            f"Please deposit more ETH to <code>{_escape(address)}</code> and try again.",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── validate contract ─────────────────────────────────────────────────
    try:
        symbol = transactions.validate_token_contract(token_address)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {_escape(str(exc))}", parse_mode=ParseMode.HTML)
        return
    except Exception as exc:
        logger.error("Contract validation failed for user %d: %s", user_id, exc)
        await update.message.reply_text(
            "⚠️ Could not validate the token contract. Please try again."
        )
        return

    # ── confirm to user ───────────────────────────────────────────────────
    await update.message.reply_text(
        f"⏳ <b>Executing volume bump…</b>\n\n"
        f"Token:   <code>{_escape(token_address)}</code>  ({_escape(symbol)})\n"
        f"Bump:    {float(amount_eth):.6f} ETH\n"
        f"Fee:     {fee_eth:.6f} ETH (1%)\n"
        f"Gas est: ~{gas_cost_eth:.6f} ETH\n\n"
        "Please wait…",
        parse_mode=ParseMode.HTML,
    )

    # ── decrypt key ───────────────────────────────────────────────────────
    try:
        private_key_hex = wallet.decrypt_private_key(encrypted_key, user_id)
    except Exception as exc:
        logger.error("Key decryption failed for user %d: %s", user_id, exc)
        await update.message.reply_text(
            "❌ Internal error: could not decrypt wallet key. Contact support."
        )
        return

    # ── send fee ──────────────────────────────────────────────────────────
    fee_tx_hash: str | None = None
    try:
        fee_tx_hash = transactions.send_fee(private_key_hex, address, fee_wei)
        logger.info("Fee tx sent for user %d: %s", user_id, fee_tx_hash)
    except Exception as exc:
        logger.error("Fee tx failed for user %d: %s", user_id, exc)
        storage.save_bump_record(
            user_id, token_address, float(amount_eth), fee_eth,
            None, None, "fee_failed"
        )
        await update.message.reply_text(
            f"❌ Failed to send service fee: {_escape(str(exc))}\n\n"
            "The bump was cancelled. No funds were moved.",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── execute swap ──────────────────────────────────────────────────────
    swap_tx_hash: str | None = None
    try:
        swap_tx_hash = transactions.execute_bump_swap(
            private_key_hex, address, token_address, amount_wei
        )
        logger.info("Swap tx sent for user %d: %s", user_id, swap_tx_hash)
    except Exception as exc:
        logger.error("Swap tx failed for user %d: %s", user_id, exc)
        storage.save_bump_record(
            user_id, token_address, float(amount_eth), fee_eth,
            fee_tx_hash, None, "swap_failed"
        )
        await update.message.reply_text(
            f"⚠️ Fee was sent, but the swap failed: {_escape(str(exc))}\n\n"
            f"Fee tx: <a href='{_basescan_tx(fee_tx_hash)}'>{fee_tx_hash[:18]}…</a>\n\n"
            "Please check the token contract address and try again.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    # ── success ───────────────────────────────────────────────────────────
    storage.save_bump_record(
        user_id, token_address, float(amount_eth), fee_eth,
        fee_tx_hash, swap_tx_hash, "success"
    )
    await update.message.reply_text(
        f"✅ <b>Volume bump successful!</b>\n\n"
        f"Token:   <code>{_escape(token_address)}</code>  ({_escape(symbol)})\n"
        f"Bumped:  {float(amount_eth):.6f} ETH\n"
        f"Fee:     {fee_eth:.6f} ETH (1%)\n\n"
        f"🔗 <a href='{_basescan_tx(swap_tx_hash)}'>View swap on BaseScan</a>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    args = context.args or []

    if len(args) != 2:
        await update.message.reply_text(
            "Usage: /withdraw <destination_address> <amount_eth>\n"
            "Example: /withdraw 0xYourAddress 0.05"
        )
        return

    to_address_raw, amount_eth_str = args

    if not Web3.is_address(to_address_raw):
        await update.message.reply_text("❌ Invalid destination address.")
        return
    to_address = Web3.to_checksum_address(to_address_raw)

    try:
        amount_eth = Decimal(amount_eth_str)
        if amount_eth <= 0:
            raise ValueError
    except (InvalidOperation, ValueError):
        await update.message.reply_text(
            "❌ Invalid amount. Provide a positive number, e.g. 0.05"
        )
        return

    amount_wei = Web3.to_wei(amount_eth, "ether")

    row = storage.get_user_wallet(user_id)
    if not row:
        await update.message.reply_text(
            "You don't have a wallet yet. Use /wallet to create one."
        )
        return

    address       = row["address"]
    encrypted_key = row["encrypted_key"]

    try:
        private_key_hex = wallet.decrypt_private_key(encrypted_key, user_id)
    except Exception as exc:
        logger.error("Key decryption failed for user %d: %s", user_id, exc)
        await update.message.reply_text(
            "❌ Internal error: could not decrypt wallet key. Contact support."
        )
        return

    await update.message.reply_text("⏳ Sending withdrawal transaction…")

    try:
        tx_hash = transactions.execute_withdraw(
            private_key_hex, address, to_address, amount_wei
        )
    except ValueError as exc:
        await update.message.reply_text(f"❌ {_escape(str(exc))}", parse_mode=ParseMode.HTML)
        return
    except Exception as exc:
        logger.error("Withdraw failed for user %d: %s", user_id, exc)
        await update.message.reply_text(
            f"❌ Withdrawal failed: {_escape(str(exc))}", parse_mode=ParseMode.HTML
        )
        return

    await update.message.reply_text(
        f"✅ <b>Withdrawal sent!</b>\n\n"
        f"Amount: {float(amount_eth):.6f} ETH\n"
        f"To:     <code>{_escape(to_address)}</code>\n\n"
        f"🔗 <a href='{_basescan_tx(tx_hash)}'>View on BaseScan</a>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    records = storage.get_bump_history(user_id, limit=5)

    if not records:
        await update.message.reply_text(
            "No bump history yet. Use /bump to get started."
        )
        return

    lines = ["<b>Last 5 bump operations</b>\n"]
    for rec in records:
        status_emoji = "✅" if rec["status"] == "success" else "❌"
        token_short  = rec["token_address"][:10] + "…"
        tx_link = (
            f"<a href='{_basescan_tx(rec['swap_tx_hash'])}'>tx</a>"
            if rec["swap_tx_hash"]
            else "—"
        )
        lines.append(
            f"{status_emoji} {_escape(rec['created_at'][:16])} | "
            f"Token: <code>{_escape(token_short)}</code> | "
            f"{rec['amount_eth']:.4f} ETH | {tx_link}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ── error handler ─────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "⚠️ An unexpected error occurred. Please try again later."
        )


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env var is not set")
    if not config.BOT_MASTER_KEY:
        raise RuntimeError("BOT_MASTER_KEY env var is not set")
    if not config.FEE_RECIPIENT_ADDRESS:
        raise RuntimeError("FEE_RECIPIENT_ADDRESS env var is not set")

    storage.init_db()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("wallet",   cmd_wallet))
    app.add_handler(CommandHandler("balance",  cmd_balance))
    app.add_handler(CommandHandler("bump",     cmd_bump))
    app.add_handler(CommandHandler("withdraw", cmd_withdraw))
    app.add_handler(CommandHandler("history",  cmd_history))

    app.add_error_handler(error_handler)

    logger.info("Bot starting (long-polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
