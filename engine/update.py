import requests
import pandas as pd
import json
import os
import time
from datetime import datetime, timedelta, timezone

import sys
from pathlib import Path

import gcsfs

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from analytics.snapshot import (
    build_balance_snapshot,
    build_daily_holder_growth,
    build_daily_bucket_breakdown,
    apply_transfers_to_snapshot,
)
from analytics.coin_age import build_weekly_snapshots, project_snapshots_forward
from analytics.wallet import (
    build_wallet_events as _build_wallet_events,
    build_wallet_summary as _build_wallet_summary,
)
from analytics.wallet_profiler import (
    ProfilerConfig,
    build_wallet_profiler_table as _build_wallet_profiler_table,
    validate_profiler_table,
)
from analytics.soulbound import build_soulbound_holder_supply as _build_soulbound_holder_supply
from analytics.chads import (
    build_chad_cohorts as _build_chad_cohorts,
    build_chad_wallets as _build_chad_wallets,
)


# =====================================================
# GCS / FILE HELPERS
# =====================================================

_fs = None

def _get_fs():
    """Lazy-load GCS filesystem."""
    global _fs
    if _fs is None:
        _fs = gcsfs.GCSFileSystem()
    return _fs


def _is_gcs_path(path):
    """Check if path is a GCS URI."""
    return isinstance(path, str) and path.startswith("gs://")


def _read_json(path):
    """Read JSON from local or GCS path."""
    if _is_gcs_path(path):
        with _get_fs().open(path, 'r') as f:
            return json.load(f)
    else:
        with open(path) as f:
            return json.load(f)


def _write_json(data, path):
    """Write JSON to local or GCS path."""
    if _is_gcs_path(path):
        with _get_fs().open(path, 'w') as f:
            json.dump(data, f, indent=2)
    else:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)


def _file_exists(path):
    """Check if file exists (local or GCS)."""
    if _is_gcs_path(path):
        return _get_fs().exists(path)
    else:
        return Path(path).exists()


def _resolve_repo_path(path):
    return Path(__file__).parent.parent / path


def _load_chad_known_addresses():
    known = _read_json(_resolve_repo_path("data/known_addresses.json"))
    labels_path = _resolve_repo_path("data/wallet_labels.json")
    if _file_exists(labels_path):
        labels = _read_json(labels_path)
        known.update(labels.get("confirmed", {}))
    return known


# =====================================================
# RPC HELPERS
# =====================================================

def _alchemy_rpc_url():
    url = os.environ.get("ALCHEMY_RPC_URL", "").strip()
    if not url:
        raise RuntimeError("ALCHEMY_RPC_URL is required for pipeline jobs that fetch Alchemy data.")
    return url


def _alchemy_prices_url():
    api_key = _alchemy_rpc_url().rstrip("/").split("/")[-1]
    return f"https://api.g.alchemy.com/prices/v1/{api_key}"


def _rpc_call(method, params=None):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or []
    }
    r = requests.post(_alchemy_rpc_url(), json=payload)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise Exception(data["error"])
    return data["result"]


def _get_latest_block():
    return int(_rpc_call("eth_blockNumber"), 16)


def _hex_to_int(x):
    if x is None:
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, str) and x.startswith("0x"):
        return int(x, 16)
    return int(x)


# =====================================================
# PRICE HISTORY
# =====================================================

def _format_alchemy_time(ts):
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _price_history_columns():
    return [
        "date",
        "timestamp",
        "price_usd",
        "symbol",
        "contract_address",
        "source",
        "fetched_at_utc",
    ]


_SYNC_TOPIC = "0x1c411e9a96e071241d3f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"
_TOKEN0_SELECTOR = "0x0dfe1681"
_TOKEN1_SELECTOR = "0xd21220a7"
_DECIMALS_SELECTOR = "0x313ce567"
_GET_RESERVES_SELECTOR = "0x0902f1ac"


def _default_price_start():
    if _file_exists(config.METADATA_FILE):
        metadata = _read_json(config.METADATA_FILE)
        first_transfer = metadata.get("first_transfer_utc")
        if first_transfer:
            return pd.to_datetime(first_transfer, utc=True).normalize()
    return pd.Timestamp("2025-01-01", tz="UTC")


def _default_price_end():
    return pd.Timestamp.now(tz="UTC").normalize()


def _iter_price_ranges(start, end, max_days=365):
    current = pd.to_datetime(start, utc=True).normalize()
    end_ts = pd.to_datetime(end, utc=True).normalize()

    while current <= end_ts:
        chunk_end = min(current + pd.Timedelta(days=max_days - 1), end_ts)
        yield current, chunk_end
        current = chunk_end + pd.Timedelta(days=1)


def _fetch_alchemy_price_history_window(start, end, address=None, symbol=None):
    body = {
        "startTime": _format_alchemy_time(start),
        "endTime": _format_alchemy_time(end),
        "interval": "1d",
    }
    if symbol:
        body["symbol"] = symbol
    else:
        body["network"] = config.ALCHEMY_PRICE_NETWORK
        body["address"] = address or config.CONTRACT_ADDRESS

    r = requests.post(
        f"{_alchemy_prices_url()}/tokens/historical",
        json=body,
        headers={"accept": "application/json", "content-type": "application/json"},
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"Alchemy price request failed: {r.status_code} {r.text}")
    return r.json()


def _fetch_alchemy_price_history(start, end, address=None, symbol=None):
    data = []
    for chunk_start, chunk_end in _iter_price_ranges(start, end):
        print(f"  price chunk: {chunk_start.date()} -> {chunk_end.date()}")
        payload = _fetch_alchemy_price_history_window(chunk_start, chunk_end, address=address, symbol=symbol)
        data.extend(payload.get("data", []))
    return {"data": data}


def _normalize_price_history(payload):
    data = payload.get("data", [])
    if not data:
        return pd.DataFrame(columns=_price_history_columns())

    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["date"] = df["timestamp"].dt.date
    df["price_usd"] = pd.to_numeric(df["value"], errors="coerce")
    df["symbol"] = "TIBBIR"
    df["contract_address"] = config.CONTRACT_ADDRESS
    df["source"] = "alchemy_prices"
    df["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()

    result = (
        df[_price_history_columns()]
        .dropna(subset=["timestamp", "price_usd"])
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return result


def _normalize_quote_price_history(payload):
    data = payload.get("data", [])
    if not data:
        return pd.DataFrame(columns=["date", "quote_price_usd"])

    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["date"] = df["timestamp"].dt.date
    df["quote_price_usd"] = pd.to_numeric(df["value"], errors="coerce")
    return (
        df[["date", "quote_price_usd"]]
        .dropna(subset=["quote_price_usd"])
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def _decode_abi_address(raw):
    return "0x" + str(raw)[-40:].lower()


def _eth_call(to_address, data, block_number=None):
    call = {"to": to_address, "data": data}
    block = hex(block_number) if block_number is not None else "latest"
    return _rpc_call("eth_call", [call, block])


def _read_contract_address(to_address, selector):
    return _decode_abi_address(_eth_call(to_address, selector))


def _read_token_decimals(token_address):
    result = _eth_call(token_address, _DECIMALS_SELECTOR)
    return int(result, 16)


def _get_daily_pair_blocks(start, end):
    pair_address = config.TIBBIR_VIRTUAL_PAIR_ADDRESS.lower()
    transfers = pd.read_parquet(
        config.MASTER_FILE,
        columns=["block_number", "timestamp", "from_address", "to_address"],
    )
    ts = pd.to_datetime(transfers["timestamp"], utc=True)
    start_ts = pd.to_datetime(start, utc=True)
    end_ts = pd.to_datetime(end, utc=True) + pd.Timedelta(days=1)

    pair_transfers = transfers[
        (ts >= start_ts)
        & (ts < end_ts)
        & (
            (transfers["from_address"].str.lower() == pair_address)
            | (transfers["to_address"].str.lower() == pair_address)
        )
    ].copy()
    if pair_transfers.empty:
        return pd.DataFrame(columns=["date", "block_number"])

    pair_transfers["date"] = pd.to_datetime(pair_transfers["timestamp"], utc=True).dt.date
    daily_blocks = pair_transfers.groupby("date")["block_number"].max()
    all_dates = pd.date_range(start_ts.normalize(), (end_ts - pd.Timedelta(days=1)).normalize(), freq="D", tz="UTC").date
    return (
        daily_blocks
        .reindex(all_dates)
        .ffill()
        .dropna()
        .astype(int)
        .rename_axis("date")
        .reset_index()
    )


def _decode_pair_reserves(raw):
    data = raw[2:]
    reserve0 = int(data[0:64], 16)
    reserve1 = int(data[64:128], 16)
    return reserve0, reserve1


def _read_pair_reserves(pair_address, block_number):
    return _decode_pair_reserves(_eth_call(pair_address, _GET_RESERVES_SELECTOR, block_number=block_number))


def _compute_native_pair_price(reserve0, reserve1, token0, token1, token0_decimals, token1_decimals):
    if token0 == config.CONTRACT_ADDRESS:
        tibbir_reserve = reserve0 / (10 ** token0_decimals)
        quote_reserve = reserve1 / (10 ** token1_decimals)
    elif token1 == config.CONTRACT_ADDRESS:
        tibbir_reserve = reserve1 / (10 ** token1_decimals)
        quote_reserve = reserve0 / (10 ** token0_decimals)
    else:
        raise RuntimeError("Configured TIBBIR/VIRTUAL pair does not contain TIBBIR.")

    return quote_reserve / tibbir_reserve if tibbir_reserve else None


def _fetch_dex_price_history(start, end):
    start_ts = pd.to_datetime(start, utc=True).normalize()
    end_ts = pd.to_datetime(end, utc=True).normalize()
    if start_ts > end_ts:
        return pd.DataFrame(columns=_price_history_columns())

    print(f"Fetching DEX-derived TIBBIR price history: {start_ts.date()} -> {end_ts.date()}")
    token0 = _read_contract_address(config.TIBBIR_VIRTUAL_PAIR_ADDRESS, _TOKEN0_SELECTOR)
    token1 = _read_contract_address(config.TIBBIR_VIRTUAL_PAIR_ADDRESS, _TOKEN1_SELECTOR)
    token0_decimals = _read_token_decimals(token0)
    token1_decimals = _read_token_decimals(token1)

    daily_blocks = _get_daily_pair_blocks(start_ts, end_ts)
    if daily_blocks.empty:
        return pd.DataFrame(columns=_price_history_columns())

    price_by_block = {}
    for block_number in sorted(daily_blocks["block_number"].unique()):
        reserve0, reserve1 = _read_pair_reserves(config.TIBBIR_VIRTUAL_PAIR_ADDRESS, int(block_number))
        price_by_block[int(block_number)] = _compute_native_pair_price(
            reserve0,
            reserve1,
            token0,
            token1,
            token0_decimals,
            token1_decimals,
        )
        time.sleep(0.05)

    prices_native = daily_blocks.copy()
    prices_native["price_native"] = prices_native["block_number"].map(price_by_block)

    quote_payload = _fetch_alchemy_price_history(start_ts, end_ts, address=config.VIRTUAL_ADDRESS)
    quote_prices = _normalize_quote_price_history(quote_payload)
    if quote_prices.empty:
        raise RuntimeError("Could not fetch VIRTUAL quote prices for DEX price backfill.")

    result = prices_native.merge(quote_prices, on="date", how="left")
    result["quote_price_usd"] = result["quote_price_usd"].ffill().bfill()
    result["price_usd"] = result["price_native"] * result["quote_price_usd"]
    result["timestamp"] = pd.to_datetime(result["date"], utc=True)
    result["symbol"] = "TIBBIR"
    result["contract_address"] = config.CONTRACT_ADDRESS
    result["source"] = "dex_reserves_tibbir_virtual"
    result["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()

    return (
        result[_price_history_columns()]
        .dropna(subset=["price_usd"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def _fill_price_history_gap(start_ts, alchemy_prices):
    if alchemy_prices.empty:
        return alchemy_prices

    first_alchemy_date = pd.Timestamp(alchemy_prices["date"].min(), tz="UTC")
    gap_end = first_alchemy_date - pd.Timedelta(days=1)
    if start_ts >= first_alchemy_date:
        return alchemy_prices

    dex_prices = _fetch_dex_price_history(start_ts, gap_end)
    if dex_prices.empty:
        return alchemy_prices

    return (
        pd.concat([dex_prices, alchemy_prices], ignore_index=True)
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def _write_price_history_metadata(df):
    metadata = _read_json(config.METADATA_FILE)
    metadata["price_history_row_count"] = int(len(df))
    metadata["price_history_first_date"] = str(df["date"].min()) if not df.empty else None
    metadata["price_history_last_date"] = str(df["date"].max()) if not df.empty else None
    metadata["price_history_built_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(metadata, config.METADATA_FILE)


def rebuild_price_history(start=None, end=None):
    """
    Rebuild daily TIBBIR USD price history from Alchemy Prices API.

    Returns:
        str: Status message
    """
    start_ts = pd.to_datetime(start, utc=True).normalize() if start else _default_price_start()
    end_ts = pd.to_datetime(end, utc=True).normalize() if end else _default_price_end()

    if start_ts > end_ts:
        return f"No price history to fetch. Start {start_ts.date()} is after end {end_ts.date()}."

    print(f"Fetching TIBBIR price history: {start_ts.date()} -> {end_ts.date()}")
    payload = _fetch_alchemy_price_history(start_ts, end_ts)
    prices = _fill_price_history_gap(start_ts, _normalize_price_history(payload))

    if prices.empty:
        return "No price history returned by Alchemy."

    prices.to_parquet(config.PRICE_HISTORY_FILE, index=False)
    _write_price_history_metadata(prices)
    return (
        f"Rebuilt price history. {len(prices)} daily rows "
        f"from {prices['date'].min()} to {prices['date'].max()}."
    )


def update_price_history():
    """
    Incrementally update daily TIBBIR USD price history.

    The latest stored day is dropped and refetched because the newest daily
    point can move as external pricing sources settle.

    Returns:
        str: Status message
    """
    if not _file_exists(config.PRICE_HISTORY_FILE):
        return rebuild_price_history()

    existing = pd.read_parquet(config.PRICE_HISTORY_FILE)
    if existing.empty:
        return rebuild_price_history()

    existing["date"] = pd.to_datetime(existing["date"]).dt.date
    last_date = existing["date"].max()
    trimmed = existing[existing["date"] < last_date].copy()

    start_ts = pd.Timestamp(last_date, tz="UTC")
    end_ts = _default_price_end()
    if start_ts > end_ts:
        return f"Price history is already current through {last_date}."

    print(f"Fetching TIBBIR price history: {start_ts.date()} -> {end_ts.date()}")
    payload = _fetch_alchemy_price_history(start_ts, end_ts)
    fetched = _normalize_price_history(payload)

    if fetched.empty:
        return "No new price history returned by Alchemy."

    result = (
        pd.concat([trimmed, fetched], ignore_index=True)
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    result.to_parquet(config.PRICE_HISTORY_FILE, index=False)
    _write_price_history_metadata(result)

    return (
        f"Updated price history. Added/refreshed {len(fetched)} days. "
        f"Total: {len(result)} days."
    )


# =====================================================
# SOULBOUND NFT HOLDER SUPPLY
# =====================================================

def build_soulbound_holder_supply():
    """
    Build daily TIBBIR holdings for addresses currently holding the
    commemorative soulbound NFT.

    Returns:
        str: Status message
    """
    holders_path = _resolve_repo_path(config.SOULBOUND_NFT_HOLDERS_CSV)
    holders_df = pd.read_csv(holders_path)
    holder_addresses = (
        holders_df["HolderAddress"]
        .dropna()
        .astype(str)
        .str.lower()
        .unique()
        .tolist()
    )

    print(f"Loading transfers for {len(holder_addresses):,} soulbound NFT holders...")
    transfers = pd.read_parquet(config.MASTER_FILE)

    metadata = _read_json(config.METADATA_FILE)
    total_supply = metadata.get("total_minted_supply")
    if total_supply is None:
        raw_amounts = transfers["raw_amount"].apply(int)
        total_supply_raw = int(raw_amounts[transfers["from_address"] == _ZERO_ADDRESS].sum())
    else:
        total_supply_raw = int(float(total_supply) * 1e18)

    result = _build_soulbound_holder_supply(
        transfers,
        holder_addresses=holder_addresses,
        total_supply_raw=total_supply_raw,
    )

    if result.empty:
        return "No soulbound holder TIBBIR balances found."

    result.to_parquet(config.SOULBOUND_HOLDER_SUPPLY_FILE, index=False)

    latest = result.sort_values("date").iloc[-1]
    metadata["soulbound_nft_holder_count"] = int(len(holder_addresses))
    metadata["soulbound_tibbir_holder_count"] = int(latest["holder_count"])
    metadata["soulbound_tibbir_balance"] = float(latest["total_balance"])
    metadata["soulbound_tibbir_pct_total_supply"] = float(latest["pct_total_supply"])
    metadata["soulbound_holder_supply_built_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(metadata, config.METADATA_FILE)

    return (
        f"Soulbound holder supply built. {len(result)} days, "
        f"{latest['total_balance']:,.0f} TIBBIR held by "
        f"{int(latest['holder_count']):,}/{len(holder_addresses):,} NFT holders."
    )


# =====================================================
# CHAD COHORTS
# =====================================================

def build_chad_cohorts():
    """
    Build current chad cohort aggregates for the dashboard.

    Cohorts are current holders in 10k-100k, 100k-1M, and 1M+ buckets,
    excluding known exchanges/burns, with current/peak >= 90% and
    total_sent/total_received < 20%.

    Returns:
        str: Status message
    """
    print("Loading wallet events, wallet summary, coin age snapshots, and known labels...")
    wallet_events = pd.read_parquet(config.WALLET_EVENTS_FILE)
    wallet_summary = pd.read_parquet(config.WALLET_SUMMARY_FILE)
    coin_age_snapshots = pd.read_parquet(config.COIN_AGE_SNAPSHOTS_FILE)
    known_addresses = _load_chad_known_addresses()

    result = _build_chad_cohorts(
        wallet_events=wallet_events,
        wallet_summary=wallet_summary,
        coin_age_snapshots=coin_age_snapshots,
        known_addresses=known_addresses,
    )
    wallets = _build_chad_wallets(
        wallet_events=wallet_events,
        wallet_summary=wallet_summary,
        coin_age_snapshots=coin_age_snapshots,
        known_addresses=known_addresses,
    )
    result.to_parquet(config.CHAD_COHORTS_FILE, index=False)
    wallets.to_parquet(config.CHAD_WALLETS_FILE, index=False)

    metadata = _read_json(config.METADATA_FILE)
    latest = result.sort_values("date").groupby("cohort", observed=False).tail(1) if not result.empty else result
    metadata["chad_cohort_wallet_count"] = int(latest["wallet_count"].sum()) if not latest.empty else 0
    metadata["chad_cohort_total_balance"] = float(latest["total_balance"].sum()) if not latest.empty else 0.0
    metadata["chad_cohort_history_days"] = int(result["date"].nunique()) if not result.empty else 0
    metadata["chad_wallet_rows"] = int(len(wallets))
    metadata["chad_cohorts_built_utc"] = datetime.now(timezone.utc).isoformat()
    metadata["chad_cohort_config"] = {
        "retention_threshold": 0.90,
        "turnover_threshold": 0.20,
        "turnover_definition": "total_sent / total_received",
        "excluded_known_address_types": ["exchange", "burn", "router", "lp"],
    }
    _write_json(metadata, config.METADATA_FILE)

    return (
        f"Chad cohorts built. {metadata['chad_cohort_wallet_count']:,} wallets, "
        f"{metadata['chad_cohort_total_balance']:,.0f} TIBBIR, "
        f"{metadata['chad_cohort_history_days']:,} history days."
    )


# =====================================================
# UPDATE TRANSFERS
# =====================================================

def update_transfers():
    """
    Fetch new transfers from the blockchain and update the master Parquet file.

    Returns:
        str: Status message
    """
    # Load metadata
    metadata = _read_json(config.METADATA_FILE)

    last_end_block = metadata["end_block"]

    latest_block = _get_latest_block()
    safe_head = latest_block - config.REORG_BUFFER

    print("Latest block:", latest_block)
    print("Safe head:", safe_head)
    print("Previous end_block:", last_end_block)

    if safe_head <= last_end_block:
        return "No update needed."

    start_block = last_end_block - config.REORG_BUFFER
    print("Updating range:", start_block, "->", safe_head)

    # Fetch transfers
    page_key = None
    new_rows = []
    total_fetched = 0

    while True:
        params = {
            "fromBlock": hex(start_block),
            "toBlock": hex(safe_head),
            "contractAddresses": [config.CONTRACT_ADDRESS],
            "category": ["erc20"],
            "maxCount": config.MAX_COUNT_HEX,
            "withMetadata": True
        }

        if page_key:
            params["pageKey"] = page_key

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "alchemy_getAssetTransfers",
            "params": [params]
        }

        r = requests.post(_alchemy_rpc_url(), json=payload)
        r.raise_for_status()
        data = r.json()

        if "error" in data:
            raise Exception(data["error"])

        result = data["result"]
        transfers = result.get("transfers", [])
        page_key = result.get("pageKey")

        for t in transfers:
            raw = t.get("rawContract") or {}
            raw_value = _hex_to_int(raw.get("value"))
            decimals = _hex_to_int(raw.get("decimal"))

            new_rows.append({
                "event_id": t.get("uniqueId"),
                "block_number": _hex_to_int(t.get("blockNum")),
                "timestamp": (t.get("metadata") or {}).get("blockTimestamp"),
                "tx_hash": t.get("hash"),
                "from_address": (t.get("from") or "").lower(),
                "to_address": (t.get("to") or "").lower(),
                "raw_amount": str(raw_value) if raw_value is not None else "",
                "decimals": decimals,
                "amount": None,  # Will be NaN in pandas (float64 compatible)
                "contract_address": (raw.get("address") or config.CONTRACT_ADDRESS).lower(),
                "category": t.get("category"),
                "asset": t.get("asset")
            })

        total_fetched += len(transfers)
        print("Fetched:", total_fetched)

        if not page_key:
            break

        time.sleep(0.05)

    print("Total new transfers fetched:", total_fetched)

    if total_fetched == 0:
        return "No new transfers found."

    new_df = pd.DataFrame(new_rows)

    # Load master
    master = pd.read_parquet(config.MASTER_FILE)

    min_block_existing = master["block_number"].min()
    max_block_existing = master["block_number"].max()

    # Safety checks
    if start_block < min_block_existing:
        raise Exception(
            f"Start block {start_block} is earlier than master min block {min_block_existing}. Aborting."
        )

    if start_block > max_block_existing:
        raise Exception(
            f"Start block {start_block} is beyond master max block {max_block_existing}. Aborting."
        )

    # Remove overlap region safely
    master = master[master["block_number"] < start_block]

    # Append new data
    master = pd.concat([master, new_df], ignore_index=True)

    # Deduplicate
    master = master.drop_duplicates(subset=["event_id"])

    # Sort deterministically
    master = master.sort_values(["block_number", "tx_hash"])

    # Invariant checks
    print("Running invariant checks...")

    # No duplicate event_id
    dup_count = master["event_id"].duplicated().sum()
    if dup_count != 0:
        raise Exception(f"Invariant failed: {dup_count} duplicate event_id found.")

    # Ledger must net to zero (use temporary int series, keep raw_amount as string)
    raw_amount_int = master["raw_amount"].apply(int)

    incoming = raw_amount_int.groupby(master["to_address"]).sum()
    outgoing = raw_amount_int.groupby(master["from_address"]).sum()
    balances = incoming.sub(outgoing, fill_value=0)

    net_balance = balances.sum()
    if net_balance != 0:
        raise Exception(f"Invariant failed: ledger net balance = {net_balance}")

    # Ensure we did not index beyond safe_head
    max_block_after = int(master["block_number"].max())
    if max_block_after > safe_head:
        raise Exception(
            f"Invariant failed: master max block {max_block_after} exceeds safe head {safe_head}"
        )

    print("All invariants passed.")

    # Save master
    master.to_parquet(config.MASTER_FILE, index=False)
    print("Master updated. Total rows:", len(master))

    # Update metadata
    metadata["end_block"] = max_block_after
    metadata["transfer_count"] = int(len(master))
    metadata["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
    ts = pd.to_datetime(master["timestamp"]).sort_values()
    metadata["first_transfer_utc"] = ts.iloc[0].isoformat() if len(ts) > 0 else None
    metadata["last_transfer_utc"] = ts.iloc[-1].isoformat() if len(ts) > 0 else None

    _write_json(metadata, config.METADATA_FILE)

    master.tail(100).to_parquet(config.RECENT_TRANSFERS_FILE, index=False)
    print("Metadata updated.")
    return f"Update complete. {total_fetched} transfers added. Total rows: {len(master)}"


# =====================================================
# UPDATE DAILY HOLDER GROWTH (INCREMENTAL)
# =====================================================

def update_daily_holder_growth(decimals=18):
    """
    Incrementally update daily holder growth parquet with per-bucket wallet counts.
    """
    if not _file_exists(config.DAILY_HOLDER_GROWTH_FILE):
        return rebuild_daily_holder_growth(decimals)

    existing = pd.read_parquet(config.DAILY_HOLDER_GROWTH_FILE)

    if existing.empty:
        return rebuild_daily_holder_growth(decimals)

    existing["date"] = pd.to_datetime(existing["date"]).dt.date
    last_date = existing["date"].max()
    print(f"Existing data up to: {last_date}")

    existing = existing[existing["date"] < last_date]

    transfers = pd.read_parquet(config.MASTER_FILE)
    transfers["date"] = pd.to_datetime(transfers["timestamp"]).dt.date

    new_dates = sorted(transfers[transfers["date"] >= last_date]["date"].unique())

    if not new_dates:
        return "No new dates to process."

    print(f"Processing {len(new_dates)} dates: {new_dates[0]} to {new_dates[-1]}")

    before_last = transfers[transfers["date"] < last_date]
    snapshot = build_balance_snapshot(before_last)

    B1k   = int(1_000     * (10 ** decimals))
    B10k  = int(10_000    * (10 ** decimals))
    B100k = int(100_000   * (10 ** decimals))
    B1m   = int(1_000_000 * (10 ** decimals))

    new_rows = []

    for date in new_dates:
        day_transfers = transfers[transfers["date"] == date]
        snapshot = apply_transfers_to_snapshot(snapshot, day_transfers)

        if snapshot.empty:
            continue

        c0_1k     = int((snapshot["raw_balance"] < B1k).sum())
        c1k_10k   = int(((snapshot["raw_balance"] >= B1k)   & (snapshot["raw_balance"] < B10k)).sum())
        c10k_100k = int(((snapshot["raw_balance"] >= B10k)  & (snapshot["raw_balance"] < B100k)).sum())
        c100k_1m  = int(((snapshot["raw_balance"] >= B100k) & (snapshot["raw_balance"] < B1m)).sum())
        c1m_plus  = int((snapshot["raw_balance"] >= B1m).sum())

        new_rows.append({
            "date":           date,
            "count_0_1k":     c0_1k,
            "count_1k_10k":   c1k_10k,
            "count_10k_100k": c10k_100k,
            "count_100k_1m":  c100k_1m,
            "count_1m_plus":  c1m_plus,
            "total_holders":  c0_1k + c1k_10k + c10k_100k + c100k_1m + c1m_plus,
        })

    if not new_rows:
        return "No new data to add."

    result = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
    result.to_parquet(config.DAILY_HOLDER_GROWTH_FILE, index=False)

    return f"Updated daily holder growth. Added {len(new_rows)} days. Total: {len(result)} days."


# =====================================================
# REBUILD DAILY HOLDER GROWTH (FULL)
# =====================================================

def build_wallet_snapshot():
    """
    Build a balance snapshot from the master transfer ledger and store it to
    GCS (or local). Also writes summary stats into the existing metadata JSON.

    Returns:
        str: Status message
    """
    transfers = pd.read_parquet(config.MASTER_FILE)
    snapshot = build_balance_snapshot(transfers)
    snapshot["balance"] = snapshot["raw_balance"] / 1e18

    # Compute stats before converting raw_balance to string
    zero_addr = "0x0000000000000000000000000000000000000000"
    dead_addr = "0x000000000000000000000000000000000000dead"

    holder_count = int((snapshot["raw_balance"] > 0).sum())
    raw_amounts = transfers["raw_amount"].apply(int)

    # Total minted = all tokens ever sent FROM zero address (mint events)
    minted_raw = int(raw_amounts[transfers["from_address"] == zero_addr].sum())
    total_minted_supply = float(minted_raw / 1e18)

    # Tokens burned to zero address
    burned_raw = int(raw_amounts[transfers["to_address"] == zero_addr].sum())
    burned_supply = float(burned_raw / 1e18)

    # Tokens held by dead address (from snapshot, before raw_balance → str conversion)
    dead_rows = snapshot[snapshot["address"] == dead_addr]
    dead_address_supply = float(dead_rows["raw_balance"].sum() / 1e18) if len(dead_rows) else 0.0

    # Holders with balance >= 10k tokens (excluding dead address)
    threshold_10k = int(10_000 * 1e18)
    holders_10k_plus = int(
        ((snapshot["raw_balance"] >= threshold_10k) & (snapshot["address"] != dead_addr)).sum()
    )

    # raw_balance values exceed int64 range; store as string (same convention as raw_amount)
    snapshot["balance"] = snapshot["raw_balance"] / 1e18
    snapshot["raw_balance"] = snapshot["raw_balance"].astype(str)
    snapshot.to_parquet(config.WALLET_SNAPSHOT_FILE, index=False)

    metadata = _read_json(config.METADATA_FILE)
    metadata["wallet_snapshot_holder_count"] = holder_count
    metadata["holders_10k_plus"] = holders_10k_plus
    metadata["total_minted_supply"] = total_minted_supply
    metadata["burned_supply"] = burned_supply
    metadata["dead_address_supply"] = dead_address_supply
    metadata["wallet_snapshot_built_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(metadata, config.METADATA_FILE)

    return f"Snapshot built. {len(snapshot):,} holders."


def rebuild_daily_holder_growth(decimals=18):
    """
    Full rebuild of daily holder growth parquet with per-bucket wallet counts.
    """
    print("Rebuilding daily holder growth from scratch...")
    transfers = pd.read_parquet(config.MASTER_FILE)
    result = build_daily_holder_growth(transfers, decimals=decimals)
    result.to_parquet(config.DAILY_HOLDER_GROWTH_FILE, index=False)
    return f"Rebuilt daily holder growth. Total: {len(result)} days."


# =====================================================
# UPDATE DAILY BUCKET BREAKDOWN (INCREMENTAL)
# =====================================================

def update_daily_bucket_breakdown(decimals=18):
    """
    Incrementally update daily bucket breakdown Parquet.

    Drops the last day (may be incomplete) then processes new days
    using the same incremental snapshot approach as update_daily_holder_growth.

    Returns:
        str: Status message
    """
    if not _file_exists(config.DAILY_BUCKET_BREAKDOWN_FILE):
        return rebuild_daily_bucket_breakdown(decimals)

    existing = pd.read_parquet(config.DAILY_BUCKET_BREAKDOWN_FILE)

    if existing.empty:
        return rebuild_daily_bucket_breakdown(decimals)

    existing["date"] = pd.to_datetime(existing["date"]).dt.date
    last_date = existing["date"].max()
    print(f"Existing bucket data up to: {last_date}")

    existing = existing[existing["date"] < last_date]

    transfers = pd.read_parquet(config.MASTER_FILE)
    transfers["date"] = pd.to_datetime(transfers["timestamp"]).dt.date

    new_dates = sorted(transfers[transfers["date"] >= last_date]["date"].unique())

    if not new_dates:
        return "No new dates to process."

    print(f"Processing {len(new_dates)} dates: {new_dates[0]} to {new_dates[-1]}")

    before_last = transfers[transfers["date"] < last_date]
    snapshot = build_balance_snapshot(before_last)

    B1k   = int(1_000     * (10 ** decimals))
    B10k  = int(10_000    * (10 ** decimals))
    B100k = int(100_000   * (10 ** decimals))
    B1m   = int(1_000_000 * (10 ** decimals))

    new_rows = []

    for date in new_dates:
        day_transfers = transfers[transfers["date"] == date]
        snapshot = apply_transfers_to_snapshot(snapshot, day_transfers)

        if snapshot.empty:
            continue

        total_supply_raw = snapshot["raw_balance"].sum()

        b0_1k     = snapshot[snapshot["raw_balance"] < B1k]
        b1k_10k   = snapshot[(snapshot["raw_balance"] >= B1k)   & (snapshot["raw_balance"] < B10k)]
        b10k_100k = snapshot[(snapshot["raw_balance"] >= B10k)  & (snapshot["raw_balance"] < B100k)]
        b100k_1m  = snapshot[(snapshot["raw_balance"] >= B100k) & (snapshot["raw_balance"] < B1m)]
        b1m_plus  = snapshot[snapshot["raw_balance"] >= B1m]

        def _pct(bucket):
            if total_supply_raw == 0:
                return 0.0
            return round(bucket["raw_balance"].sum() / total_supply_raw * 100, 2)

        new_rows.append({
            "date":           date,
            "pct_0_1k":       _pct(b0_1k),
            "pct_1k_10k":     _pct(b1k_10k),
            "pct_10k_100k":   _pct(b10k_100k),
            "pct_100k_1m":    _pct(b100k_1m),
            "pct_1m_plus":    _pct(b1m_plus),
            "count_0_1k":     len(b0_1k),
            "count_1k_10k":   len(b1k_10k),
            "count_10k_100k": len(b10k_100k),
            "count_100k_1m":  len(b100k_1m),
            "count_1m_plus":  len(b1m_plus),
        })

    if not new_rows:
        return "No new data to add."

    result = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
    result.to_parquet(config.DAILY_BUCKET_BREAKDOWN_FILE, index=False)

    return f"Updated daily bucket breakdown. Added {len(new_rows)} days. Total: {len(result)} days."


# =====================================================
# REBUILD DAILY BUCKET BREAKDOWN (FULL)
# =====================================================

def rebuild_daily_bucket_breakdown(decimals=18):
    """
    Full rebuild of daily bucket breakdown Parquet from scratch.

    Returns:
        str: Status message
    """
    print("Rebuilding daily bucket breakdown from scratch...")
    transfers = pd.read_parquet(config.MASTER_FILE)
    result = build_daily_bucket_breakdown(transfers, decimals=decimals)
    result.to_parquet(config.DAILY_BUCKET_BREAKDOWN_FILE, index=False)
    return f"Rebuilt daily bucket breakdown. Total: {len(result)} days."


# =====================================================
# WALLET ACTIVITY
# =====================================================

_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_BURN_ADDRESS = "0x000000000000000000000000000000000000dead"
_EXCHANGE_TX_THRESHOLD = 1000  # wallets with tx_in AND tx_out above this are excluded from coin age


def build_wallet_activity():
    """
    Compute per-address balance and transaction counts from the master ledger
    and save to GCS. Excludes only the zero address (minting source); the burn
    address (0x000...dead) is included so its balance is visible.

    Returns:
        str: Status message
    """
    transfers = pd.read_parquet(config.MASTER_FILE)

    transfers["_raw"] = transfers["raw_amount"].apply(int)
    tx_in  = transfers.groupby("to_address").size().rename("tx_in")
    tx_out = transfers.groupby("from_address").size().rename("tx_out")

    all_addresses = pd.Index(
        pd.concat([transfers["to_address"], transfers["from_address"]]).unique()
    ).difference([_ZERO_ADDRESS])

    incoming = transfers.groupby("to_address")["_raw"].sum()
    outgoing = transfers.groupby("from_address")["_raw"].sum()
    raw_balance = (
        incoming.reindex(all_addresses, fill_value=0)
        .sub(outgoing.reindex(all_addresses, fill_value=0))
    )

    wa = pd.DataFrame({
        "address": all_addresses,
        "balance": raw_balance.values / 1e18,
        "tx_in":   tx_in.reindex(all_addresses, fill_value=0).values,
        "tx_out":  tx_out.reindex(all_addresses, fill_value=0).values,
    }).sort_values("tx_in", ascending=False).reset_index(drop=True)

    wa.to_parquet(config.WALLET_ACTIVITY_FILE, index=False)
    return f"Wallet activity built. {len(wa):,} addresses."


# =====================================================
# COIN AGE SNAPSHOTS
# =====================================================

def rebuild_coin_age_snapshots():
    """
    Full rebuild of per-wallet weekly coin age snapshots from the master ledger.

    Excludes high-activity wallets (likely exchanges / LPs) where both
    tx_in and tx_out exceed the exchange threshold.

    Runtime: ~12 minutes for ~100k wallets.

    Returns:
        str: Status message
    """
    print("Loading transfers and wallet activity...")
    transfers = pd.read_parquet(config.MASTER_FILE)
    wa        = pd.read_parquet(config.WALLET_ACTIVITY_FILE)

    excluded = (
        ((wa["tx_in"] > _EXCHANGE_TX_THRESHOLD) & (wa["tx_out"] > _EXCHANGE_TX_THRESHOLD)) |
        (wa["address"] == _BURN_ADDRESS)
    )
    wallets  = wa[~excluded]["address"].tolist()
    print(f"Wallets to process: {len(wallets):,}  (excluded {excluded.sum():,} exchanges/LPs)")

    # Pre-index transfers by address for O(1) lookup
    addr_col = pd.concat([
        transfers["to_address"].rename("address"),
        transfers["from_address"].rename("address"),
    ]).reset_index().rename(columns={"index": "row_idx"})
    addr_to_idx = addr_col.groupby("address")["row_idx"].apply(list)

    results = []
    skipped = 0
    t0 = time.time()

    for i, addr in enumerate(wallets):
        if addr not in addr_to_idx:
            skipped += 1
            continue
        snap = build_weekly_snapshots(addr, transfers.loc[addr_to_idx[addr]])
        if not snap.empty:
            results.append(snap)

        if (i + 1) % 1000 == 0:
            elapsed   = time.time() - t0
            rate      = (i + 1) / elapsed
            remaining = (len(wallets) - i - 1) / rate / 60
            print(f"  {i+1:,}/{len(wallets):,}  |  {elapsed/60:.1f} min elapsed  |  ~{remaining:.0f} min remaining")

    all_snapshots = pd.concat(results, ignore_index=True)
    all_snapshots.to_parquet(config.COIN_AGE_SNAPSHOTS_FILE, index=False)

    elapsed = time.time() - t0
    return (
        f"Rebuilt coin age snapshots in {elapsed/60:.1f} min. "
        f"{len(all_snapshots):,} rows across {all_snapshots['address'].nunique():,} wallets. "
        f"Skipped {skipped:,}."
    )


def update_coin_age_snapshots():
    """
    Incrementally update coin age snapshots.

    - Wallets with new transfers since the last computed week are fully rebuilt.
    - New wallets not yet in the snapshots are built from scratch.
    - Inactive wallets are projected forward by advancing their coin age in time
      (no transfer scan needed).

    Falls back to rebuild_coin_age_snapshots() if the file does not exist.

    Returns:
        str: Status message
    """
    if not _file_exists(config.COIN_AGE_SNAPSHOTS_FILE):
        print("No existing snapshots — running full rebuild.")
        return rebuild_coin_age_snapshots()

    existing  = pd.read_parquet(config.COIN_AGE_SNAPSHOTS_FILE)
    existing["week_start"] = pd.to_datetime(existing["week_start"]).dt.date

    last_week = existing["week_start"].max()
    print(f"Existing snapshots up to: {last_week}")

    # Re-do the last complete week to handle any transfers that arrived late
    trimmed = existing[existing["week_start"] < last_week].copy()

    # Determine the latest week boundary to project/build up to
    now = datetime.now(tz=timezone.utc)
    from analytics.coin_age import _floor_to_monday
    current_boundary = (_floor_to_monday(now) - timedelta(weeks=1)).date()

    if current_boundary <= last_week:
        return "No new weeks to add — snapshots are current."

    print(f"Adding weeks from {last_week} to {current_boundary}")

    transfers = pd.read_parquet(config.MASTER_FILE)
    wa        = pd.read_parquet(config.WALLET_ACTIVITY_FILE)
    excluded  = (wa["tx_in"] > _EXCHANGE_TX_THRESHOLD) & (wa["tx_out"] > _EXCHANGE_TX_THRESHOLD)
    included  = set(wa[~excluded]["address"].tolist())

    # Wallets active since the re-do boundary
    redo_from    = last_week - timedelta(weeks=1)
    transfers["_ts"] = pd.to_datetime(transfers["timestamp"], utc=True)
    recent_addrs = set(
        pd.concat([
            transfers.loc[transfers["_ts"].dt.date >= redo_from, "to_address"],
            transfers.loc[transfers["_ts"].dt.date >= redo_from, "from_address"],
        ]).unique()
    ) & included

    existing_addrs = set(existing["address"].unique())
    new_addrs      = included - existing_addrs
    active_addrs   = (recent_addrs | new_addrs)
    inactive_addrs = existing_addrs & included - active_addrs

    print(f"Active/new wallets to rebuild: {len(active_addrs):,}")
    print(f"Inactive wallets to project:   {len(inactive_addrs):,}")

    # Rebuild active + new wallets
    addr_col    = pd.concat([
        transfers["to_address"].rename("address"),
        transfers["from_address"].rename("address"),
    ]).reset_index().rename(columns={"index": "row_idx"})
    addr_to_idx = addr_col.groupby("address")["row_idx"].apply(list)

    rebuilt = []
    t0 = time.time()
    for i, addr in enumerate(active_addrs):
        if addr not in addr_to_idx:
            continue
        snap = build_weekly_snapshots(addr, transfers.loc[addr_to_idx[addr]])
        if not snap.empty:
            rebuilt.append(snap)
        if (i + 1) % 500 == 0:
            print(f"  rebuilt {i+1:,}/{len(active_addrs):,}")

    # Project inactive wallets forward
    last_inactive = (
        existing[existing["address"].isin(inactive_addrs)]
        .sort_values("week_start")
        .groupby("address")
        .last()
        .reset_index()
    )
    projected = project_snapshots_forward(last_inactive, current_boundary)

    parts = [trimmed] + rebuilt + ([projected] if not projected.empty else [])
    result = pd.concat(parts, ignore_index=True)
    result.to_parquet(config.COIN_AGE_SNAPSHOTS_FILE, index=False)

    elapsed = time.time() - t0
    return (
        f"Updated coin age snapshots in {elapsed:.1f}s. "
        f"Rebuilt {len(active_addrs):,} wallets, projected {len(inactive_addrs):,}. "
        f"Total rows: {len(result):,}."
    )


# =====================================================
# WALLET EVENTS + WALLET SUMMARY
# =====================================================

def build_wallet_events():
    """
    Build the wallet-centric event log from the master transfer ledger.

    Each transfer produces two rows (one for sender, one for receiver),
    excluding the zero address as a wallet. Sorted by (address, block_number)
    for efficient per-wallet slicing.

    Writes wallet_events_row_count, wallet_events_address_count,
    wallet_events_built_utc, and transfers_master_row_count to metadata.

    Returns:
        str: Status message
    """
    print("Loading master transfers...")
    transfers = pd.read_parquet(config.MASTER_FILE)

    print("Building wallet events...")
    events = _build_wallet_events(transfers)
    events.to_parquet(config.WALLET_EVENTS_FILE, index=False)

    metadata = _read_json(config.METADATA_FILE)
    metadata["wallet_events_row_count"]     = len(events)
    metadata["wallet_events_address_count"] = int(events["address"].nunique())
    metadata["wallet_events_built_utc"]     = datetime.now(timezone.utc).isoformat()
    metadata["transfers_master_row_count"]  = len(transfers)
    _write_json(metadata, config.METADATA_FILE)

    return (
        f"Wallet events built. {len(events):,} rows across "
        f"{metadata['wallet_events_address_count']:,} addresses."
    )


def build_wallet_summary():
    """
    Build an enriched per-wallet summary from the master transfer ledger.

    Contains raw stats only (balance, tx counts, first/last seen, totals).
    No classifications.

    Returns:
        str: Status message
    """
    print("Loading master transfers...")
    transfers = pd.read_parquet(config.MASTER_FILE)

    print("Building wallet summary...")
    summary = _build_wallet_summary(transfers)
    summary.to_parquet(config.WALLET_SUMMARY_FILE, index=False)

    return f"Wallet summary built. {len(summary):,} addresses."


def build_wallet_profiler(
    combined_activity_threshold_in:  int   = 1_000,
    combined_activity_threshold_out: int   = 1_000,
    single_side_activity_threshold:  int   = 10_000,
    peak_balance_threshold:          float = 1_000_000.0,
):
    """
    Build the candidate wallet profiler table.

    Filters out exchange/system wallets, replays balance history to compute
    peak_balance, then keeps only wallets that ever held >= peak_balance_threshold
    tokens. Saves to GCS and writes summary stats to metadata.

    All thresholds are configurable via arguments (defaults match the spec).

    Returns:
        str: Status message
    """
    cfg = ProfilerConfig(
        combined_activity_threshold_in  = combined_activity_threshold_in,
        combined_activity_threshold_out = combined_activity_threshold_out,
        single_side_activity_threshold  = single_side_activity_threshold,
        peak_balance_threshold          = peak_balance_threshold,
    )

    print("Loading wallet_events and wallet_summary...")
    wallet_events  = pd.read_parquet(config.WALLET_EVENTS_FILE)
    wallet_summary = pd.read_parquet(config.WALLET_SUMMARY_FILE)

    profiler, excluded = _build_wallet_profiler_table(wallet_events, wallet_summary, cfg)

    valid = validate_profiler_table(profiler)
    if not valid:
        raise RuntimeError("Profiler validation failed — see output above.")

    profiler.to_parquet(config.WALLET_PROFILER_FILE, index=False)

    excl_counts = excluded["exclusion_reason"].value_counts().to_dict()

    metadata = _read_json(config.METADATA_FILE)
    metadata["wallet_profiler_wallet_count"]    = len(profiler)
    metadata["wallet_profiler_excluded_count"]  = len(excluded)
    metadata["wallet_profiler_excl_breakdown"]  = excl_counts
    metadata["wallet_profiler_built_utc"]       = datetime.now(timezone.utc).isoformat()
    metadata["wallet_profiler_config"] = {
        "combined_activity_threshold_in":  cfg.combined_activity_threshold_in,
        "combined_activity_threshold_out": cfg.combined_activity_threshold_out,
        "single_side_activity_threshold":  cfg.single_side_activity_threshold,
        "peak_balance_threshold":          cfg.peak_balance_threshold,
    }
    _write_json(metadata, config.METADATA_FILE)

    return (
        f"Wallet profiler built. {len(profiler):,} candidate wallets, "
        f"{len(excluded):,} excluded."
    )


def publish_public_dataset():
    """
    Copy tibbir_transfers_master.parquet to gs://<bucket>/public/ and make
    it publicly readable, along with a metadata.json describing the dataset.

    Called at the end of the scheduled pipeline to keep the public snapshot fresh.

    Returns:
        str: Status message with public URLs.
    """
    BASE_URL       = config.PUBLIC_BASE_URL
    fs             = _get_fs()

    COLUMN_SCHEMA = [
        {"name": "event_id",         "dtype": "string",  "description": "Unique transfer identifier (Alchemy uniqueId)"},
        {"name": "block_number",     "dtype": "int64",   "description": "Block number of the transfer"},
        {"name": "timestamp",        "dtype": "string",  "description": "ISO 8601 block timestamp (UTC)"},
        {"name": "tx_hash",          "dtype": "string",  "description": "Transaction hash"},
        {"name": "from_address",     "dtype": "string",  "description": "Sender address (lowercase hex)"},
        {"name": "to_address",       "dtype": "string",  "description": "Receiver address (lowercase hex)"},
        {"name": "raw_amount",       "dtype": "string",  "description": "Transfer amount as 18-decimal integer string — use this for full precision arithmetic"},
        {"name": "decimals",         "dtype": "int64",   "description": "Token decimal places (always 18 for TIBBIR)"},
        {"name": "amount",           "dtype": "float64", "description": "Transfer amount in TIBBIR units (raw_amount / 10^18)"},
        {"name": "contract_address", "dtype": "string",  "description": "TIBBIR ERC-20 contract address"},
        {"name": "category",         "dtype": "string",  "description": "Alchemy transfer category (always 'erc20')"},
        {"name": "asset",            "dtype": "string",  "description": "Token symbol (TIBBIR)"},
    ]

    print("Loading master transfers...")
    df = pd.read_parquet(config.MASTER_FILE)
    print(f"  {len(df):,} rows")

    # Populate example values from a mid-dataset row
    sample_row = df.iloc[len(df) // 2]
    for col in COLUMN_SCHEMA:
        val = sample_row.get(col["name"], None)
        col["example"] = str(val) if val is not None else None

    print("Writing transfers_master.parquet...")
    with fs.open(f"{config.PUBLIC_GCS_PREFIX}/transfers_master.parquet", 'wb') as f:
        df.to_parquet(f, index=False)

    print("Writing sample_transfers.parquet (1,000 rows)...")
    with fs.open(f"{config.PUBLIC_GCS_PREFIX}/sample_transfers.parquet", 'wb') as f:
        df.head(1_000).to_parquet(f, index=False)

    schema = {
        "dataset":   "TIBBIR ERC-20 Token Transfers",
        "columns":   COLUMN_SCHEMA,
        "notes": [
            "The zero address (0x0000000000000000000000000000000000000000) appears as from_address on mint events.",
            "raw_amount is stored as a string to preserve full 18-decimal integer precision. Convert with int(raw_amount) / 10**18.",
            "amount (float64) may lose sub-token precision on very large transfers — prefer raw_amount for exact arithmetic.",
            "Addresses are always lowercase.",
        ],
        "quickstart_python": (
            "import pandas as pd\n"
            "df = pd.read_parquet('https://storage.googleapis.com/tibson-public/transfers_master.parquet')\n"
            "# or load the sample first:\n"
            "sample = pd.read_parquet('https://storage.googleapis.com/tibson-public/sample_transfers.parquet')"
        ),
    }

    print("Writing schema.json...")
    _write_json(schema, f"{config.PUBLIC_GCS_PREFIX}/schema.json")

    now_utc = datetime.now(timezone.utc).isoformat()
    meta = {
        "dataset":          "TIBBIR ERC-20 Token Transfers",
        "description":      (
            "Complete on-chain transfer history for the TIBBIR token on Base (EVM). "
            "Updated hourly. Each row is one ERC-20 Transfer event."
        ),
        "chain":            config.CHAIN,
        "contract_address": config.CONTRACT_ADDRESS,
        "last_updated_utc": now_utc,
        "row_count":        len(df),
        "first_block":      int(df['block_number'].min()),
        "last_block":       int(df['block_number'].max()),
        "first_timestamp":  str(df['timestamp'].min()),
        "last_timestamp":   str(df['timestamp'].max()),
        "files": {
            "transfers_master": {
                "url":         f"{BASE_URL}/transfers_master.parquet",
                "format":      "parquet",
                "description": "Full transfer history — all {row_count:,} rows".replace("{row_count:,}", f"{len(df):,}"),
            },
            "sample_transfers": {
                "url":         f"{BASE_URL}/sample_transfers.parquet",
                "format":      "parquet",
                "description": "First 1,000 rows — quick preview without downloading the full dataset",
            },
            "schema": {
                "url":         f"{BASE_URL}/schema.json",
                "format":      "json",
                "description": "Column definitions, dtypes, example values, and Python quickstart",
            },
            "metadata": {
                "url":         f"{BASE_URL}/metadata.json",
                "format":      "json",
                "description": "Dataset-level stats and file listing (this file)",
            },
        },
    }

    print("Writing metadata.json...")
    _write_json(meta, f"{config.PUBLIC_GCS_PREFIX}/metadata.json")

    return (
        f"Public dataset published. {len(df):,} rows.\n"
        f"  {BASE_URL}/transfers_master.parquet\n"
        f"  {BASE_URL}/sample_transfers.parquet\n"
        f"  {BASE_URL}/schema.json\n"
        f"  {BASE_URL}/metadata.json"
    )
