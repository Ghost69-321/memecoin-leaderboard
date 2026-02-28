"""
transactions.py – Base-chain transaction helpers.

Flow for a single bump operation
---------------------------------
1. Verify the token address is a valid ERC-20 contract.
2. Calculate fee = bump_amount * FEE_PERCENT.
3. Estimate gas for fee transfer (ETH → FEE_RECIPIENT_ADDRESS) and for the
   Uniswap V3 exactInputSingle swap.
4. Verify the user wallet holds enough ETH to cover all of the above.
5. Send the fee transfer and wait for confirmation.
6. Send the swap and wait for confirmation.

The swap uses Uniswap V3 SwapRouter02 (deployed on Base at
0x2626664c2603336E57B271c5C0b26F421741e481).  ETH is sent as *msg.value*;
the router wraps it to WETH internally because tokenIn = WETH address.
"""

from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.exceptions import ContractLogicError

from config import (
    BASE_CHAIN_ID,
    BASE_RPC_URL,
    FEE_PERCENT,
    FEE_RECIPIENT_ADDRESS,
    GAS_LIMIT_SWAP,
    GAS_LIMIT_TRANSFER,
    UNISWAP_V3_ROUTER,
    WETH_ADDRESS,
)

# ── ABI fragments ─────────────────────────────────────────────────────────────

# Minimal ERC-20 ABI – only what we need
_ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]

# Uniswap V3 SwapRouter02 – exactInputSingle (no deadline field in v2 router)
_ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn",             "type": "address"},
                    {"internalType": "address", "name": "tokenOut",            "type": "address"},
                    {"internalType": "uint24",  "name": "fee",                 "type": "uint24"},
                    {"internalType": "address", "name": "recipient",           "type": "address"},
                    {"internalType": "uint256", "name": "amountIn",            "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMinimum",    "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96",   "type": "uint160"},
                ],
                "internalType": "struct ISwapRouter.ExactInputSingleParams",
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    }
]

# ── helpers ───────────────────────────────────────────────────────────────────

def _get_web3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to Base RPC at {BASE_RPC_URL}")
    return w3


def get_balance_wei(address: str) -> int:
    """Return the ETH balance (in wei) for *address*."""
    w3 = _get_web3()
    return w3.eth.get_balance(Web3.to_checksum_address(address))


def get_balance_eth(address: str) -> float:
    """Return the ETH balance (in ETH, float) for *address*."""
    return float(Web3.from_wei(get_balance_wei(address), "ether"))


def validate_token_contract(token_address: str) -> str:
    """Check that *token_address* is a deployed ERC-20 contract.

    Returns the token symbol on success; raises *ValueError* on failure.
    """
    w3 = _get_web3()
    checksum = Web3.to_checksum_address(token_address)
    code = w3.eth.get_code(checksum)
    if code in (b"", b"0x"):
        raise ValueError(f"No contract deployed at {token_address}")
    try:
        contract = w3.eth.contract(address=checksum, abi=_ERC20_ABI)
        symbol = contract.functions.symbol().call()
        return symbol
    except Exception:
        # Not every ERC-20 exposes symbol() – still allow the bump
        return "UNKNOWN"


def estimate_total_cost_wei(bump_amount_wei: int) -> tuple[int, int, int]:
    """Return (fee_wei, estimated_gas_cost_wei, total_required_wei).

    *bump_amount_wei* is the ETH that will go into the swap.
    """
    w3 = _get_web3()
    gas_price = w3.eth.gas_price
    fee_wei = int(bump_amount_wei * FEE_PERCENT)
    gas_cost = gas_price * (GAS_LIMIT_TRANSFER + GAS_LIMIT_SWAP)
    total = bump_amount_wei + fee_wei + gas_cost
    return fee_wei, gas_cost, total


def _send_and_wait(w3: Web3, signed_tx) -> dict:
    """Broadcast a signed transaction and wait for its receipt."""
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] != 1:
        raise RuntimeError(
            f"Transaction {tx_hash.hex()} was reverted on-chain"
        )
    return receipt


def send_fee(
    private_key_hex: str,
    from_address: str,
    fee_amount_wei: int,
) -> str:
    """Send *fee_amount_wei* to FEE_RECIPIENT_ADDRESS. Returns tx hash."""
    w3 = _get_web3()
    account: LocalAccount = Account.from_key(private_key_hex)
    nonce = w3.eth.get_transaction_count(
        Web3.to_checksum_address(from_address), "pending"
    )
    gas_price = w3.eth.gas_price
    tx: dict = {
        "to":       Web3.to_checksum_address(FEE_RECIPIENT_ADDRESS),
        "value":    fee_amount_wei,
        "gas":      GAS_LIMIT_TRANSFER,
        "gasPrice": gas_price,
        "nonce":    nonce,
        "chainId":  BASE_CHAIN_ID,
    }
    signed = account.sign_transaction(tx)
    receipt = _send_and_wait(w3, signed)
    return receipt["transactionHash"].hex()


def execute_bump_swap(
    private_key_hex: str,
    from_address: str,
    token_address: str,
    eth_amount_wei: int,
    fee_tier: int = 3000,
) -> str:
    """Swap *eth_amount_wei* of ETH → *token_address* on Uniswap V3.

    Returns the swap tx hash.  Tries fee tiers 3000 → 500 → 10000 if needed.
    """
    w3 = _get_web3()
    account: LocalAccount = Account.from_key(private_key_hex)
    router = w3.eth.contract(
        address=Web3.to_checksum_address(UNISWAP_V3_ROUTER),
        abi=_ROUTER_ABI,
    )
    checksum_token = Web3.to_checksum_address(token_address)
    checksum_from  = Web3.to_checksum_address(from_address)

    fee_tiers_to_try = [fee_tier, 500, 10_000, 100]
    last_error: Optional[Exception] = None

    for tier in fee_tiers_to_try:
        params = (
            Web3.to_checksum_address(WETH_ADDRESS),  # tokenIn  (WETH)
            checksum_token,                           # tokenOut
            tier,                                     # fee tier
            checksum_from,                            # recipient
            eth_amount_wei,                           # amountIn
            # amountOutMinimum = 0: volume-bump intent accepts any output;
            # users acknowledge this may be subject to MEV/sandwich attacks.
            0,                                        # amountOutMinimum
            0,                                        # sqrtPriceLimitX96
        )
        nonce = w3.eth.get_transaction_count(checksum_from, "pending")
        gas_price = w3.eth.gas_price
        try:
            tx = router.functions.exactInputSingle(params).build_transaction(
                {
                    "from":     checksum_from,
                    "value":    eth_amount_wei,
                    "gas":      GAS_LIMIT_SWAP,
                    "gasPrice": gas_price,
                    "nonce":    nonce,
                    "chainId":  BASE_CHAIN_ID,
                }
            )
            signed = account.sign_transaction(tx)
            receipt = _send_and_wait(w3, signed)
            return receipt["transactionHash"].hex()
        except (ContractLogicError, RuntimeError, Exception) as exc:
            last_error = exc
            continue

    raise RuntimeError(
        f"Swap failed across all fee tiers: {last_error}"
    ) from last_error


def execute_withdraw(
    private_key_hex: str,
    from_address: str,
    to_address: str,
    amount_wei: int,
) -> str:
    """Transfer *amount_wei* ETH from the user's bot wallet to *to_address*.

    The gas cost is deducted from the user's balance on top of *amount_wei*.
    """
    w3 = _get_web3()
    account: LocalAccount = Account.from_key(private_key_hex)
    gas_price = w3.eth.gas_price
    gas_cost  = gas_price * GAS_LIMIT_TRANSFER
    balance   = w3.eth.get_balance(Web3.to_checksum_address(from_address))

    if balance < amount_wei + gas_cost:
        raise ValueError(
            f"Insufficient balance: have {Web3.from_wei(balance, 'ether'):.6f} ETH, "
            f"need {Web3.from_wei(amount_wei + gas_cost, 'ether'):.6f} ETH "
            f"(amount + gas)"
        )

    nonce = w3.eth.get_transaction_count(
        Web3.to_checksum_address(from_address), "pending"
    )
    tx: dict = {
        "to":       Web3.to_checksum_address(to_address),
        "value":    amount_wei,
        "gas":      GAS_LIMIT_TRANSFER,
        "gasPrice": gas_price,
        "nonce":    nonce,
        "chainId":  BASE_CHAIN_ID,
    }
    signed = account.sign_transaction(tx)
    receipt = _send_and_wait(w3, signed)
    return receipt["transactionHash"].hex()
