from dataclasses import dataclass, field
import pandas as pd


@dataclass
class ProfilerConfig:
    combined_activity_threshold_in:  int   = 1_000
    combined_activity_threshold_out: int   = 1_000
    single_side_activity_threshold:  int   = 10_000
    peak_balance_threshold:          float = 1_000_000.0


def filter_wallets(wallet_summary_df, cfg=None):
    """
    Split wallet_summary into (included, excluded).

    excluded has an extra 'exclusion_reason' column with pipe-separated labels:
      excluded_combined_activity | excluded_high_tx_in | excluded_high_tx_out

    Returns: (included_df, excluded_df)
    """
    if cfg is None:
        cfg = ProfilerConfig()

    ws = wallet_summary_df.copy()

    excl_combined = (
        (ws["tx_in"]  > cfg.combined_activity_threshold_in) &
        (ws["tx_out"] > cfg.combined_activity_threshold_out)
    )
    excl_high_in  = ws["tx_in"]  > cfg.single_side_activity_threshold
    excl_high_out = ws["tx_out"] > cfg.single_side_activity_threshold

    excluded_mask = excl_combined | excl_high_in | excl_high_out

    reason_df = pd.DataFrame({
        "excluded_combined_activity": excl_combined[excluded_mask],
        "excluded_high_tx_in":        excl_high_in[excluded_mask],
        "excluded_high_tx_out":       excl_high_out[excluded_mask],
    })
    excluded = ws[excluded_mask].copy()
    excluded["exclusion_reason"] = reason_df.apply(
        lambda row: "|".join(col for col in reason_df.columns if row[col]), axis=1
    ).values

    return ws[~excluded_mask].copy(), excluded


def _extract_log_index(event_id_series):
    """Extract integer log index from '<txhash>:log:<n>' event_id strings."""
    return event_id_series.str.rsplit(":", n=1).str[-1].astype(int)


def compute_peak_balances(addresses, wallet_events_df):
    """
    Replay balance history for given addresses to find peak_balance and its timestamp.

    Sorted by (block_number, log_index) — extracted from event_id — for correct
    intra-block ordering as required by the spec.

    Returns DataFrame: address, peak_balance, peak_balance_timestamp
    """
    addr_set = set(addresses)
    events = wallet_events_df[wallet_events_df["address"].isin(addr_set)].copy()

    events["log_index"] = _extract_log_index(events["event_id"])
    events = events.sort_values(["address", "block_number", "log_index"])

    events["signed"] = events["amount"].where(events["direction"] == "in", -events["amount"])
    events["running_balance"] = events.groupby("address", sort=False)["signed"].cumsum()

    peak_idx = events.groupby("address")["running_balance"].idxmax()
    peak = events.loc[peak_idx, ["address", "running_balance", "timestamp"]].copy()
    peak.columns = ["address", "peak_balance", "peak_balance_timestamp"]

    return peak.reset_index(drop=True)


def build_wallet_profiler_table(wallet_events_df, wallet_summary_df, cfg=None):
    """
    Build the candidate wallet profiler table.

    Pipeline:
      1. Filter by activity thresholds (exchange/system wallet exclusion)
      2. Replay wallet histories to compute peak_balance
      3. Filter to peak_balance >= cfg.peak_balance_threshold
      4. Join with summary stats and compute derived fields

    Returns: (profiler_df, excluded_df)
      profiler_df   — candidate wallet universe, one row per wallet
      excluded_df   — all excluded wallets with exclusion_reason
    """
    if cfg is None:
        cfg = ProfilerConfig()

    # Step 1: activity filter
    included, excluded_activity = filter_wallets(wallet_summary_df, cfg)
    print(f"Activity filter: {len(included):,} included, {len(excluded_activity):,} excluded")

    # Step 2: peak balance replay
    print("Replaying wallet histories for peak balance...")
    peak = compute_peak_balances(included["address"].tolist(), wallet_events_df)

    # Step 3: join and apply peak balance filter
    merged = included.merge(peak, on="address", how="left")
    merged["peak_balance"] = merged["peak_balance"].fillna(merged["balance"])
    merged["peak_balance_timestamp"] = merged["peak_balance_timestamp"].fillna(merged["last_ts"])

    profiler = merged[merged["peak_balance"] >= cfg.peak_balance_threshold].copy()
    below = merged[merged["peak_balance"] < cfg.peak_balance_threshold].copy()
    below["exclusion_reason"] = "below_peak_balance_threshold"

    print(f"Peak balance filter (>= {cfg.peak_balance_threshold:,.0f}): {len(profiler):,} wallets kept")

    # Step 4: derived fields
    # Clamp sub-epsilon negative balances (float64 precision noise from summing many amounts)
    profiler["balance"] = profiler["balance"].clip(lower=0)
    profiler["retention_ratio"] = (
        (profiler["balance"] / profiler["peak_balance"]).clip(0, 1)
    )
    profiler["wallet_age_days"] = (
        (pd.to_datetime(profiler["last_ts"],   utc=True) -
         pd.to_datetime(profiler["first_ts"],  utc=True))
        .dt.total_seconds() / 86_400
    ).round(1)

    # Step 5: rename and select columns
    profiler = profiler.rename(columns={
        "address":        "wallet_address",
        "balance":        "current_balance",
        "total_received": "total_in",
        "total_sent":     "total_out",
        "first_ts":       "first_seen_timestamp",
        "last_ts":        "last_seen_timestamp",
    })

    out_cols = [
        "wallet_address",
        "current_balance", "peak_balance", "peak_balance_timestamp",
        "retention_ratio",
        "total_in", "total_out",
        "tx_in", "tx_out",
        "first_seen_timestamp", "last_seen_timestamp",
        "wallet_age_days",
        "first_block", "last_block",
    ]
    profiler = (
        profiler[out_cols]
        .sort_values("peak_balance", ascending=False)
        .reset_index(drop=True)
    )

    all_excluded = pd.concat([excluded_activity, below], ignore_index=True)

    return profiler, all_excluded


def validate_profiler_table(profiler_df):
    """
    Run sanity checks on the profiler table. Prints a report.
    Returns True if all checks pass.
    """
    issues = []

    neg_balance = (profiler_df["current_balance"] < 0).sum()
    if neg_balance:
        issues.append(f"  {neg_balance} wallets with negative current_balance")

    peak_lt_current = (profiler_df["peak_balance"] < profiler_df["current_balance"] - 1e-6).sum()
    if peak_lt_current:
        issues.append(f"  {peak_lt_current} wallets where peak_balance < current_balance")

    bad_retention = (
        (profiler_df["retention_ratio"] < 0) | (profiler_df["retention_ratio"] > 1 + 1e-6)
    ).sum()
    if bad_retention:
        issues.append(f"  {bad_retention} wallets with retention_ratio outside [0, 1]")

    if issues:
        print("Validation FAILED:")
        for msg in issues:
            print(msg)
        return False

    print(f"Validation passed. {len(profiler_df):,} wallets, "
          f"peak_balance range: {profiler_df['peak_balance'].min():,.0f} – "
          f"{profiler_df['peak_balance'].max():,.0f}")
    return True
