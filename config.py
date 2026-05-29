import os

CONTRACT_ADDRESS = "0xa4a2e2ca3fbfe21aed83471d28b6f65a233c6e00".lower()

CHAIN = "base"
ALCHEMY_PRICE_NETWORK = "base-mainnet"
VIRTUAL_ADDRESS = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b".lower()
TIBBIR_VIRTUAL_PAIR_ADDRESS = "0x0c3b466104545efa096b8f944c1e524e1d0d4888".lower()

REORG_BUFFER = 200

MAX_COUNT_HEX = "0x3e8"  # 1000 per request

GCS_BUCKET = os.environ.get("TIBBIR_GCS_BUCKET", "tibbir-data")
GCS_PREFIX = f"gs://{GCS_BUCKET}"

PUBLIC_GCS_BUCKET  = os.environ.get("TIBBIR_PUBLIC_GCS_BUCKET", "tibson-public")
PUBLIC_GCS_PREFIX  = f"gs://{PUBLIC_GCS_BUCKET}"
PUBLIC_BASE_URL    = f"https://storage.googleapis.com/{PUBLIC_GCS_BUCKET}"
MASTER_FILE = f"{GCS_PREFIX}/tibbir_transfers_master.parquet"
METADATA_FILE = f"{GCS_PREFIX}/tibbir_metadata.json"
DAILY_HOLDER_GROWTH_FILE = f"{GCS_PREFIX}/daily_holder_growth.parquet"
DAILY_BUCKET_BREAKDOWN_FILE = f"{GCS_PREFIX}/daily_bucket_breakdown.parquet"
WALLET_SNAPSHOT_FILE = f"{GCS_PREFIX}/tibbir_wallet_snapshot.parquet"
RECENT_TRANSFERS_FILE = f"{GCS_PREFIX}/tibbir_recent_transfers.parquet"
WALLET_ACTIVITY_FILE    = f"{GCS_PREFIX}/tibbir_wallet_activity.parquet"
COIN_AGE_SNAPSHOTS_FILE = f"{GCS_PREFIX}/tibbir_coin_age_snapshots.parquet"
WALLET_EVENTS_FILE      = f"{GCS_PREFIX}/tibbir_wallet_events.parquet"
WALLET_SUMMARY_FILE     = f"{GCS_PREFIX}/tibbir_wallet_summary.parquet"
WALLET_PROFILER_FILE    = f"{GCS_PREFIX}/tibbir_wallet_profiler.parquet"
PRICE_HISTORY_FILE      = f"{GCS_PREFIX}/tibbir_price_history.parquet"
CHAD_COHORTS_FILE       = f"{GCS_PREFIX}/tibbir_chad_cohorts.parquet"
CHAD_WALLETS_FILE       = f"{GCS_PREFIX}/tibbir_chad_wallets.parquet"
SOULBOUND_NFT_HOLDERS_CSV = "data/Tibbir-SoulboundNFT-0xcabce1fa75aca96b40cc98dd3ab38ba332d9e488.csv"
SOULBOUND_HOLDER_SUPPLY_FILE = f"{GCS_PREFIX}/tibbir_soulbound_holder_supply.parquet"
