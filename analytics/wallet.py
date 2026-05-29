import pandas as pd

_ZERO_ADDR = "0x0000000000000000000000000000000000000000"


def build_wallet_events(transfers_df, decimals=18):
    """
    Expand the master transfer ledger into a wallet-centric event log.

    Each transfer becomes two rows — one for the sender ("out") and one for
    the receiver ("in") — from the perspective of that wallet. The zero
    address (minting source / burn sink) is excluded as a wallet; transfers
    where it is the counterparty are kept.

    Returns DataFrame sorted by (address, block_number).
    Columns: address, event_id, block_number, timestamp, direction,
             counterparty, raw_amount, amount
    """
    df = transfers_df.copy()
    df["amount"] = df["raw_amount"].apply(int) / (10 ** decimals)

    inc = (
        df[df["to_address"] != _ZERO_ADDR]
        [["to_address", "event_id", "block_number", "timestamp",
          "from_address", "raw_amount", "amount"]]
        .rename(columns={"to_address": "address", "from_address": "counterparty"})
        .assign(direction="in")
    )

    out = (
        df[df["from_address"] != _ZERO_ADDR]
        [["from_address", "event_id", "block_number", "timestamp",
          "to_address", "raw_amount", "amount"]]
        .rename(columns={"from_address": "address", "to_address": "counterparty"})
        .assign(direction="out")
    )

    events = (
        pd.concat([inc, out], ignore_index=True)
        .sort_values(["address", "block_number"])
        .reset_index(drop=True)
    )

    return events[["address", "event_id", "block_number", "timestamp",
                   "direction", "counterparty", "raw_amount", "amount"]]


def build_wallet_summary(transfers_df, decimals=18):
    """
    Derive a per-wallet summary from the master transfer ledger.

    Columns: address, balance, tx_in, tx_out, total_received, total_sent,
             first_block, last_block, first_ts, last_ts

    No classifications — raw stats only.
    """
    df = transfers_df.copy()
    df["_amount"] = df["raw_amount"].apply(int) / (10 ** decimals)
    df["_ts"] = pd.to_datetime(df["timestamp"], utc=True)

    inc = df[df["to_address"] != _ZERO_ADDR]
    out = df[df["from_address"] != _ZERO_ADDR]

    all_addrs = pd.Index(
        pd.concat([inc["to_address"], out["from_address"]]).unique()
    )

    inc_agg = inc.groupby("to_address").agg(
        tx_in          =("event_id","count"),
        total_received =("_amount", "sum"),
    ).reindex(all_addrs)

    out_agg = out.groupby("from_address").agg(
        tx_out     =("event_id","count"),
        total_sent =("_amount", "sum"),
    ).reindex(all_addrs)

    # Compute first/last block and timestamp across both directions in one pass
    timing = (
        pd.concat([
            inc[["to_address",   "block_number", "_ts"]].rename(columns={"to_address":   "addr"}),
            out[["from_address", "block_number", "_ts"]].rename(columns={"from_address": "addr"}),
        ], ignore_index=True)
        .groupby("addr")
        .agg(first_block=("block_number","min"), last_block=("block_number","max"),
             first_ts=("_ts","min"), last_ts=("_ts","max"))
        .reindex(all_addrs)
    )

    summary = pd.DataFrame(index=all_addrs)
    summary["balance"]        = inc_agg["total_received"].fillna(0) - out_agg["total_sent"].fillna(0)
    summary["tx_in"]          = inc_agg["tx_in"].fillna(0).astype(int)
    summary["tx_out"]         = out_agg["tx_out"].fillna(0).astype(int)
    summary["total_received"] = inc_agg["total_received"].fillna(0)
    summary["total_sent"]     = out_agg["total_sent"].fillna(0)
    summary["first_block"]    = timing["first_block"].fillna(0).astype(int)
    summary["last_block"]     = timing["last_block"].fillna(0).astype(int)
    summary["first_ts"]       = timing["first_ts"]
    summary["last_ts"]        = timing["last_ts"]

    return (
        summary.reset_index().rename(columns={"index": "address"})
        .sort_values("tx_in", ascending=False)
        .reset_index(drop=True)
    )


def get_wallet_events(address, wallet_events_df):
    """Return all events for a single wallet, sorted by block_number."""
    return (
        wallet_events_df[wallet_events_df["address"] == address]
        .sort_values("block_number")
        .copy()
    )


def replay_wallet_balance(address, wallet_events_df):
    """
    Return a chronological balance timeline for a wallet.

    Columns: block_number, timestamp, direction, counterparty, amount, balance_after
    """
    events = get_wallet_events(address, wallet_events_df)
    if events.empty:
        return events
    signed = events["amount"].where(events["direction"] == "in", -events["amount"])
    events = events.copy()
    events["balance_after"] = signed.cumsum()
    return events[["block_number", "timestamp", "direction", "counterparty",
                   "amount", "balance_after"]].reset_index(drop=True)
