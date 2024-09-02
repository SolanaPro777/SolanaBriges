import base64
import based58
import httpx
import asyncio

from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from solana.publickey import PublicKey
from solana.keypair import Keypair
from solana.transaction import Transaction
from solana.system_program import SYS_PROGRAM_ID
from spl.token.constants import ASSOCIATED_TOKEN_PROGRAM_ID, TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address, create_associated_token_account
from solana.rpc.core import RPCException

from usdc_swaps import route_map

SOLANA_CLIENT = AsyncClient('https://api.mainnet-beta.solana.com')
WALLET = Keypair.from_secret_key(based58.b58decode('secret_key'.encode("ascii")))
INPUT_USDC_AMOUNT = 5000000
USDC_BASE = 1000000


def get_mint(index, indexedRouteMap):
    return indexedRouteMap['mintKeys'][int(index)]


def get_route_map():
    return route_map


async def get_coin_quote(INPUT_MINT, TOKEN_MINT, amount):
    # Get PAIR QUOTE
    url = f"https://quote-api.jup.ag/v1/quote?inputMint={INPUT_MINT}&outputMint={TOKEN_MINT}&amount={amount}&slippage=0.5"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=15.0)
    return response.json()

async def get_coin_swap_quote(route):
    # Get PAIR SWAP QUOTE
    async with httpx.AsyncClient() as client:
        response = await client.post(
        url="https://quote-api.jup.ag/v1/swap",
        json={
        "route": route,
        "userPublicKey": str(WALLET.public_key),
        "wrapUnwrapSOL": False
        },
        timeout=15.0
        )
    return response.json()

async def execute_transaction(transactions):
    # Execute transactions
    opts = TxOpts(skip_preflight=True, max_retries=11)
    for tx_name, raw_transaction in transactions.items():
        if raw_transaction:
            try:
                transaction = Transaction.deserialize(base64.b64decode(raw_transaction))
                await SOLANA_CLIENT.send_transaction(transaction, WALLET, opts=opts)
            except Exception as e:
                print("Error occurred at ex tx: ", str(e))
                return str(e)

async def serialized_swap_transaction(usdcToTokenRoute, tokenToUsdcRoute):
    if usdcToTokenRoute:
        try:
            usdcToTokenTransaction = await get_coin_swap_quote(usdcToTokenRoute)
            await execute_transaction(usdcToTokenTransaction)
        except Exception as e:
            print("Error occurred at execution usdctotoken: ", str(e))
            return str(e)

    if tokenToUsdcRoute:
        try:
            tokenToUsdcTransaction = await get_coin_swap_quote(tokenToUsdcRoute)
            await execute_transaction(tokenToUsdcTransaction)
        except Exception as e:
            print("Error occurred at execution tokentousdc: ", str(e))
            return str(e)


async def _create_associated_token_account(token):
    token_pubkey = PublicKey(token)
    wallet_pubkey = WALLET.public_key

    # Get the associated token account address
    token_associated_account = get_associated_token_address(wallet_pubkey, token_pubkey)
    token_associated_account_pubkey = PublicKey(token_associated_account)

    opts = TxOpts(skip_preflight=True, max_retries=11)

    # Check if the associated token account already exists
    ata_info = await SOLANA_CLIENT.get_account_info(token_associated_account_pubkey)
    if not ata_info.get('result', {}).get('value'):
        try:
            # Create instruction to create the associated token account
            instruction = create_associated_token_account(
                wallet_pubkey,
                wallet_pubkey,
                token_pubkey
            )
            txn = Transaction().add(instruction)
            recent_blockhash = await SOLANA_CLIENT.get_recent_blockhash()
            txn.recent_blockhash = recent_blockhash['result']['value']['blockhash']

            # Send the transaction
            await SOLANA_CLIENT.send_transaction(txn, WALLET, opts=opts)
            print(f"Created associated token account: {token_associated_account_pubkey}")
        except RPCException as e:
            print("RPC error occurred while creating ATA:", e)
            return e
        except Exception as e:
            print("Error occurred while creating ATA:", str(e))
            return e
    else:
        print("Associated token account already exists:", token_associated_account_pubkey)


async def swap(input, generatedRouteMap):
    # Check for any possible ARB opportunities
    while True:
        for token in generatedRouteMap[:150]:
            usdcToToken = await get_coin_quote(
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
                token,
                input
            )
            if usdcToToken.get('data'):
                tokenToUsdc = await get_coin_quote(
                    token,
                    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
                    usdcToToken.get('data')[0].get('otherAmountThreshold')
                )

                if tokenToUsdc.get('data'):
                    if tokenToUsdc.get('data')[0].get('otherAmountThreshold') > input:
                        await _create_associated_token_account(token)
                        await serialized_swap_transaction(usdcToToken.get('data')[0], tokenToUsdc.get('data')[0])
                        profit = tokenToUsdc.get('data')[0].get('otherAmountThreshold') - input
                        print("Approx Profit made: ", profit / USDC_BASE)


if __name__ == '__main__':
    generatedRouteMap = get_route_map()
    asyncio.run(swap(INPUT_USDC_AMOUNT, generatedRouteMap))