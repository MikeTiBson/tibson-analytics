from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import pandas as pd


@dataclass
class WalletState:
    balance:      float = 0.0
    age_mass:     float = 0.0   # sum of (each coin's balance * its age in days)
    tx_in_total:  int   = 0
    tx_out_total: int   = 0

    def avg_age(self) -> float:
        return self.age_mass / self.balance if self.balance > 0 else 0.0

    def apply_time(self, delta_days: float):
        self.age_mass += self.balance * delta_days

    def apply_incoming(self, amount: float):
        self.balance += amount
        self.tx_in_total += 1

    def apply_outgoing(self, amount: float):
        if self.balance > 0:
            frac = min(amount / self.balance, 1.0)  # clamp: float rounding can make amount > balance
            self.age_mass *= (1.0 - frac)
            self.age_mass = max(self.age_mass, 0.0)
        self.balance = max(self.balance - amount, 0.0)
        self.tx_out_total += 1


def _floor_to_monday(dt) -> datetime:
    if isinstance(dt, datetime):
        d = dt.date()
    else:
        d = dt
    monday = d - timedelta(days=d.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def build_weekly_snapshots(address: str, transfers_df: pd.DataFrame, decimals: int = 18) -> pd.DataFrame:
    """
    Build weekly coin age snapshots for a single wallet.

    Iterates the transfer ledger chronologically, tracking WalletState and
    emitting one row per Monday 00:00 UTC boundary up to now.

    Returns DataFrame with columns:
        address, week_start (date), balance, avg_age (days),
        tx_in_total, tx_out_total
    """
    addr = address.lower()
    df = transfers_df[
        (transfers_df["from_address"] == addr) | (transfers_df["to_address"] == addr)
    ].copy()

    if df.empty:
        return pd.DataFrame(columns=["address", "week_start", "balance", "avg_age", "tx_in_total", "tx_out_total"])

    df["_amount"] = df["raw_amount"].apply(int) / 10 ** decimals
    df["_ts"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("_ts").reset_index(drop=True)

    state         = WalletState()
    current       = df["_ts"].iloc[0]
    next_boundary = _floor_to_monday(current) + timedelta(weeks=1)
    snapshots     = []

    for _, row in df.iterrows():
        ts     = row["_ts"]
        amount = row["_amount"]

        while next_boundary <= ts:
            delta = (next_boundary - current).total_seconds() / 86400
            state.apply_time(delta)
            snapshots.append({
                "address":      addr,
                "week_start":   (next_boundary - timedelta(weeks=1)).date(),
                "balance":      state.balance,
                "avg_age":      state.avg_age(),
                "tx_in_total":  state.tx_in_total,
                "tx_out_total": state.tx_out_total,
            })
            current       = next_boundary
            next_boundary += timedelta(weeks=1)

        delta = (ts - current).total_seconds() / 86400
        state.apply_time(delta)
        current = ts

        if row["to_address"] == addr:
            state.apply_incoming(amount)
        if row["from_address"] == addr:
            state.apply_outgoing(amount)

    now = datetime.now(tz=timezone.utc)
    while next_boundary <= now:
        delta = (next_boundary - current).total_seconds() / 86400
        state.apply_time(delta)
        snapshots.append({
            "address":      addr,
            "week_start":   (next_boundary - timedelta(weeks=1)).date(),
            "balance":      state.balance,
            "avg_age":      state.avg_age(),
            "tx_in_total":  state.tx_in_total,
            "tx_out_total": state.tx_out_total,
        })
        current       = next_boundary
        next_boundary += timedelta(weeks=1)

    return pd.DataFrame(snapshots)


def project_snapshots_forward(last_rows: pd.DataFrame, up_to_week: date) -> pd.DataFrame:
    """
    Extend snapshots for wallets that had no new transfers by advancing time.

    last_rows: one row per wallet — their most recent snapshot.
    up_to_week: the latest week_start to project up to (inclusive).

    Returns new rows for each (wallet × new_week) from (last_week + 7d) to up_to_week.
    Age advances by 7 days per week; balance and tx counts are unchanged.
    """
    results = []
    for _, row in last_rows.iterrows():
        week = row["week_start"]
        if isinstance(week, str):
            week = date.fromisoformat(week)
        balance      = row["balance"]
        age_mass     = balance * row["avg_age"]   # recover age_mass
        tx_in        = row["tx_in_total"]
        tx_out       = row["tx_out_total"]
        addr         = row["address"]

        next_week = week + timedelta(weeks=1)
        while next_week <= up_to_week:
            age_mass += balance * 7.0
            results.append({
                "address":      addr,
                "week_start":   next_week,
                "balance":      balance,
                "avg_age":      age_mass / balance if balance > 0 else 0.0,
                "tx_in_total":  tx_in,
                "tx_out_total": tx_out,
            })
            next_week += timedelta(weeks=1)

    return pd.DataFrame(results) if results else pd.DataFrame(
        columns=["address", "week_start", "balance", "avg_age", "tx_in_total", "tx_out_total"]
    )
