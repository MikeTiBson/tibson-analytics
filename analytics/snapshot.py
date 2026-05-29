import pandas as pd

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def build_balance_snapshot(transfers_df, block=None):
    """
    Build balance snapshot from transfer ledger.

    Parameters:
        transfers_df (DataFrame): master transfer ledger
        block (int or None): if provided, only include transfers <= block

    Returns:
        DataFrame: address | raw_balance (int)
    """

    df = transfers_df.copy()

    if block is not None:
        df = df[df["block_number"] <= block]

    # Ensure raw_amount is integer
    df["raw_amount"] = df["raw_amount"].astype(object).apply(int)

    # Aggregate incoming and outgoing
    incoming = df.groupby("to_address")["raw_amount"].sum()
    outgoing = df.groupby("from_address")["raw_amount"].sum()

    balances = incoming.sub(outgoing, fill_value=0)

    snapshot = balances.reset_index()
    snapshot.columns = ["address", "raw_balance"]

    # Remove zero balances
    snapshot = snapshot[snapshot["raw_balance"] != 0]

    # Remove zero address (mint/burn sink)
    snapshot = snapshot[snapshot["address"] != ZERO_ADDRESS]

    return snapshot


def bucket_holders(snapshot_df, decimals=18):
    """
    Bucket holders by balance size.

    Returns:
        DataFrame with:
            bucket
            holders
            total_balance_raw
            total_balance (human units)
    """

    df = snapshot_df.copy()

    # Convert to human units only for bucketing
    df["balance"] = df["raw_balance"] / (10 ** decimals)

    bins = [
        0,
        1,
        1_000,
        10_000,
        100_000,
        1_000_000,
        float("inf")
    ]

    labels = [
        "<1",
        "1-1k",
        "1k-10k",
        "10k-100k",
        "100k-1M",
        "1M+"
    ]

    df["bucket"] = pd.cut(df["balance"], bins=bins, labels=labels, right=False)

    summary = df.groupby("bucket").agg(
        holders=("address", "count"),
        total_balance_raw=("raw_balance", "sum")
    ).reset_index()

    # Add human-readable balance column safely
    summary["total_balance"] = summary["total_balance_raw"] / (10 ** decimals)

    return summary


def apply_transfers_to_snapshot(snapshot_df, transfers_df):
    """
    Incrementally update a balance snapshot with new transfers.

    Parameters:
        snapshot_df (DataFrame): Existing snapshot with address | raw_balance
        transfers_df (DataFrame): New transfers to apply

    Returns:
        DataFrame: Updated snapshot with address | raw_balance
    """
    if transfers_df.empty:
        return snapshot_df.copy()

    # Start with existing balances as a Series
    balances = snapshot_df.set_index("address")["raw_balance"].copy()

    # Ensure raw_amount is integer
    transfers = transfers_df.copy()
    transfers["raw_amount"] = transfers["raw_amount"].astype(object).apply(int)

    # Aggregate incoming and outgoing from new transfers
    incoming = transfers.groupby("to_address")["raw_amount"].sum()
    outgoing = transfers.groupby("from_address")["raw_amount"].sum()

    # Apply incoming (add to balances)
    for addr, amount in incoming.items():
        if addr in balances.index:
            balances[addr] += amount
        else:
            balances[addr] = amount

    # Apply outgoing (subtract from balances)
    for addr, amount in outgoing.items():
        if addr in balances.index:
            balances[addr] -= amount
        else:
            balances[addr] = -amount

    # Convert back to DataFrame
    snapshot = balances.reset_index()
    snapshot.columns = ["address", "raw_balance"]

    # Remove zero balances
    snapshot = snapshot[snapshot["raw_balance"] != 0]

    # Remove zero address (mint/burn sink)
    snapshot = snapshot[snapshot["address"] != ZERO_ADDRESS]

    return snapshot


def build_daily_holder_growth(transfers_df, decimals=18):
    """
    Build daily time-series of wallet counts across 5 balance buckets.
    Buckets (in token units): 0-1k, 1k-10k, 10k-100k, 100k-1M, 1M+.

    Returns:
        DataFrame with columns:
            date,
            count_0_1k, count_1k_10k, count_10k_100k, count_100k_1m, count_1m_plus,
            total_holders
    """
    df = transfers_df.copy()
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    dates = sorted(df["date"].unique())

    B1k   = int(1_000     * (10 ** decimals))
    B10k  = int(10_000    * (10 ** decimals))
    B100k = int(100_000   * (10 ** decimals))
    B1m   = int(1_000_000 * (10 ** decimals))

    results = []

    for date in dates:
        snapshot = build_balance_snapshot(df[df["date"] <= date])
        if snapshot.empty:
            continue

        c0_1k     = int((snapshot["raw_balance"] < B1k).sum())
        c1k_10k   = int(((snapshot["raw_balance"] >= B1k)   & (snapshot["raw_balance"] < B10k)).sum())
        c10k_100k = int(((snapshot["raw_balance"] >= B10k)  & (snapshot["raw_balance"] < B100k)).sum())
        c100k_1m  = int(((snapshot["raw_balance"] >= B100k) & (snapshot["raw_balance"] < B1m)).sum())
        c1m_plus  = int((snapshot["raw_balance"] >= B1m).sum())

        results.append({
            "date":           date,
            "count_0_1k":     c0_1k,
            "count_1k_10k":   c1k_10k,
            "count_10k_100k": c10k_100k,
            "count_100k_1m":  c100k_1m,
            "count_1m_plus":  c1m_plus,
            "total_holders":  c0_1k + c1k_10k + c10k_100k + c100k_1m + c1m_plus,
        })

    return pd.DataFrame(results)


def build_daily_bucket_breakdown(transfers_df, decimals=18):
    """
    Build daily time-series of holder distribution across 5 balance buckets.
    Buckets (in token units): 0-1k, 1k-10k, 10k-100k, 100k-1M, 1M+.

    Returns:
        DataFrame with columns:
            date,
            pct_0_1k, pct_1k_10k, pct_10k_100k, pct_100k_1m, pct_1m_plus  (% of total supply),
            count_0_1k, count_1k_10k, count_10k_100k, count_100k_1m, count_1m_plus  (wallet counts)
    """
    df = transfers_df.copy()
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    dates = sorted(df["date"].unique())

    B1k   = int(1_000     * (10 ** decimals))
    B10k  = int(10_000    * (10 ** decimals))
    B100k = int(100_000   * (10 ** decimals))
    B1m   = int(1_000_000 * (10 ** decimals))

    results = []

    for date in dates:
        snapshot = build_balance_snapshot(df[df["date"] <= date])
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

        results.append({
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

    return pd.DataFrame(results)
