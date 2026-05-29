import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.update import (
    update_transfers,
    update_daily_holder_growth,
    update_daily_bucket_breakdown,
    build_wallet_snapshot,
    build_wallet_activity,
    update_coin_age_snapshots,
    build_wallet_events,
    build_wallet_summary,
    publish_public_dataset,
    update_price_history,
    build_soulbound_holder_supply,
    build_chad_cohorts,
)

print("=== update_transfers ===")
print(update_transfers())

print("=== update_daily_holder_growth ===")
print(update_daily_holder_growth())

print("=== update_daily_bucket_breakdown ===")
print(update_daily_bucket_breakdown())

print("=== build_wallet_snapshot ===")
print(build_wallet_snapshot())

print("=== build_wallet_activity ===")
print(build_wallet_activity())

print("=== update_coin_age_snapshots ===")
print(update_coin_age_snapshots())

print("=== build_wallet_events ===")
print(build_wallet_events())

print("=== build_wallet_summary ===")
print(build_wallet_summary())

print("=== update_price_history ===")
print(update_price_history())

print("=== build_soulbound_holder_supply ===")
print(build_soulbound_holder_supply())

print("=== build_chad_cohorts ===")
print(build_chad_cohorts())

print("=== publish_public_dataset ===")
print(publish_public_dataset())
