import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
from datetime import datetime, timezone
from pathlib import Path
import config


@st.cache_resource
def _gcs_fs():
    """Create a gcsfs filesystem using service account credentials from secrets."""
    import gcsfs, tempfile
    creds = {k: v for k, v in st.secrets["connections"]["gcs"].items()}
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(creds, tmp)
    tmp.close()
    return gcsfs.GCSFileSystem(token=tmp.name)


def _is_gcs(path):
    return str(path).startswith("gs://")


def _read_parquet(path, **kwargs):
    if _is_gcs(path):
        with _gcs_fs().open(str(path)) as f:
            return pd.read_parquet(f, **kwargs)
    return pd.read_parquet(path, **kwargs)


def _read_json_file(path):
    if _is_gcs(path):
        with _gcs_fs().open(str(path)) as f:
            return json.load(f)
    with open(path) as f:
        return json.load(f)



st.set_page_config(page_title="tibson analytics", layout="centered")
_TIBSON_IMAGE = Path(__file__).parent / "tibson.avif"
st.title("tibson analytics")
if _TIBSON_IMAGE.exists():
    st.image(str(_TIBSON_IMAGE), width=96)

st.markdown(
    """
    <style>
      div.stButton button[data-testid="stBaseButton-tertiary"],
      div.stButton button[kind="tertiary"] {
        background: transparent !important;
        border: 0 !important;
        color: #38bdf8 !important;
        padding: 0 !important;
        min-height: auto !important;
        text-decoration: underline !important;
        box-shadow: none !important;
      }
      div.stButton button[data-testid="stBaseButton-tertiary"] *,
      div.stButton button[kind="tertiary"] * {
        color: #38bdf8 !important;
        text-decoration: underline !important;
      }
      div.stButton button[data-testid="stBaseButton-tertiary"]:hover,
      div.stButton button[kind="tertiary"]:hover {
        color: #7dd3fc !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

if st.query_params.get("page") == "dataset-details":
    st.session_state["page"] = "dataset-details"
    del st.query_params["page"]
    st.rerun()

IS_COIN_AGE_EXAMPLE = st.query_params.get("page") == "coin-age-example"


def load_metadata():
    try:
        return _read_json_file(config.METADATA_FILE)
    except Exception as e:
        st.error(f"Failed to load metadata: {e}")
        return None


meta = None if IS_COIN_AGE_EXAMPLE else load_metadata()

_ZERO_ADDR = "0x0000000000000000000000000000000000000000"
_DEAD_ADDR = "0x000000000000000000000000000000000000dead"
_BASESCAN  = "https://basescan.org"
DATA_DIR = Path(__file__).parent / "data"
PRICE_CONTEXT_FILE = DATA_DIR / "price_context_events.json"
PRICE_HISTORY_CSV_FILE = DATA_DIR / "price_history.csv"
PLOTLY_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "doubleClick": False,
    "modeBarButtonsToRemove": [
        "autoScale2d",
        "lasso2d",
        "pan2d",
        "resetScale2d",
        "select2d",
        "zoom2d",
        "zoomIn2d",
        "zoomOut2d",
    ],
    "responsive": True,
    "scrollZoom": False,
    "toImageButtonOptions": {
        "format": "png",
        "filename": "tibson-analytics-chart",
        "height": 720,
        "scale": 2,
        "width": 1280,
    },
}
CHART_HEIGHT = 480


def _date_xaxis():
    return dict(title=None)


def _bottom_legend():
    return dict(
        title=None,
        orientation="h",
        yanchor="top",
        y=-0.20,
        xanchor="left",
        x=0,
        font=dict(size=13),
    )


def _make_chart_scroll_safe(fig):
    fig.update_layout(dragmode=False)
    return fig


@st.cache_data
def load_price_context_config():
    with open(PRICE_CONTEXT_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("events", []), data.get("zones", [])


PRICE_EVENTS, PRICE_ZONES = load_price_context_config()


def _price_event_sort_ts(event):
    return pd.to_datetime(event.get("time_utc") or event["date"], utc=True).tz_convert(None)


def _price_event_chart_date(event):
    return pd.to_datetime(event.get("chart_date") or event["date"])


def _visible_price_events(price_events, p_window, mode):
    if mode == "Off" or p_window.empty:
        return []

    visible = []
    min_date = p_window["date"].min()
    max_date = p_window["date"].max()
    for event in price_events:
        section = event.get("section", "lore")
        if mode == "Key events" and section != "key":
            continue
        if mode == "Bonus lore" and section != "lore":
            continue

        chart_date = _price_event_chart_date(event)
        if min_date <= chart_date <= max_date:
            visible.append({
                **event,
                "date": pd.to_datetime(event["date"]),
                "chart_date": chart_date,
                "sort_ts": _price_event_sort_ts(event),
                "tier": event.get("tier", "lore"),
                "group": event.get("group", "Other"),
            })
    return visible


def _format_price_links(links):
    if not isinstance(links, list):
        return ""
    return " ".join(
        f'[{link.get("label", "link")}]({link.get("url", "")})'
        for link in links
        if link.get("url")
    )


def _price_event_display_time(event):
    time_utc = event.get("time_utc")
    if isinstance(time_utc, str) and time_utc:
        return time_utc
    return event["date"].strftime("%Y-%m-%d")


def _price_event_link_text(event):
    extra_links = _format_price_links(event.get("links", []))
    if extra_links:
        return f'{event["title"]} - {extra_links}'
    return event["title"]


def _render_price_event_line(event, bullet="-"):
    links = event.get("links", [])
    if not isinstance(links, list):
        links = []

    if len(links) <= 1:
        st.markdown(f"{bullet} {_price_event_display_time(event)} - {_price_event_link_text(event)}")
        return

    st.markdown(f"{bullet} {_price_event_display_time(event)} - {event['title']}")
    for link in links:
        if link.get("url"):
            st.markdown(f"  - [{link.get('label', 'link')}]({link['url']})")


def _render_price_event_links(event):
    links = event.get("links", [])
    if not isinstance(links, list):
        return

    for link in links:
        if link.get("url"):
            st.markdown(f"- [{link.get('label', 'link')}]({link['url']})")


def _price_context_divider():
    st.markdown("<hr style='margin:0.75rem 0; border-color:rgba(250,250,250,0.12)'>", unsafe_allow_html=True)


def _price_group_heading(group_name, group):
    first_event = group.iloc[0]
    return f"{first_event['date'].strftime('%Y-%m-%d')} - {group_name}"


def _render_key_price_timeline(visible_events):
    events_df = pd.DataFrame(visible_events).sort_values(["sort_ts", "group", "title"])
    rendered_groups = set()
    items = []

    for _, event in events_df.iterrows():
        group_name = event["group"]
        group = events_df[events_df["group"] == group_name].sort_values(["sort_ts", "title"])
        is_major_group = (group["tier"] == "major").any()

        if is_major_group:
            if group_name in rendered_groups:
                continue
            rendered_groups.add(group_name)
            items.append(("major", group_name, group))
            continue

        items.append(("single", None, event))

    for idx, (kind, group_name, payload) in enumerate(items):
        if kind == "major":
            st.markdown(f"**{_price_group_heading(group_name, payload)}**")
            if len(payload) == 1:
                _render_price_event_links(payload.iloc[0])
            else:
                for _, group_event in payload.iterrows():
                    _render_price_event_line(group_event)
        else:
            st.markdown(f"**{_price_event_display_time(payload)}** - {_price_event_link_text(payload)}")

        if idx < len(items) - 1:
            _price_context_divider()


def _render_grouped_price_events(visible_events):
    visible_events_df = pd.DataFrame(visible_events).sort_values(["sort_ts", "group", "title"])
    groups = list(visible_events_df.groupby("group", sort=False))
    for idx, (group_name, group) in enumerate(groups):
        group = group.sort_values(["sort_ts", "title"])
        st.markdown(f"**{group_name}**")
        for _, event in group.iterrows():
            _render_price_event_line(event)
        if idx < len(groups) - 1:
            _price_context_divider()


def _render_lore_price_context(visible_zones, visible_events):
    rendered_any = False

    zone_by_group = {zone.get("group", zone["title"]): zone for zone in visible_zones}
    events_df = pd.DataFrame(visible_events) if visible_events else pd.DataFrame()

    def divider_if_needed():
        nonlocal rendered_any
        if rendered_any:
            _price_context_divider()
        rendered_any = True

    if "No dates zone" in zone_by_group:
        zone = zone_by_group["No dates zone"]
        divider_if_needed()
        st.markdown(f"**{zone['title']}**")
        if zone.get("detail"):
            st.markdown(zone["detail"])
        for link in zone.get("links", []):
            if link.get("url"):
                st.markdown(f"- [{link.get('label', 'link')}]({link['url']})")

    if not events_df.empty:
        for group_name in ["Beeple x Tibbir", "Konami", "Other / Misc"]:
            group = events_df[events_df["group"] == group_name].sort_values(["sort_ts", "title"])
            if group.empty:
                continue

            divider_if_needed()
            st.markdown(f"**{group_name}**")

            if group_name == "Konami":
                for _, event in group.iterrows():
                    for link in event.get("links", []):
                        if link.get("url"):
                            st.markdown(f"- [{link.get('label', 'link')}]({link['url']})")
                continue

            for _, event in group.iterrows():
                links = event.get("links", [])
                if isinstance(links, list) and len(links) == 1 and links[0].get("url"):
                    st.markdown(f"- [{event['title']}]({links[0]['url']})")
                else:
                    st.markdown(f"- {_price_event_link_text(event)}")


def _group_price_events_for_chart(visible_events, p_window):
    if not visible_events:
        return pd.DataFrame()

    events_df = pd.DataFrame(visible_events).sort_values(["sort_ts", "group", "title"])
    marker_groups = []
    rendered_major_groups = set()

    for _, event in events_df.iterrows():
        group_name = event["group"]
        is_major = event["tier"] == "major"
        if is_major:
            if group_name in rendered_major_groups:
                continue
            rendered_major_groups.add(group_name)
            group = events_df[events_df["group"] == group_name].sort_values(["sort_ts", "title"])
        else:
            group = pd.DataFrame([event])

        anchor = group.iloc[0]
        nearest_idx = (p_window["date"] - anchor["chart_date"]).abs().idxmin()
        event_price = p_window.loc[nearest_idx, "price_usd"]
        marker_groups.append({
            "date": anchor["chart_date"],
            "price_usd": event_price,
            "label": group_name if len(group) > 1 else anchor["title"],
            "count": len(group),
            "tier": "major" if is_major else anchor["tier"],
        })
    return pd.DataFrame(marker_groups)

if meta:
    def _fmt_ts(raw):
        try:
            return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return raw or "—"

    _lbl = "font-size:0.72em; color:rgba(250,250,250,0.45); text-transform:uppercase; letter-spacing:0.06em; margin:6px 0 1px"
    _val = "font-size:0.85em; color:rgba(250,250,250,0.8); margin:0"

    _end_block = meta.get("end_block")
    _end_block_str = f"{_end_block:,}" if _end_block is not None else "—"
    _holders = meta.get("wallet_snapshot_holder_count")
    _holders_10k = meta.get("holders_10k_plus")

    _supply      = meta.get("total_minted_supply")
    _burned_zero = meta.get("burned_supply", 0)
    _burned_dead = meta.get("dead_address_supply", 0)
    _is_dataset_details_page = st.session_state.get("page", "dashboard") == "dataset-details"

    def _render_contract_supply_details():
        c1, c2 = st.columns(2)
        c1.markdown(
            f'<p style="{_lbl}">Contract</p>'
            f'<p style="{_val}"><code>{config.CONTRACT_ADDRESS}</code> '
            f'<a href="{_BASESCAN}/token/{config.CONTRACT_ADDRESS}" target="_blank" style="color:#6366f1">↗</a></p>',
            unsafe_allow_html=True,
        )
        c2.markdown(f'<p style="{_lbl}">Total initial supply</p><p style="{_val}">{f"{_supply:,.0f}" if _supply is not None else "—"}</p>', unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        c1.markdown(
            f'<p style="{_lbl}">Burn address</p>'
            f'<p style="{_val}"><code>{_ZERO_ADDR}</code> '
            f'<a href="{_BASESCAN}/token/{config.CONTRACT_ADDRESS}?a={_ZERO_ADDR}" target="_blank" style="color:#6366f1">↗</a></p>',
            unsafe_allow_html=True,
        )
        c2.markdown(f'<p style="{_lbl}">Initial supply − burns</p><p style="{_val}">{f"{_supply - _burned_zero:,.0f}" if _supply is not None else "—"}</p>', unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        c1.markdown(
            f'<p style="{_lbl}">Dead address</p>'
            f'<p style="{_val}"><code>{_DEAD_ADDR}</code> '
            f'<a href="{_BASESCAN}/token/{config.CONTRACT_ADDRESS}?a={_DEAD_ADDR}" target="_blank" style="color:#6366f1">↗</a></p>',
            unsafe_allow_html=True,
        )
        c2.markdown(f'<p style="{_lbl}">Initial supply − (burns + dead)</p><p style="{_val}">{f"{_supply - _burned_zero - _burned_dead:,.0f}" if _supply is not None else "—"}</p>', unsafe_allow_html=True)

    def _render_dataset_details_page():
        if st.button("Back to dashboard", key="back_to_dashboard", type="tertiary"):
            st.session_state["page"] = "dashboard"
            st.rerun()

        st.subheader("Contract & Supply")
        _render_contract_supply_details()

        st.divider()
        st.subheader("Transaction data")
        st.markdown(
            f"""
            - Data covers Tibbir transactions on Base (via Alchemy) up to the latest safe block at the time of the last run (-{config.REORG_BUFFER} blocks for reorg safety).
            - Wallet balances, metrics and charts are derived from the full transaction history.
            """
        )
        with st.expander("Public dataset"):
            st.markdown(
                f"""
                The full transaction dataset is published to a public Google Storage bucket.

                - [Metadata]({config.PUBLIC_BASE_URL}/metadata.json): dataset stats and file listing.
                - [Schema]({config.PUBLIC_BASE_URL}/schema.json): column definitions, dtypes, examples, and Python quickstart.
                - [Sample transactions]({config.PUBLIC_BASE_URL}/sample_transfers.parquet): first 1,000 rows for quick inspection.
                - [Full transaction history]({config.PUBLIC_BASE_URL}/transfers_master.parquet): complete Parquet dataset.

                ```python
                import requests
                import pandas as pd

                base = "{config.PUBLIC_BASE_URL}"
                metadata = requests.get(f"{{base}}/metadata.json").json()
                schema = requests.get(f"{{base}}/schema.json").json()
                sample = pd.read_parquet(f"{{base}}/sample_transfers.parquet")
                transactions = pd.read_parquet(f"{{base}}/transfers_master.parquet")
                ```
                """
            )

        render_raw_data()

        st.divider()
        st.subheader("Price data")
        st.markdown(
            """
            - **Jan 12-Mar 24, 2025:** UTC end-of-day DEX reserve-derived close proxy from the TIBBIR/VIRTUAL pool.
            - **Mar 25, 2025 onward:** Alchemy daily token prices.
            """
        )
        with st.expander("Inspect raw price data"):
            try:
                prices = load_price_history_csv()
                st.dataframe(prices, hide_index=True, use_container_width=True, height=420)
            except Exception as e:
                st.warning(f"Could not load local price CSV: {e}")

    if not _is_dataset_details_page:
        c1, c2 = st.columns(2)
        c1.metric("Last updated", _fmt_ts(meta.get("last_updated_utc", "")))
        c2.metric("Latest block", _end_block_str)

        st.markdown(
            """
            - Transaction data updates hourly
            - Price data uses daily price points
            """
        )

        if st.button("Read more details about data coverage", key="open_dataset_details", type="tertiary"):
            st.session_state["page"] = "dataset-details"
            st.rerun()

# --- cached loaders (defined once, used across sections) ---

@st.cache_data
def load_wallet_snapshot():
    return _read_parquet(config.WALLET_SNAPSHOT_FILE)

@st.cache_data
def load_transfers_sample():
    df = _read_parquet(config.RECENT_TRANSFERS_FILE)
    df["amount"] = df["raw_amount"].apply(int) / (10 ** df["decimals"])
    priority = ["timestamp", "block_number", "event_id"]
    rest = [c for c in df.columns if c not in priority]
    return df[priority + rest].sort_values("timestamp", ascending=False).reset_index(drop=True)

@st.cache_data
def load_holder_growth():
    return _read_parquet(config.DAILY_HOLDER_GROWTH_FILE)

@st.cache_data
def load_bucket_breakdown():
    return _read_parquet(config.DAILY_BUCKET_BREAKDOWN_FILE)

@st.cache_data
def load_price_history():
    return _read_parquet(config.PRICE_HISTORY_FILE)

@st.cache_data
def load_price_history_csv():
    df = pd.read_csv(PRICE_HISTORY_CSV_FILE)
    return df.sort_values("date").reset_index(drop=True)

@st.cache_data
def load_soulbound_holder_supply():
    return _read_parquet(config.SOULBOUND_HOLDER_SUPPLY_FILE)

@st.cache_data
def load_soulbound_wallets():
    holders = pd.read_csv(Path(__file__).parent / config.SOULBOUND_NFT_HOLDERS_CSV)
    holders["address"] = holders["HolderAddress"].astype(str).str.lower()
    holders = holders.rename(columns={"Quantity": "nft_quantity", "PendingBalanceUpdate": "pending_balance_update"})

    snapshot = load_wallet_snapshot().copy()
    address_col = "address" if "address" in snapshot.columns else "wallet_address"
    snapshot[address_col] = snapshot[address_col].astype(str).str.lower()
    balance_cols = [address_col, "balance"]
    wallet_rows = holders.merge(snapshot[balance_cols], left_on="address", right_on=address_col, how="left")
    wallet_rows["balance"] = wallet_rows["balance"].fillna(0.0)
    return wallet_rows[["address", "nft_quantity", "pending_balance_update", "balance"]]

@st.cache_data
def load_chad_cohorts():
    return _read_parquet(config.CHAD_COHORTS_FILE)

@st.cache_data
def load_chad_wallets():
    return _read_parquet(config.CHAD_WALLETS_FILE)

COIN_AGE_EXAMPLE_WALLET = "0xffb3f0b6817036985f49c311a2f7d597bcb02910"
COIN_AGE_EXAMPLE_AS_OF = pd.Timestamp("2026-05-25T00:00:00Z")
COIN_AGE_EXAMPLE_FILE = Path(__file__).parent / "examples" / "coin_age_example_wallet_events.csv"


@st.cache_data
def load_coin_age_example_events():
    events = pd.read_csv(COIN_AGE_EXAMPLE_FILE)
    events["address"] = events["address"].astype(str).str.lower()
    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True)
    events["log_index"] = events["event_id"].str.rsplit(":", n=1).str[-1].astype(int)
    return events.sort_values(["block_number", "log_index"]).reset_index(drop=True)


def build_coin_age_example_rows(events, as_of=None):
    if events.empty:
        return pd.DataFrame(), {"balance": 0.0, "age_mass": 0.0, "avg_age": 0.0}

    as_of = as_of or pd.Timestamp.now(tz=timezone.utc)
    balance = 0.0
    age_mass = 0.0
    current = events["timestamp"].iloc[0]
    rows = []

    for _, row in events.iterrows():
        ts = row["timestamp"]
        elapsed_days = max((ts - current).total_seconds() / 86400, 0.0)
        age_mass += balance * elapsed_days

        balance_before = balance
        age_mass_before = age_mass
        amount = float(row["amount"])
        direction = row["direction"]
        if direction == "in":
            balance += amount
        else:
            sold_fraction = min(amount / balance, 1.0) if balance > 0 else 0.0
            age_mass *= (1.0 - sold_fraction)
            balance = max(balance - amount, 0.0)

        rows.append({
            "timestamp": ts,
            "direction": direction,
            "amount": amount,
            "days_since_previous": elapsed_days,
            "balance_before": balance_before,
            "avg_age_before": age_mass_before / balance_before if balance_before > 0 else 0.0,
            "balance_after": balance,
            "avg_age_after": age_mass / balance if balance > 0 else 0.0,
        })
        current = ts

    elapsed_days = max((as_of - current).total_seconds() / 86400, 0.0)
    age_mass += balance * elapsed_days

    final = {
        "balance": balance,
        "age_mass": age_mass,
        "avg_age": age_mass / balance if balance > 0 else 0.0,
        "days_since_last_event": elapsed_days,
        "as_of": as_of,
    }
    return pd.DataFrame(rows), final


def _coin_age_example_chad_metrics(events, rows, final):
    total_bought = float(events.loc[events["direction"] == "in", "amount"].sum())
    total_sold = float(events.loc[events["direction"] == "out", "amount"].sum())
    peak_balance = float(rows["balance_after"].max()) if not rows.empty else 0.0
    current_balance = float(final["balance"])
    return {
        "current_balance": current_balance,
        "peak_balance": peak_balance,
        "pct_of_peak": current_balance / peak_balance if peak_balance > 0 else 0.0,
        "total_bought": total_bought,
        "total_sold": total_sold,
        "sold_bought": total_sold / total_bought if total_bought > 0 else 0.0,
        "avg_coin_age": float(final["avg_age"]),
        "age_mass": float(final["age_mass"]),
    }


def render_coin_age_example_page():
    st.subheader("Example - Chad metrics")
    st.markdown(
        f"[{COIN_AGE_EXAMPLE_WALLET}]({_BASESCAN}/token/{config.CONTRACT_ADDRESS}?a={COIN_AGE_EXAMPLE_WALLET}#transactions)"
    )
    st.markdown(
        f"""
        This worked example is **time-frozen at {COIN_AGE_EXAMPLE_AS_OF.strftime('%Y-%m-%d %H:%M UTC')}**
        so the numbers remain the same.
        """
    )

    try:
        events = load_coin_age_example_events()
        rows, final = build_coin_age_example_rows(events, as_of=COIN_AGE_EXAMPLE_AS_OF)
        if events.empty:
            st.warning("No wallet events found for this address.")
            return

        metrics = _coin_age_example_chad_metrics(events, rows, final)

        st.markdown("**1. Inclusion criterias**")
        c1, c2, c3 = st.columns(3)
        c1.metric("Current balance", f"{metrics['current_balance']:,.0f}")
        c2.metric("Peak balance", f"{metrics['peak_balance']:,.0f}")
        c3.metric("% of peak", f"{metrics['pct_of_peak']:.1%}")

        c1, c2, c3 = st.columns(3)
        c1.metric("Total bought", f"{metrics['total_bought']:,.0f}")
        c2.metric("Total sold", f"{metrics['total_sold']:,.0f}")
        c3.metric("Sold / bought", f"{metrics['sold_bought']:.1%}")

        st.markdown(
            f"""
            - Current holdings are at least 90% of peak holdings: ✓
            - Total sold / total bought is less than 20%: ✓
            - **Current balance** is what the wallet still holds at the frozen timestamp.
            - **Peak balance** is the highest balance this wallet reached in the frozen event history.
            - **% of peak** is `current balance / peak balance`: `{metrics['current_balance']:,.0f} / {metrics['peak_balance']:,.0f} = {metrics['pct_of_peak']:.1%}`.
            - **Sold / bought** is `total sold / total bought`: `{metrics['total_sold']:,.0f} / {metrics['total_bought']:,.0f} = {metrics['sold_bought']:.1%}`.
            """
        )

        st.markdown("**2. Coin age metrics**")
        c1, c2, c3 = st.columns(3)
        c1.metric("Age mass", f"{metrics['age_mass']:,.0f}")
        c2.metric("Current balance", f"{metrics['current_balance']:,.0f}")
        c3.metric("Avg coin age", f"{metrics['avg_coin_age']:,.0f} days")

        st.markdown(
            f"""
            - **Age mass** is token-days: `sum(token amount x days held)`.
            - **Avg coin age** is `age mass / current balance`: `{metrics['age_mass']:,.0f} / {metrics['current_balance']:,.0f} = {metrics['avg_coin_age']:,.1f} days`.
            - A **buy / receive** adds fresh tokens at age `0`.
            - A **sell / send** removes the same fraction of age mass as the fraction of balance sold.
            """
        )

        display = rows.copy()
        display["Date"] = display["timestamp"].dt.strftime("%Y-%m-%d")
        display["Type"] = display["direction"]
        for col in ["amount", "balance_before", "balance_after"]:
            display[col] = display[col].map(lambda v: f"{v:,.0f}")
        for col in ["days_since_previous", "avg_age_before", "avg_age_after"]:
            display[col] = display[col].map(lambda v: f"{v:,.1f}")

        st.markdown("**3. Event-by-event replay**")
        st.dataframe(
            display[[
                "Date",
                "Type",
                "amount",
                "days_since_previous",
                "balance_before",
                "avg_age_before",
                "balance_after",
                "avg_age_after",
            ]].rename(columns={
                "amount": "Amount",
                "days_since_previous": "Days",
                "balance_before": "Bal. before",
                "avg_age_before": "Age before",
                "balance_after": "Bal. after",
                "avg_age_after": "Age after",
            }),
            hide_index=True,
            use_container_width=True,
            height=520,
            column_config={
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Type": st.column_config.TextColumn("Type", width="small"),
                "Amount": st.column_config.TextColumn("Amount", width="small"),
                "Days": st.column_config.TextColumn("Days", width="small"),
                "Bal. before": st.column_config.TextColumn("Bal. before", width="small"),
                "Age before": st.column_config.TextColumn("Age before", width="small"),
                "Bal. after": st.column_config.TextColumn("Bal. after", width="small"),
                "Age after": st.column_config.TextColumn("Age after", width="small"),
            },
        )
    except Exception as e:
        st.warning(f"Could not build coin age example: {e}")


if st.query_params.get("page") == "coin-age-example":
    render_coin_age_example_page()
    st.stop()


def render_raw_data():
    with st.expander("Verify wallet balances and latest transactions"):
        c1, c2 = st.columns(2)
        c1.metric("Last updated", _fmt_ts(meta.get("last_updated_utc", "")))
        c2.metric("Latest block", _end_block_str)

        tab_snap, tab_transfers = st.tabs(["Wallet balances", "Latest transactions"])

        with tab_snap:
            try:
                snap = load_wallet_snapshot().copy()
                address_col = "address" if "address" in snap.columns else "wallet_address"
                snap[address_col] = snap[address_col].astype(str).str.lower()

                query = st.text_input("Search wallet", key="snapshot_wallet_search", placeholder="0x...")
                if query:
                    snap = snap[snap[address_col].str.contains(query.strip().lower(), case=False, na=False)]

                snap = snap.sort_values("balance", ascending=False).reset_index(drop=True)
                snap["Wallet"] = snap[address_col].str.slice(0, 6) + "..." + snap[address_col].str.slice(-4)
                snap["BaseScan"] = snap[address_col].map(
                    lambda address: f"{_BASESCAN}/token/{config.CONTRACT_ADDRESS}?a={address}#transactions"
                )
                snap["TIBBIR held"] = snap["balance"].map(lambda v: f"{v:,.0f}")
                st.dataframe(
                    snap[["Wallet", "BaseScan", "TIBBIR held"]],
                    hide_index=True,
                    use_container_width=True,
                    height=420,
                    column_config={
                        "Wallet": st.column_config.TextColumn("Wallet", width="small"),
                        "BaseScan": st.column_config.LinkColumn("BaseScan", display_text="open", width="small"),
                        "TIBBIR held": st.column_config.TextColumn("TIBBIR held", width="small"),
                    },
                )
            except Exception as e:
                st.warning(f"Could not load wallet snapshot: {e}")

        with tab_transfers:
            try:
                transfers = load_transfers_sample()
                st.dataframe(transfers, use_container_width=True)
            except Exception as e:
                st.warning(f"Could not load transfers: {e}")

if st.session_state.get("page", "dashboard") == "dataset-details":
    _render_dataset_details_page()
    st.stop()

st.divider()

# --- Price history ---
st.subheader("Price, key events & bonus lore")

try:
    pdf = load_price_history()
    pdf["date"] = pd.to_datetime(pdf["date"])
    pdf = pdf.sort_values("date")

    price_context = st.radio("Price context", ["Off", "Key events", "Bonus lore"], index=1, horizontal=True, key="price_context")
    p_window = pdf.sort_values("date")
    launch_anchor_date = pd.Timestamp("2025-01-11")
    if not p_window.empty and p_window["date"].min() > launch_anchor_date:
        p_window = pd.concat(
            [
                pd.DataFrame([{"date": launch_anchor_date, "price_usd": 0.0}]),
                p_window,
            ],
            ignore_index=True,
        ).sort_values("date")

    latest_price = p_window.iloc[-1]["price_usd"] if not p_window.empty else None
    if latest_price is not None:
        st.metric(
            "Latest daily price",
            f"${latest_price:,.6f}",
            help=(
                "Daily USD price:\n\n"
                "- Jan 12-Mar 24, 2025: UTC end-of-day DEX reserve-derived "
                "close proxy from the TIBBIR/VIRTUAL pool.\n"
                "- Mar 25, 2025 onward: Alchemy daily token prices."
            ),
        )

    fig_price = go.Figure()
    fig_price.add_trace(go.Scatter(
        x=p_window["date"],
        y=p_window["price_usd"],
        name="Price",
        mode="lines",
        line=dict(width=2, color="#22d3ee"),
        hovertemplate="%{x|%b %d, %Y}<br>$%{y:.6f}<extra>TIBBIR</extra>",
    ))

    visible_price_events = _visible_price_events(PRICE_EVENTS, p_window, price_context)
    if price_context != "Off" and not p_window.empty:
        if price_context == "Bonus lore":
            for zone in PRICE_ZONES:
                zone_start = pd.to_datetime(zone["start"])
                zone_end = pd.to_datetime(zone["end"])
                if zone_end < p_window["date"].min() or zone_start > p_window["date"].max():
                    continue

                visible_start = max(zone_start, p_window["date"].min())
                visible_end = min(zone_end, p_window["date"].max())
                fig_price.add_vrect(
                    x0=visible_start,
                    x1=visible_end,
                    fillcolor="rgba(251,191,36,0.10)",
                    line_width=0,
                    layer="below",
                    annotation_text=zone["title"],
                    annotation_position="top left",
                    annotation_font=dict(size=11, color="#fbbf24"),
                )

        grouped_df = _group_price_events_for_chart(visible_price_events, p_window) if price_context == "Key events" else pd.DataFrame()
        if not grouped_df.empty:
            for _, marker in grouped_df.iterrows():
                fig_price.add_vline(
                    x=marker["date"],
                    line_width=1,
                    line_dash="dot",
                    line_color="rgba(250,250,250,0.22)" if marker["tier"] == "major" else "rgba(148,163,184,0.16)",
                    layer="below",
                )
            for tier, name, color, size in [
                ("major", "Major events", "#34d399", 20),
                ("noteworthy", "Other", "#fbbf24", 15),
            ]:
                tier_df = grouped_df[grouped_df["tier"] == tier]
                if tier_df.empty:
                    continue
                fig_price.add_trace(go.Scatter(
                    x=tier_df["date"],
                    y=tier_df["price_usd"],
                    name=name,
                    mode="markers",
                    marker=dict(
                        size=size,
                        color=color,
                        line=dict(width=1, color="#111827"),
                    ),
                    text=tier_df["label"],
                    hovertemplate=(
                        "%{x|%b %d, %Y}<br><b>%{text}</b>"
                        "<extra></extra>"
                    ),
                ))

    fig_price.update_layout(
        yaxis=dict(title=None, tickprefix="$", tickformat=".2f"),
        xaxis=_date_xaxis(),
        hovermode="closest",
        hoverdistance=30,
        spikedistance=30,
        legend=_bottom_legend(),
        margin=dict(t=16, b=90, l=0, r=0),
        height=CHART_HEIGHT,
    )
    st.plotly_chart(_make_chart_scroll_safe(fig_price), use_container_width=True, config=PLOTLY_CONFIG)
    st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)
    if price_context != "Off":
        visible_zones = [
            zone
            for zone in PRICE_ZONES
            if price_context == "Bonus lore"
            if not p_window.empty
            and pd.to_datetime(zone["end"]) >= p_window["date"].min()
            and pd.to_datetime(zone["start"]) <= p_window["date"].max()
        ]
        if visible_zones or visible_price_events:
            with st.expander("Price context details", expanded=False):
                if price_context == "Bonus lore":
                    _render_lore_price_context(visible_zones, visible_price_events)
                elif visible_price_events:
                        _render_key_price_timeline(visible_price_events)
except Exception as e:
    st.warning(f"Could not load price history: {e}")

st.markdown(
    """
    <div style="margin:1.15rem 0 0.35rem">
      <div style="font-size:0.95rem; font-weight:700; margin-bottom:0.55rem">Explore more</div>
      <div style="display:flex; flex-wrap:wrap; gap:0.6rem">
        <a href="#jump-chad-wallets" style="padding:0.42rem 0.7rem; border:1px solid rgba(250,250,250,0.16); border-radius:6px; text-decoration:none">Chad wallets</a>
        <a href="#jump-soulbound-wallets" style="padding:0.42rem 0.7rem; border:1px solid rgba(250,250,250,0.16); border-radius:6px; text-decoration:none">Soulbound wallets</a>
        <a href="#jump-current-wallet-count" style="padding:0.42rem 0.7rem; border:1px solid rgba(250,250,250,0.16); border-radius:6px; text-decoration:none">Current wallet count</a>
        <a href="#jump-holder-growth" style="padding:0.42rem 0.7rem; border:1px solid rgba(250,250,250,0.16); border-radius:6px; text-decoration:none">Wallet count history</a>
        <a href="#jump-current-holder-distribution" style="padding:0.42rem 0.7rem; border:1px solid rgba(250,250,250,0.16); border-radius:6px; text-decoration:none">Current holder distribution</a>
        <a href="#jump-holder-distribution-history" style="padding:0.42rem 0.7rem; border:1px solid rgba(250,250,250,0.16); border-radius:6px; text-decoration:none">Holder distribution history</a>
        <a href="#jump-wallets-vs-supply" style="padding:0.42rem 0.7rem; border:1px solid rgba(250,250,250,0.16); border-radius:6px; text-decoration:none">Wallets vs supply</a>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

# --- Chad cohorts ---
st.markdown('<div id="jump-chad-wallets" style="scroll-margin-top:5rem"></div>', unsafe_allow_html=True)
st.subheader("Chad wallets")

try:
    cdf = load_chad_cohorts()
    cdf["date"] = pd.to_datetime(cdf["date"])
    cohort_order = ["10k-100k", "100k-1M", "1M+"]
    cdf["cohort"] = pd.Categorical(cdf["cohort"], categories=cohort_order, ordered=True)
    cdf = cdf.sort_values(["date", "cohort"])
    latest_chads = cdf.sort_values("date").groupby("cohort", observed=False).tail(1)

    total_chads = int(latest_chads["wallet_count"].sum())
    total_chad_balance = float(latest_chads["total_balance"].sum())
    weighted_age = (
        float((latest_chads["avg_coin_age_days"] * latest_chads["total_balance"]).sum() / total_chad_balance)
        if total_chad_balance > 0
        else 0.0
    )
    latest_chad_date = latest_chads["date"].max()
    avg_coin_age_date = latest_chad_date - pd.Timedelta(days=weighted_age)

    st.markdown(
        """
        <div style="font-size:1rem; color:rgba(250,250,250,0.78); line-height:1.55; margin:0.35rem 0 1rem">
          <strong>Inclusion criteria for wallets</strong><br>
          - current holdings are at least 90% of peak holdings<br>
          - total sold / total bought is less than 20%
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Chad wallets", f"{total_chads:,}")
    c2.metric("TIBBIR held", f"{total_chad_balance:,.0f}")
    c3.metric("Avg coin age", f"{weighted_age:,.0f} days")

    cohort_summary = latest_chads.copy()
    cohort_summary["cohort"] = pd.Categorical(cohort_summary["cohort"], categories=cohort_order, ordered=True)
    cohort_summary = cohort_summary.sort_values("cohort")
    cohort_summary["TIBBIR held"] = cohort_summary["total_balance"].map(lambda v: f"{v:,.0f}")
    cohort_summary["Wallets"] = cohort_summary["wallet_count"].map(lambda v: f"{int(v):,}")
    cohort_summary["Avg coin age"] = cohort_summary["avg_coin_age_days"].map(lambda v: f"{v:,.0f} days")
    cohort_summary["% of peak"] = cohort_summary["avg_retention_ratio"].map(lambda v: f"{v:.1%}")
    cohort_summary["Sold / bought"] = cohort_summary["avg_turnover_ratio"].map(lambda v: f"{v:.1%}")

    chad_window = cdf.sort_values(["date", "cohort"])

    fig_chads = go.Figure()
    chad_colors = ["#34d399", "#22d3ee", "#6366f1"]
    for label, color in zip(cohort_order, chad_colors):
        cohort = chad_window[chad_window["cohort"] == label]
        fig_chads.add_trace(go.Scatter(
            x=cohort["date"],
            y=cohort["balance"],
            name=label,
            stackgroup="one",
            line=dict(width=0.5, color=color),
            fillcolor=color,
            hovertemplate="%{y:,.0f} TIBBIR<extra>" + label + "</extra>",
        ))
    if pd.notna(avg_coin_age_date) and avg_coin_age_date >= chad_window["date"].min():
        fig_chads.add_shape(
            type="line",
            x0=avg_coin_age_date,
            x1=avg_coin_age_date,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line_width=1.5,
            line_dash="dot",
            line_color="rgba(251,191,36,0.9)",
        )
        fig_chads.add_annotation(
            x=avg_coin_age_date,
            y=1,
            xref="x",
            yref="paper",
            text=f"Avg coin age date ({weighted_age:,.0f}d)",
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font=dict(size=11, color="#fbbf24"),
        )
    fig_chads.update_layout(
        yaxis=dict(title=None),
        xaxis=_date_xaxis(),
        hovermode="x unified",
        legend=_bottom_legend(),
        margin=dict(t=28, b=90, l=0, r=0),
        height=CHART_HEIGHT,
    )
    st.plotly_chart(_make_chart_scroll_safe(fig_chads), use_container_width=True, config=PLOTLY_CONFIG)
    st.caption("Historical holdings are grouped by each wallet's current cohort.")
    st.dataframe(
        cohort_summary[["cohort", "Wallets", "TIBBIR held", "Avg coin age", "% of peak", "Sold / bought"]]
        .rename(columns={"cohort": "Cohort"}),
        hide_index=True,
        use_container_width=True,
    )

    with st.expander("Example and wallet verification"):
        st.markdown(
            '<a href="?page=coin-age-example" target="_blank">Example - Chad metrics</a>',
            unsafe_allow_html=True,
        )
        try:
            wallets = load_chad_wallets()
            wallets["cohort"] = pd.Categorical(wallets["cohort"], categories=cohort_order, ordered=True)
            wallets = wallets.sort_values(["cohort", "current_balance"], ascending=[True, False])

            st.markdown("**Wallets**")
            tabs = st.tabs(cohort_order)
            for tab, label in zip(tabs, cohort_order):
                with tab:
                    cohort_wallets = wallets[wallets["cohort"] == label].copy()
                    query = st.text_input("Search wallet", key=f"chad_wallet_search_{label}", placeholder="0x...")
                    if query:
                        cohort_wallets = cohort_wallets[
                            cohort_wallets["wallet_address"].str.contains(query.strip().lower(), case=False, na=False)
                        ]

                    cohort_wallets["Wallet"] = cohort_wallets["wallet_address"].str.slice(0, 6) + "..." + cohort_wallets["wallet_address"].str.slice(-4)
                    cohort_wallets["Current"] = cohort_wallets["current_balance"].map(lambda v: f"{v:,.0f}")
                    cohort_wallets["Peak"] = cohort_wallets["peak_balance"].map(lambda v: f"{v:,.0f}")
                    cohort_wallets["% of peak"] = cohort_wallets["retention_ratio"].map(lambda v: f"{v:.1%}")
                    cohort_wallets["Sold / bought"] = cohort_wallets["turnover_ratio"].map(lambda v: f"{v:.1%}")
                    cohort_wallets["Age"] = cohort_wallets["avg_coin_age_days"].fillna(0).map(lambda v: f"{v:,.0f}d")
                    table = cohort_wallets[[
                        "Wallet",
                        "basescan_url",
                        "Current",
                        "Peak",
                        "% of peak",
                        "Sold / bought",
                        "Age",
                    ]].rename(columns={"basescan_url": "BaseScan"})
                    st.dataframe(
                        table,
                        hide_index=True,
                        use_container_width=True,
                        height=420,
                        column_config={
                            "BaseScan": st.column_config.LinkColumn("BaseScan", display_text="open"),
                            "Wallet": st.column_config.TextColumn("Wallet", width="small"),
                        },
                    )
        except Exception as e:
            st.info(f"Wallet verification table will appear after the chad wallet file is rebuilt: {e}")

except Exception as e:
    st.warning(f"Could not load chad cohorts: {e}")

st.divider()

# --- Soulbound NFT holder supply ---
st.markdown('<div id="jump-soulbound-wallets" style="scroll-margin-top:5rem"></div>', unsafe_allow_html=True)
st.subheader("Soulbound wallets")

try:
    sdf = load_soulbound_holder_supply()
    sdf["date"] = pd.to_datetime(sdf["date"])
    sdf = sdf.sort_values("date")

    s_window = sdf.sort_values("date")

    latest_soulbound = sdf.iloc[-1]
    c1, c2, c3 = st.columns(3)
    c1.metric("TIBBIR held", f"{latest_soulbound['total_balance']:,.0f}")
    c2.metric("Share of supply", f"{latest_soulbound['pct_total_supply']:.2f}%")
    c3.metric("TIBBIR holders", f"{int(latest_soulbound['holder_count']):,} / {int(latest_soulbound['soulbound_address_count']):,}")

    fig_soulbound = go.Figure()
    fig_soulbound.add_trace(go.Scatter(
        x=s_window["date"],
        y=s_window["total_balance"],
        customdata=s_window[["pct_total_supply"]],
        name="Soulbound wallets",
        mode="lines",
        line=dict(width=2, color="#34d399"),
        fill="tozeroy",
        fillcolor="rgba(52,211,153,0.28)",
        hovertemplate="%{x|%b %d, %Y}<br>%{customdata[0]:.2f}% of supply<extra>Soulbound wallets</extra>",
    ))

    fig_soulbound.update_layout(
        yaxis=dict(title=None),
        xaxis=_date_xaxis(),
        hovermode="x unified",
        showlegend=False,
        margin=dict(t=16, b=56, l=0, r=0),
        height=CHART_HEIGHT,
    )
    st.plotly_chart(_make_chart_scroll_safe(fig_soulbound), use_container_width=True, config=PLOTLY_CONFIG)
    st.caption("Current TIBBIR held by addresses with a soulbound NFT.")

    with st.expander("Wallet verification"):
        try:
            soulbound_wallets = load_soulbound_wallets().sort_values("balance", ascending=False)
            st.markdown("[View all soulbound NFT holders on BaseScan](https://basescan.org/token/0xcabce1fa75aca96b40cc98dd3ab38ba332d9e488)")
            query = st.text_input("Search wallet", key="soulbound_wallet_search", placeholder="0x...")
            if query:
                soulbound_wallets = soulbound_wallets[
                    soulbound_wallets["address"].str.contains(query.strip().lower(), case=False, na=False)
                ]

            soulbound_wallets["Wallet"] = soulbound_wallets["address"].str.slice(0, 6) + "..." + soulbound_wallets["address"].str.slice(-4)
            soulbound_wallets["BaseScan"] = soulbound_wallets["address"].map(
                lambda address: f"https://basescan.org/token/{config.CONTRACT_ADDRESS}?a={address}#transactions"
            )
            soulbound_wallets["TIBBIR held"] = soulbound_wallets["balance"].map(lambda v: f"{v:,.0f}")
            soulbound_wallets["Soulbound NFTs"] = soulbound_wallets["nft_quantity"].map(lambda v: f"{int(v):,}")

            st.dataframe(
                soulbound_wallets[["Wallet", "BaseScan", "TIBBIR held", "Soulbound NFTs"]],
                hide_index=True,
                use_container_width=True,
                height=420,
                column_config={
                    "Wallet": st.column_config.TextColumn("Wallet", width="small"),
                    "BaseScan": st.column_config.LinkColumn("BaseScan", display_text="open", width="small"),
                    "TIBBIR held": st.column_config.TextColumn("TIBBIR held", width="small"),
                    "Soulbound NFTs": st.column_config.TextColumn("Soulbound NFTs", width="small"),
                },
            )
        except Exception as e:
            st.info(f"Soulbound wallet verification will appear after wallet data loads: {e}")

except Exception as e:
    st.warning(f"Could not load soulbound NFT holder supply: {e}")

st.divider()

BUCKETS = [
    ("pct_1m_plus",    "count_1m_plus",    "1M+"),
    ("pct_100k_1m",    "count_100k_1m",    "100k–1M"),
    ("pct_10k_100k",   "count_10k_100k",   "10k–100k"),
    ("pct_1k_10k",     "count_1k_10k",     "1k–10k"),
    ("pct_0_1k",       "count_0_1k",       "0–1k"),
]
BUCKET_COLORS = ["#6366f1", "#22d3ee", "#34d399", "#fbbf24", "#f87171"]

# --- Current wallet count ---
st.markdown('<div id="jump-current-wallet-count" style="scroll-margin-top:5rem"></div>', unsafe_allow_html=True)
st.subheader("Current wallet count per bucket")

try:
    bdf_counts = load_bucket_breakdown()
    bdf_counts["date"] = pd.to_datetime(bdf_counts["date"])
    latest_counts = bdf_counts.loc[bdf_counts["date"].idxmax()]
    total_wallet_count = int(sum(latest_counts[count_col] for _, count_col, _ in BUCKETS))

    st.markdown(
        f"""
        <div style="border:1px solid rgba(250,250,250,0.14); border-radius:8px; padding:0.9rem 1rem; margin:0.25rem 0 1rem">
          <div style="font-size:0.88rem; font-weight:700; color:rgba(250,250,250,0.82)">Wallet count</div>
          <div style="font-size:2rem; line-height:1.15; margin:0.1rem 0">{total_wallet_count:,}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    current_counts = pd.DataFrame([
        {"Bucket": label, "Wallets": int(latest_counts[count_col]), "Color": color}
        for (_, count_col, label), color in zip(BUCKETS, BUCKET_COLORS)
    ])
    fig_counts = go.Figure(go.Bar(
        x=current_counts["Bucket"],
        y=current_counts["Wallets"],
        marker=dict(color=current_counts["Color"]),
        text=current_counts["Wallets"].map(lambda v: f"{v:,}"),
        textposition="outside",
        textfont=dict(color="#f8fafc", size=12),
        hovertemplate="%{x}<br>%{y:,} wallets<extra></extra>",
    ))
    fig_counts.update_layout(
        xaxis=dict(title=None),
        yaxis=dict(title=None, showgrid=True),
        margin=dict(t=16, b=20, l=0, r=0),
        height=320,
        showlegend=False,
    )
    st.plotly_chart(_make_chart_scroll_safe(fig_counts), use_container_width=True, config=PLOTLY_CONFIG)
    st.caption("Addresses with a current TIBBIR balance, grouped by wallet size.")

except Exception as e:
    st.warning(f"Could not load current wallet counts: {e}")

st.divider()

# --- Holder growth ---
st.markdown('<div id="jump-holder-growth" style="scroll-margin-top:5rem"></div>', unsafe_allow_html=True)
st.subheader("Wallet count (with history)")

GROWTH_BUCKETS = [
    ("count_1m_plus",    "1M+"),
    ("count_100k_1m",    "100k–1M"),
    ("count_10k_100k",   "10k–100k"),
    ("count_1k_10k",     "1k–10k"),
    ("count_0_1k",       "0–1k"),
]
GROWTH_COLORS = ["#6366f1", "#22d3ee", "#34d399", "#fbbf24", "#f87171"]

try:
    gdf = load_holder_growth()
    gdf["date"] = pd.to_datetime(gdf["date"])

    _all_bucket_labels = [label for _, label in GROWTH_BUCKETS]
    b_col1, b_col2 = st.columns([1, 4])
    with b_col1:
        select_all = st.toggle("All", value=True, key="growth_select_all")
    with b_col2:
        selected_buckets = st.multiselect(
            "Buckets",
            options=_all_bucket_labels,
            default=_all_bucket_labels if select_all else [],
            disabled=select_all,
            label_visibility="collapsed",
            key="growth_buckets",
        )
    if select_all:
        selected_buckets = _all_bucket_labels

    g_window = gdf.sort_values("date")

    fig2 = go.Figure()
    for (col, label), color in zip(GROWTH_BUCKETS, GROWTH_COLORS):
        if label not in selected_buckets:
            continue
        fig2.add_trace(go.Scatter(
            x=g_window["date"],
            y=g_window[col],
            name=label,
            stackgroup="one",
            line=dict(width=0.5, color=color),
            fillcolor=color,
            hovertemplate="%{y:,}<extra>" + label + "</extra>",
        ))

    fig2.update_layout(
        yaxis=dict(title=None),
        xaxis=_date_xaxis(),
        hovermode="x unified",
        legend=_bottom_legend(),
        margin=dict(t=28, b=90, l=0, r=0),
        height=CHART_HEIGHT,
    )
    st.plotly_chart(_make_chart_scroll_safe(fig2), use_container_width=True, config=PLOTLY_CONFIG)

except Exception as e:
    st.warning(f"Could not load holder growth: {e}")

st.divider()

# --- Holder distribution ---
st.markdown('<div id="jump-current-holder-distribution" style="scroll-margin-top:5rem"></div>', unsafe_allow_html=True)
st.subheader("Current holder distribution")

try:
    bdf = load_bucket_breakdown()
    bdf["date"] = pd.to_datetime(bdf["date"])
    latest_distribution = bdf.loc[bdf["date"].idxmax()]

    current_distribution = pd.DataFrame([
        {"Bucket": label, "Supply": float(latest_distribution[pct_col]), "Color": color}
        for (pct_col, _, label), color in zip(BUCKETS, BUCKET_COLORS)
    ])
    fig_current_distribution = go.Figure(go.Bar(
        x=current_distribution["Bucket"],
        y=current_distribution["Supply"],
        marker=dict(color=current_distribution["Color"]),
        text=current_distribution["Supply"].map(lambda v: f"{v:.1f}%"),
        textposition="outside",
        textfont=dict(color="#f8fafc", size=12),
        hovertemplate="%{x}<br>%{y:.1f}% of supply<extra></extra>",
    ))
    fig_current_distribution.update_layout(
        xaxis=dict(title=None),
        yaxis=dict(title=None, range=[0, 100], ticksuffix="%"),
        margin=dict(t=16, b=20, l=0, r=0),
        height=320,
        showlegend=False,
    )
    st.plotly_chart(_make_chart_scroll_safe(fig_current_distribution), use_container_width=True, config=PLOTLY_CONFIG)
    st.caption("Share of current TIBBIR supply held by wallets in each balance bucket.")

    st.divider()
    st.markdown('<div id="jump-holder-distribution-history" style="scroll-margin-top:5rem"></div>', unsafe_allow_html=True)
    st.subheader("Holder distribution (with history)")

    window = bdf.sort_values("date")

    fig = go.Figure()
    for (pct_col, _, label), color in zip(BUCKETS, BUCKET_COLORS):
        fig.add_trace(go.Scatter(
            x=window["date"],
            y=window[pct_col],
            name=label,
            stackgroup="one",
            line=dict(width=0.5, color=color),
            fillcolor=color,
            hovertemplate="%{y:.1f}%<extra>" + label + "</extra>",
        ))

    fig.update_layout(
        yaxis=dict(title=None, range=[0, 100]),
        xaxis=_date_xaxis(),
        hovermode="x unified",
        legend=_bottom_legend(),
        margin=dict(t=28, b=90, l=0, r=0),
        height=CHART_HEIGHT,
    )
    st.plotly_chart(_make_chart_scroll_safe(fig), use_container_width=True, config=PLOTLY_CONFIG)

except Exception as e:
    st.warning(f"Could not load holder distribution: {e}")

st.divider()

# --- Wallets vs supply ---
st.markdown('<div id="jump-wallets-vs-supply" style="scroll-margin-top:5rem"></div>', unsafe_allow_html=True)
st.subheader("Wallets vs supply by bucket")

try:
    bdf_current_holders = load_bucket_breakdown()
    bdf_current_holders["date"] = pd.to_datetime(bdf_current_holders["date"])
    latest_current_holders = bdf_current_holders.loc[bdf_current_holders["date"].idxmax()]
    total_current_wallets = int(sum(latest_current_holders[count_col] for _, count_col, _ in BUCKETS))

    current_holders = pd.DataFrame([
        {
            "Bucket": label,
            "Wallets": int(latest_current_holders[count_col]),
            "% of wallets": (
                int(latest_current_holders[count_col]) / total_current_wallets * 100
                if total_current_wallets
                else 0
            ),
            "% of supply": float(latest_current_holders[pct_col]),
        }
        for pct_col, count_col, label in BUCKETS
    ])

    st.dataframe(
        current_holders,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Bucket": st.column_config.TextColumn("Bucket", width="small"),
            "Wallets": st.column_config.NumberColumn("Wallets", format="%d"),
            "% of wallets": st.column_config.ProgressColumn(
                "% of wallets",
                format="%.1f%%",
                min_value=0,
                max_value=100,
            ),
            "% of supply": st.column_config.ProgressColumn(
                "% of supply",
                format="%.1f%%",
                min_value=0,
                max_value=100,
            ),
        },
    )
    st.caption("Current wallet count and supply share shown side by side for each balance bucket.")

except Exception as e:
    st.warning(f"Could not load wallets vs supply by bucket: {e}")
