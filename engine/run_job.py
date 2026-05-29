import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.update import (
    update_transfers,
    update_daily_holder_growth,
    update_daily_bucket_breakdown,
    rebuild_daily_holder_growth,
    rebuild_daily_bucket_breakdown,
    build_wallet_snapshot,
    build_wallet_activity,
    rebuild_coin_age_snapshots,
    update_coin_age_snapshots,
    build_wallet_events,
    build_wallet_summary,
    build_wallet_profiler,
    publish_public_dataset,
    rebuild_price_history,
    update_price_history,
    build_soulbound_holder_supply,
    build_chad_cohorts,
)

JOBS = {
    "update_transfers":           lambda: update_transfers(),
    "update_holder_growth":       lambda: update_daily_holder_growth(),
    "update_bucket_breakdown":    lambda: update_daily_bucket_breakdown(),
    "rebuild_holder_growth":      lambda: rebuild_daily_holder_growth(),
    "rebuild_bucket_breakdown":   lambda: rebuild_daily_bucket_breakdown(),
    "build_wallet_snapshot":      lambda: build_wallet_snapshot(),
    "build_wallet_activity":      lambda: build_wallet_activity(),
    "rebuild_coin_age_snapshots": lambda: rebuild_coin_age_snapshots(),
    "update_coin_age_snapshots":  lambda: update_coin_age_snapshots(),
    "build_wallet_events":        lambda: build_wallet_events(),
    "build_wallet_summary":       lambda: build_wallet_summary(),
    "build_wallet_profiler":      lambda: build_wallet_profiler(),
    "publish_public_dataset":     lambda: publish_public_dataset(),
    "rebuild_price_history":      lambda: rebuild_price_history(),
    "update_price_history":       lambda: update_price_history(),
    "build_soulbound_holder_supply": lambda: build_soulbound_holder_supply(),
    "build_chad_cohorts":         lambda: build_chad_cohorts(),
}

parser = argparse.ArgumentParser()
parser.add_argument("--job", required=True, choices=list(JOBS))
args = parser.parse_args()

print(f"=== {args.job} ===")
print(JOBS[args.job]())
