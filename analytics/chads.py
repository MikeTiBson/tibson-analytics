import pandas as pd

import config


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
DEAD_ADDRESS = "0x000000000000000000000000000000000000dead"

CHAD_COHORTS = [
    ("10k-100k", 10_000, 100_000),
    ("100k-1M", 100_000, 1_000_000),
    ("1M+", 1_000_000, None),
]

CHAD_COHORT_COLUMNS = [
    "date",
    "cohort",
    "min_balance",
    "max_balance",
    "balance",
    "wallet_count",
    "total_balance",
    "avg_current_balance",
    "avg_coin_age_days",
    "avg_retention_ratio",
    "avg_turnover_ratio",
]

CHAD_WALLET_COLUMNS = [
    "cohort",
    "wallet_address",
    "basescan_url",
    "current_balance",
    "peak_balance",
    "retention_ratio",
    "turnover_ratio",
    "avg_coin_age_days",
    "total_received",
    "total_sent",
    "tx_in",
    "tx_out",
    "first_seen_timestamp",
    "last_seen_timestamp",
]


def _empty_result():
    return pd.DataFrame(columns=CHAD_COHORT_COLUMNS)


def _empty_wallets():
    return pd.DataFrame(columns=CHAD_WALLET_COLUMNS)


def _excluded_addresses(known_addresses):
    excluded = {ZERO_ADDRESS, DEAD_ADDRESS}
    for addr, meta in (known_addresses or {}).items():
        if not isinstance(meta, dict):
            continue
        if meta.get("type") in {"exchange", "burn", "router", "lp"}:
            excluded.add(str(addr).lower())
    return excluded


def _assign_cohort(balance):
    for label, low, high in CHAD_COHORTS:
        if balance >= low and (high is None or balance < high):
            return label
    return None


def _wallet_peak_balances(wallet_events):
    events = wallet_events.copy()
    if events.empty:
        return pd.Series(dtype="float64", name="peak_balance")

    events["log_index"] = events["event_id"].str.rsplit(":", n=1).str[-1].astype(int)
    events = events.sort_values(["address", "block_number", "log_index"])
    events["signed_amount"] = events["amount"].where(events["direction"] == "in", -events["amount"])
    events["running_balance"] = events.groupby("address", sort=False)["signed_amount"].cumsum()
    return events.groupby("address")["running_balance"].max().rename("peak_balance")


def _latest_coin_age(coin_age_snapshots):
    if coin_age_snapshots is None or coin_age_snapshots.empty:
        return pd.DataFrame(columns=["address", "avg_age"])

    age = coin_age_snapshots.copy()
    age["address"] = age["address"].astype(str).str.lower()
    age["week_start"] = pd.to_datetime(age["week_start"])
    return (
        age.sort_values("week_start")
        .groupby("address")
        .tail(1)[["address", "avg_age"]]
    )


def _current_cohort_metrics(wallets):
    rows = []
    for label, low, high in CHAD_COHORTS:
        cohort = wallets[wallets["cohort"] == label]
        total_balance = float(cohort["balance"].sum())
        avg_current_balance = float(cohort["balance"].mean()) if not cohort.empty else 0.0

        age_rows = cohort.dropna(subset=["avg_age"])
        if not age_rows.empty and age_rows["balance"].sum() > 0:
            avg_coin_age = float((age_rows["avg_age"] * age_rows["balance"]).sum() / age_rows["balance"].sum())
        else:
            avg_coin_age = 0.0

        rows.append({
            "cohort": label,
            "min_balance": low,
            "max_balance": high,
            "wallet_count": int(len(cohort)),
            "total_balance": total_balance,
            "avg_current_balance": avg_current_balance,
            "avg_coin_age_days": avg_coin_age,
            "avg_retention_ratio": float(cohort["retention_ratio"].mean()) if not cohort.empty else 0.0,
            "avg_turnover_ratio": float(cohort["turnover_ratio"].mean()) if not cohort.empty else 0.0,
        })

    return pd.DataFrame(rows)


def _cohort_history(wallet_events, wallets):
    if wallet_events.empty or wallets.empty:
        return pd.DataFrame(columns=["date", "cohort", "balance"])

    wallet_cohorts = wallets[["address", "cohort"]]
    events = wallet_events.merge(wallet_cohorts, on="address", how="inner")
    events["date"] = pd.to_datetime(events["timestamp"], utc=True).dt.date
    events["signed_amount"] = events["amount"].where(events["direction"] == "in", -events["amount"])

    daily = (
        events.groupby(["date", "cohort"], observed=False)["signed_amount"]
        .sum()
        .rename("daily_delta")
        .reset_index()
    )
    if daily.empty:
        return pd.DataFrame(columns=["date", "cohort", "balance"])

    dates = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D").date
    index = pd.MultiIndex.from_product(
        [dates, [label for label, _, _ in CHAD_COHORTS]],
        names=["date", "cohort"],
    )
    history = (
        daily.set_index(["date", "cohort"])
        .reindex(index, fill_value=0)
        .groupby("cohort", observed=False)["daily_delta"]
        .cumsum()
        .clip(lower=0)
        .rename("balance")
        .reset_index()
    )
    return history


def select_chad_wallets(
    wallet_events,
    wallet_summary,
    coin_age_snapshots=None,
    known_addresses=None,
    retention_threshold=0.90,
    turnover_threshold=0.20,
):
    """
    Select current chad wallets and attach cohort-level verification metrics.
    """
    summary = wallet_summary.copy()
    if summary.empty:
        return pd.DataFrame()

    summary["address"] = summary["address"].astype(str).str.lower()
    summary = summary[
        (summary["balance"] > 0)
        & (~summary["address"].isin(_excluded_addresses(known_addresses)))
    ].copy()
    summary["cohort"] = summary["balance"].apply(_assign_cohort)
    summary = summary.dropna(subset=["cohort"])
    if summary.empty:
        return pd.DataFrame()

    events = wallet_events.copy()
    events["address"] = events["address"].astype(str).str.lower()
    events = events[events["address"].isin(summary["address"])].copy()

    peak = _wallet_peak_balances(events)
    wallets = summary.merge(peak, on="address", how="left")
    wallets["peak_balance"] = wallets["peak_balance"].fillna(wallets["balance"])
    wallets["retention_ratio"] = (wallets["balance"] / wallets["peak_balance"]).clip(upper=1)
    wallets["turnover_ratio"] = (
        wallets["total_sent"] / wallets["total_received"].where(wallets["total_received"] > 0)
    ).fillna(0)

    wallets = wallets[
        (wallets["retention_ratio"] >= retention_threshold)
        & (wallets["turnover_ratio"] < turnover_threshold)
    ].copy()
    if wallets.empty:
        return pd.DataFrame()

    return wallets.merge(_latest_coin_age(coin_age_snapshots), on="address", how="left")


def build_chad_wallets(
    wallet_events,
    wallet_summary,
    coin_age_snapshots=None,
    known_addresses=None,
    retention_threshold=0.90,
    turnover_threshold=0.20,
):
    """
    Build current wallet-level chad rows for dashboard verification tables.
    """
    wallets = select_chad_wallets(
        wallet_events=wallet_events,
        wallet_summary=wallet_summary,
        coin_age_snapshots=coin_age_snapshots,
        known_addresses=known_addresses,
        retention_threshold=retention_threshold,
        turnover_threshold=turnover_threshold,
    )
    if wallets.empty:
        return _empty_wallets()

    result = wallets.rename(columns={
        "address": "wallet_address",
        "balance": "current_balance",
        "avg_age": "avg_coin_age_days",
        "first_ts": "first_seen_timestamp",
        "last_ts": "last_seen_timestamp",
    }).copy()
    result["basescan_url"] = (
        "https://basescan.org/token/"
        + config.CONTRACT_ADDRESS
        + "?a="
        + result["wallet_address"]
        + "#transactions"
    )
    result = result.sort_values(["cohort", "current_balance"], ascending=[True, False])
    return result[CHAD_WALLET_COLUMNS].reset_index(drop=True)


def build_chad_cohorts(
    wallet_events,
    wallet_summary,
    coin_age_snapshots=None,
    known_addresses=None,
    retention_threshold=0.90,
    turnover_threshold=0.20,
):
    """
    Build "chad" cohort holdings history for dashboard display.

    A chad is a current holder in one of the three tracked size buckets whose
    current balance is at least 90% of peak balance and whose sold/bought
    turnover is below 20%. Known market-infrastructure and burn addresses are
    excluded. Cohort membership is based on current balances, then those
    selected wallets are replayed historically to produce one daily balance row
    per cohort. Average coin age is a current balance-weighted cohort metric.
    """
    wallets = select_chad_wallets(
        wallet_events=wallet_events,
        wallet_summary=wallet_summary,
        coin_age_snapshots=coin_age_snapshots,
        known_addresses=known_addresses,
        retention_threshold=retention_threshold,
        turnover_threshold=turnover_threshold,
    )
    if wallets.empty:
        return _empty_result()

    events = wallet_events.copy()
    events["address"] = events["address"].astype(str).str.lower()
    events = events[events["address"].isin(wallets["address"])].copy()

    metrics = _current_cohort_metrics(wallets)
    history = _cohort_history(events, wallets)
    if history.empty:
        return _empty_result()

    result = history.merge(metrics, on="cohort", how="left")
    result["date"] = pd.to_datetime(result["date"]).dt.date
    return result[CHAD_COHORT_COLUMNS]
