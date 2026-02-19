"""
storage.py – SQLite persistence for user wallets and bump history.

Tables
------
user_wallets   – one row per Telegram user (address + encrypted private key)
bump_history   – audit trail of every bump operation attempted
"""
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional

from config import DATABASE_PATH


# ── helpers ──────────────────────────────────────────────────────────────────

@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── schema ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they do not already exist."""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_wallets (
                user_id      INTEGER PRIMARY KEY,
                address      TEXT    NOT NULL,
                encrypted_key TEXT   NOT NULL,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bump_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                token_address TEXT    NOT NULL,
                amount_eth    REAL    NOT NULL,
                fee_eth       REAL    NOT NULL,
                fee_tx_hash   TEXT,
                swap_tx_hash  TEXT,
                status        TEXT    NOT NULL DEFAULT 'pending',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


# ── user_wallets ──────────────────────────────────────────────────────────────

def get_user_wallet(user_id: int) -> Optional[sqlite3.Row]:
    """Return the wallet row for *user_id*, or *None* if not found."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT address, encrypted_key FROM user_wallets WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def save_user_wallet(user_id: int, address: str, encrypted_key: str) -> None:
    """Insert or replace the wallet record for *user_id*."""
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_wallets (user_id, address, encrypted_key)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                address       = excluded.address,
                encrypted_key = excluded.encrypted_key
            """,
            (user_id, address, encrypted_key),
        )


# ── bump_history ──────────────────────────────────────────────────────────────

def save_bump_record(
    user_id: int,
    token_address: str,
    amount_eth: float,
    fee_eth: float,
    fee_tx_hash: Optional[str],
    swap_tx_hash: Optional[str],
    status: str,
) -> None:
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO bump_history
                (user_id, token_address, amount_eth, fee_eth,
                 fee_tx_hash, swap_tx_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                token_address,
                amount_eth,
                fee_eth,
                fee_tx_hash,
                swap_tx_hash,
                status,
            ),
        )


def get_bump_history(user_id: int, limit: int = 5) -> list[sqlite3.Row]:
    """Return the *limit* most recent bump records for *user_id*."""
    with _get_conn() as conn:
        return conn.execute(
            """
            SELECT token_address, amount_eth, fee_eth,
                   swap_tx_hash, status, created_at
            FROM   bump_history
            WHERE  user_id = ?
            ORDER  BY created_at DESC
            LIMIT  ?
            """,
            (user_id, limit),
        ).fetchall()
