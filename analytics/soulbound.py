import pandas as pd


BUCKETS = [
    ("balance_0_1k", "pct_0_1k", "count_0_1k", 0, 1_000),
    ("balance_1k_10k", "pct_1k_10k", "count_1k_10k", 1_000, 10_000),
    ("balance_10k_100k", "pct_10k_100k", "count_10k_100k", 10_000, 100_000),
    ("balance_100k_1m", "pct_100k_1m", "count_100k_1m", 100_000, 1_000_000),
    ("balance_1m_plus", "pct_1m_plus", "count_1m_plus", 1_000_000, None),
]


def build_soulbound_holder_supply(transfers, holder_addresses, total_supply_raw, decimals=18):
    """
    Build daily TIBBIR balances for the soulbound NFT holder cohort.

    Returns one row per transfer-ledger day with total cohort balance,
    percent of total supply, active cohort holder count, and bucketed balances.
    """
    holders = {addr.lower() for addr in holder_addresses if isinstance(addr, str)}
    if not holders:
        return pd.DataFrame()

    df = transfers.copy()
    df["date"] = pd.to_datetime(df["timestamp"], utc=True).dt.date
    df["raw_amount_int"] = df["raw_amount"].apply(int)
    df["from_address"] = df["from_address"].str.lower()
    df["to_address"] = df["to_address"].str.lower()

    parts = []
    inbound = df[df["to_address"].isin(holders)]
    if not inbound.empty:
        parts.append(
            inbound[["date", "to_address", "raw_amount_int"]]
            .rename(columns={"to_address": "address", "raw_amount_int": "delta_raw"})
        )

    outbound = df[df["from_address"].isin(holders)]
    if not outbound.empty:
        out = (
            outbound[["date", "from_address", "raw_amount_int"]]
            .rename(columns={"from_address": "address", "raw_amount_int": "delta_raw"})
        )
        out["delta_raw"] = -out["delta_raw"]
        parts.append(out)

    if not parts:
        return pd.DataFrame()

    deltas = pd.concat(parts, ignore_index=True)
    daily = deltas.groupby(["date", "address"], as_index=False)["delta_raw"].sum()
    dates = sorted(df["date"].unique())
    addresses = sorted(holders)

    balance_matrix = (
        daily.pivot(index="date", columns="address", values="delta_raw")
        .reindex(index=dates, columns=addresses, fill_value=0)
        .fillna(0)
        .cumsum()
    )

    records = []
    for date, row in balance_matrix.iterrows():
        positive_balances = row[row > 0]
        total_balance_raw = positive_balances.sum()
        token_balances = positive_balances / (10 ** decimals)

        record = {
            "date": date,
            "total_balance": float(total_balance_raw / (10 ** decimals)),
            "pct_total_supply": float(total_balance_raw / total_supply_raw * 100) if total_supply_raw else 0.0,
            "holder_count": int(len(positive_balances)),
            "soulbound_address_count": int(len(holders)),
        }

        for balance_col, pct_col, count_col, lower, upper in BUCKETS:
            mask = token_balances >= lower
            if upper is not None:
                mask &= token_balances < upper
            bucket = token_balances[mask]
            record[balance_col] = float(bucket.sum())
            record[pct_col] = float(bucket.sum() * (10 ** decimals) / total_supply_raw * 100) if total_supply_raw else 0.0
            record[count_col] = int(len(bucket))

        records.append(record)

    return pd.DataFrame(records)
