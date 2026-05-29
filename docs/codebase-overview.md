# Codebase Overview

## Architecture

Production pipeline: `engine/update.py` fetches ERC-20 transfers from Alchemy → writes Parquet files to GCS → `app.py` Streamlit dashboard reads them. Analytics logic lives in `analytics/snapshot.py` (pure, no I/O). Daily automation via GitHub Actions.

Price pipeline: `engine/update.py` fetches daily TIBBIR/USD points from the Alchemy Prices API by Base contract address, writes `tibbir_price_history.parquet` to GCS, and `app.py` renders a simple daily price chart.

Chad cohorts: `analytics/chads.py` selects current 10k+ holder cohorts from `wallet_events`, `wallet_summary`, `coin_age_snapshots`, `data/known_addresses.json`, and confirmed `data/wallet_labels.json` market-infrastructure labels, then replays those wallets into a historical holdings time series and emits wallet-level verification rows; `engine/update.py` writes `tibbir_chad_cohorts.parquet` and `tibbir_chad_wallets.parquet`; `app.py` renders the aggregate chart and top-wallet verification tables.

Sandbox (`sbx/`, gitignored): exploratory notebooks and scripts for research that hasn't been promoted to production yet.

Key files:
- `config.py` price path: `PRICE_HISTORY_FILE` for daily TIBBIR/USD points
- `config.py` — all paths, contract address, RPC URL, reorg buffer
- `engine/update.py` — ETL (fetch, validate, write), including coin age + wallet activity jobs
- `analytics/snapshot.py` — balance snapshots, bucketing, time-series
- `analytics/coin_age.py` — coin age state machine (`WalletState`, `build_weekly_snapshots`, `project_snapshots_forward`)
- `analytics/chads.py` - current chad cohort aggregation with current/peak, sold/bought, and coin-age metrics
- `app.py` — Streamlit dashboard
- `data/price_context_events.json` - editable price chart key-event and lore config
- `data/price_history.csv` - repo-local raw price history snapshot used by the dataset details inspection table
- `sbx/coin_age.py` — original sandbox coin age module (kept as sbx source of truth)
- `sbx/coin_age_pipeline.ipynb` — exploratory pipeline notebook
- `sbx/coin_age_verification.ipynb` — balance accounting checks
- `sbx/coin_age_viz.ipynb` — exploratory visualisation notebook (balance overview + coin age per week)

## Recent Changes

### 2026-05-26

- **Price context config**: moved price chart event/lore material into `data/price_context_events.json`, with editable `major`, `noteworthy`, and `lore` tiers plus grouped links for key arcs and lore sections such as launch sequence, CryptoPunk #9098, Ribbit rebrand, Ribbita.ai launch, No dates zone, Beeple x Tibbir, Konami, and Other / Misc.
- **Price chart context UI**: replaced the raw labels toggle with `Off`, `Key events`, and `Bonus lore` modes. Key events render as a chronological timeline, with dated major arcs shown as titled bullet groups and additional context shown as inline one-liners; major chart markers are larger, all context markers are yellow, dotted guide lines show event timing, and hovers avoid implying an exact event price. Bonus lore keeps the No dates zone on the chart but leaves the remaining lore as grouped details below. Event ordering uses `time_utc` when present, otherwise the event date.
- **Price source note**: moved the visible price-source caption into the `Latest daily price` metric help tooltip to reduce chart clutter.
- **Dashboard structure**: kept only dataset freshness and coverage note at the top of the main dashboard, moved contract/supply details plus raw wallet/recent-transfer inspection behind a read-more page, made Price the first substantive chart, and defaulted Price context to Key events.
- **Price event chart styling**: split key-event markers into separate legend traces for green Major events and yellow Other key events while keeping the details expander unchanged.
- **Price date control**: previously replaced preset price range buttons with an exact date range filter before removing chart time filters entirely.
- **Chart time filters**: removed date/range time controls from all dashboard charts so each chart shows the full available history by default; non-time controls such as Price context and holder-growth bucket selection remain.
- **Dataset details page**: split details into Contract & Supply, Transaction data with raw wallet/recent-transfer inspection, and Price data with source/proxy explanation separated by time period.
- **Main dataset copy**: shortened and enlarged the main dashboard data note to mention charts/metrics derived from Alchemy transaction and price data plus the hourly update cadence; fuller data coverage details remain on the dataset details page.
- **Dashboard section polish**: renamed the Price, Soulbound, and Chad sections for clearer reader-facing navigation and added a searchable Soulbound wallet verification table with token-specific BaseScan links.
- **Dashboard navigation**: added an Explore more link row after the price story with stable anchors for Chad wallets, Soulbound wallets, Holder distribution, and Holder growth.
- **Dashboard section order**: reordered the post-price sections to match navigation priority (Chad wallets, Soulbound wallets, Holder distribution, Holder growth) and added unique anchor targets with scroll offsets so linked headings remain visible.
- **Price event hover polish**: tightened price-chart event hover behavior from unified x-slice hover to closest-point hover and tuned event marker sizes so nearby events are easier to inspect individually while keeping additional context visible.
- **Price source tooltip**: reformatted the latest-price help text into separate date-range bullets for the DEX proxy period and Alchemy price period.
- **Price chart hover labels**: added dates to both price-line and event hover labels and increased hover distance so daily price/date values are easier to inspect without reintroducing broad unified event hovers.
- **Chad section layout**: moved the cohort summary table below the historical holdings chart so the section flows from criteria and headline metrics to chart, then supporting cohort details and verification.
- **Chad average age marker**: added a vertical marker to the Chad holdings chart at latest cohort date minus the weighted average coin age, tying the headline age metric back to the historical timeline.
- **Soulbound chart simplification**: changed the Soulbound wallets chart from a stacked balance-bucket share view to a single total-TIBBIR-held filled line chart.
- **Soulbound verification link**: added a BaseScan link to the soulbound NFT contract holder list above the searchable wallet verification table.
- **Soulbound chart copy**: simplified the Soulbound chart caption to describe current TIBBIR held by addresses with a soulbound NFT.
- **Main dataset copy**: expanded the top dashboard note from "tx" to "transactions" for clarity.
- **Repo root cleanup**: moved misc local data/config files into `data/` (`price_context_events.json`, `known_addresses.json`, `wallet_labels.json`, and the soulbound NFT holder CSV), updated app/pipeline paths, and removed the obsolete `CLAUDE.md` workflow note.
- **Price raw inspection**: added a dataset-details expander that reads raw price rows from repo-local `data/price_history.csv` rather than storage.
- **Dataset details copy**: changed the transaction data note into two bullets covering safe-block coverage and full transaction-history derivation for wallet balances, metrics, and charts.
- **Public dataset link**: added a dataset-details expander with links to public metadata, schema, sample transactions, full transaction parquet, and a Python loading snippet for all files.
- **Wallet verification UI**: renamed the raw transaction inspection expander to focus on wallet balance verification and latest transactions; wallet balances are searchable and include token-specific BaseScan links.
- **Hourly pipeline cadence**: changed the scheduled GitHub Action from every 4 hours to hourly; the app continues to read from the private bucket, and the public transaction dataset is published at the end of the same hourly run.
- **Dataset note copy**: removed the "Note -" prefix from the top dashboard data-source sentence.
- **Dataset update cadence copy**: split the top dashboard data-source note into bullets clarifying that transaction data updates hourly while price data uses daily price points.
- **Dataset details layout**: moved the last-updated and latest-block cards into the wallet balance/latest transaction verification expander so the snapshot timestamp stays near the data being inspected.
- **Landing page intro**: removed the redundant `Dataset` subheader from the top dashboard intro.
- **Public repo cleanup**: removed the optional `.devcontainer` Codespaces setup, one-time `backfill/` notebooks/state files, and the old wallet-classification prototype GitHub workflow/script before public Streamlit deployment.
- **Secret loading cleanup**: moved Alchemy RPC/API-key environment loading out of shared `config.py` and into `engine/update.py`, so the Streamlit dashboard import path does not touch Alchemy configuration.
- **Public dataset terminology**: changed reader-facing public dataset copy and generated metadata/schema descriptions from "transfers" to "transactions" while preserving existing parquet filenames.
- **Public README**: added a concise public-facing `README.md` with dashboard overview, public dataset links, quickstart snippet, data notes, and a credential safety note.
- **Security basics**: added `requirements.in` for direct dependencies and a fully pinned generated `requirements.txt` for Streamlit/GitHub installs, added read-only `contents` permissions to GitHub Actions, and added a gitignored local security checklist for Streamlit/GitHub deployment.
- **Docs cleanup**: removed the internal `docs/todo.md` scratch list before public deployment.
- **Ignore-file cleanup**: simplified `.gitignore` to current public repo needs: Python/cache files, local secrets, IDE files, scratch folders, and generated bulky data (`*.parquet`, `*.ipynb`).
- **Streamlit navigation cleanup**: changed dataset-details navigation from markdown query links to in-app buttons backed by session state, avoiding new tabs and ugly deployed `~/+/` query URLs.
- **Mobile chart polish**: increased chart heights, shortened date ticks and price legend labels, moved legends below charts, removed legend titles, and hid Plotly modebars to reduce cramped chart rendering on mobile.
- **Soulbound mobile polish**: removed the Soulbound chart y-axis title, increased date tick density, and changed hover to show share of supply rather than raw TIBBIR held.
- **Holder distribution mobile polish**: removed the y-axis title and moved the current wallet count snapshot into a titled vertical bar chart after the wallet-count history section.
- **Holder growth mobile polish**: renamed the section to Wallet count (per bucket), removed the y-axis title, and increased date tick density for the chart.
- **Chart date axes**: reverted forced mobile date tick formatting so Plotly can use its normal date labels across time-series charts.
- **Chart legend readability**: increased shared bottom legend label size across charts that use the common Plotly legend helper.
- **Wallet count structure**: reordered the post-Soulbound sections to show current wallet count first, followed by wallet-count history and holder-distribution history, and added a short explanatory card for what wallet count means.
- **Holder distribution snapshot**: added a current holder distribution bar chart with an explanatory caption before the holder-distribution history chart.
- **Explore links**: split holder distribution navigation into separate current snapshot and history links.
- **Launch price marker**: moved the launch event marker to January 11, 2025 and added a zero-price chart anchor so the label matches the launch date while avoiding an implied exact launch price.
- **Mobile scroll behavior**: disabled Plotly scroll, double-click, and drag zoom gestures across dashboard charts so mobile page scrolling is less likely to get trapped inside a chart.
- **Chart export controls**: restored the Plotly modebar without zoom/pan/select controls, keeping image download available while preserving scroll-safe chart behavior.
- **Wallets vs supply summary**: moved the combined current table to the end of the holder section and renamed it to Wallets vs supply by bucket.
- **Chart height tuning**: reduced shared chart height and current snapshot bar chart heights so mobile pages are less dominated by a single chart.
- **Dashboard data cache**: added a 10-minute TTL to Streamlit storage-backed loaders so hourly bucket updates appear without requiring an app restart.
- **Holder section titles**: shortened wallet-count and holder-distribution history chart titles.
- **Streamlit keepalive**: added a GitHub Actions workflow that pings the public Streamlit `/healthz` endpoint every 15 minutes.
- **Dashboard cadence copy**: softened the top dashboard update copy to say transaction data updates ~hourly and price data updates daily.
- **Chad example copy**: simplified the peak-balance explanation on the worked metric example page.

### 2026-05-25

- **Chad cohort chart**: added a dashboard section for current 10k+ "chad" wallets split into `10k-100k`, `100k-1M`, and `1M+`, showing historical holdings for those current cohorts plus current wallet count, total balance, balance-weighted average coin age, average current/peak, and sold/bought by cohort.
- **Chad cohort dataset**: added `analytics/chads.py` and GCS outputs `tibbir_chad_cohorts.parquet` plus `tibbir_chad_wallets.parquet`. Cohorts require current balance to be at least 90% of peak balance and sold/bought below 20%; known exchange, LP/router, and burn addresses are excluded. The cohort output contains one daily historical balance row per current cohort; the wallet output powers top-10 verification tables with BaseScan links.
- **Jobs/automation**: added `build_chad_cohorts` to manual jobs and the daily pipeline before public dataset publishing.
- **Validation**: prototyped the cohort logic in `sbx/chad_cohorts_prototype.py`, ran a synthetic production test, and ran `python -m compileall analytics engine app.py config.py`.
- **Chad wallet verification UI**: wallet verification tables now show all qualifying wallets per cohort with full addresses, BaseScan token links, fixed-height scrolling, and address search.
- **Chad section UX**: simplified the default dashboard view to headline metrics, a short plain-English definition, cohort summary, and holdings history; wallet verification and the "Example - Chad metrics" link live in the "Example and wallet verification" expander.
- **Worked metric example page**: added a linked "Example - Chad metrics" page for wallet `0xffb3f0b6817036985f49c311a2f7d597bcb02910`, time-frozen at 2026-05-25 00:00 UTC and backed by `examples/coin_age_example_wallet_events.csv`, including inclusion criteria checks, age mass, average coin age, and event-by-event replay.
- **Worked example table fit**: compacted the event replay table labels and column widths so all replay metrics, including final average age, fit in the centered dashboard layout; the replay now uses date-only labels, in/out transfer types, and abbreviated balance headers, with extra aging-caption detail removed.

### 2026-05-17

- **Price history pipeline**: added daily TIBBIR/USD price fetch from Alchemy Prices API using Base contract address (`network=base-mainnet`, interval `1d`). Output file: `tibbir_price_history.parquet`.
- **Price history update behavior**: incremental updates drop and refetch the latest stored day before appending new days, mirroring the existing pattern for incomplete/settling daily data.
- **Price history API windowing**: full rebuilds split Alchemy `1d` price requests into <=365-point chunks to satisfy the Prices API limit.
- **Early price backfill**: when Alchemy TIBBIR price history starts after launch, rebuilds fill the missing leading range from the TIBBIR/VIRTUAL Uniswap v2 pool's on-chain `Sync` reserve events and daily VIRTUAL/USD prices.
- **Dashboard chart**: added a simple `Price` section in `app.py` with range selector and latest daily price metric.
- **Dashboard price note**: added UI copy clarifying that early launch rows are UTC end-of-day DEX reserve-derived close proxies and later rows use Alchemy daily token prices.
- **Dashboard price note dates**: made source boundary explicit: Jan 12-Mar 24, 2025 uses DEX reserve-derived close proxy; Mar 25, 2025 onward uses Alchemy daily token prices.
- **Price lore labels**: added a dashboard toggle for significant event labels on the price chart. Markers include Jan 12, 2025 mickym.eth deployer funding, launch transaction, and launch-window Crypto_Nolt / Altcoinist posts, Feb 10, 2025 early Altcoinist thread, Mar 24, 2025 "It takes money to change money", Apr 22, 2025 Coinbase "updating the system" bonus folklore, May 9, 2025 Altcoinist first article, Jul 28, 2025 CryptoPunk #9098 / commemorative soulbound NFT announcement, Oct 2, 2025 Micky Malka appearance with Raoul Pal, Oct 16, 2025 Ribbit rebrand / Token Letter surfaced, Oct 27, Nov 1, Nov 10, Nov 13, and Nov 24, 2025 Beeple TIBBIR art posts, Nov 11, 2025 Vlad Tenev reply, Nov 24-25, 2025 ko-na-mi honorable mentions, Dec 17, 2025 Ribbit Capital TIBBIR imagery, Jan 29, 2026 UTC Ribbita.ai launch / agentic commerce terminal plus 573/Konami numerology honorable mention, Feb 11, 2026 Altcoinist "I will retire You" article, and Apr 12, 2026 MoonPay TIBBIR flirt.
- **CryptoPunk lore links**: added the Base soulbound token contract link to the Jul 28, 2025 CryptoPunk #9098 event.
- **Soulbound NFT holder supply**: added tracked soulbound NFT holder export CSV, a `build_soulbound_holder_supply` job, GCS output `tibbir_soulbound_holder_supply.parquet`, and a separate dashboard chart showing TIBBIR supply held by those addresses over time by balance bucket.
- **Price lore zones**: added support for shaded price-chart lore ranges, currently using the "No Dates Zone" from Jul 22-Nov 12, 2025.
- **Price lore grouping**: chart markers now group same-day lore events into one marker with date/count labels to avoid stacked dots; the event list below the chart preserves individual links grouped by date.
- **Price lore marker styling**: removed dotted vertical event lines from the price chart; point labels remain, and shaded zone ranges are unchanged.
- **Price lore compactness**: removed always-visible text labels from point markers to keep the default chart readable; event names remain in hover and in the grouped timeline list below.
- **Public repo hygiene**: redacted the tracked backfill notebook's hardcoded Alchemy endpoint and expanded `.gitignore` for local secrets/settings/scratch files before making the repo public.
- **Jobs/automation**: added manual jobs `rebuild_price_history` and `update_price_history`; daily pipeline now runs `update_price_history` before publishing the public dataset.
- **Validation**: prototyped parsing/merge behavior in `sbx/price_history_prototype.py`; ran syntax compilation and mocked engine-level rebuild/update checks.

### 2026-05-11 (session 7)

- **Public dataset publishing** (`engine/update.py` `publish_public_dataset()`): writes 4 files to `gs://tibson-public` on every pipeline run — `transfers_master.parquet` (full transaction dataset), `sample_transfers.parquet` (first 1,000 transaction rows), `schema.json` (column definitions, dtypes, example values, Python quickstart), `metadata.json` (row count, block range, last updated, file listing). Designed so an AI assistant or analyst can orient immediately from the metadata/schema URLs.
- **`config.py`**: added `PUBLIC_GCS_BUCKET`, `PUBLIC_GCS_PREFIX`, `PUBLIC_BASE_URL` pointing to `tibson-public`.
- **Pipeline frequency**: `daily_update.yml` cron changed from `0 4 * * *` (once daily) to hourly; the scheduled pipeline updates private app data first and publishes the public dataset at the end of the same run.
- **`run_job.py` + `run_job.yml`**: `publish_public_dataset` added as a manual job option.
- **`run_daily.py`**: `publish_public_dataset()` called at the end of every pipeline run.
- **Git remote**: moved to the public analytics repository.
- **Public URLs**: `https://storage.googleapis.com/tibson-public/transfers_master.parquet` · `schema.json` · `sample_transfers.parquet` · `metadata.json`

### 2026-05-09

- **Project review / orientation**: reviewed the current pipeline, dashboard, wallet analytics, GitHub Actions jobs, and docs before starting the next feature. No production logic changed.
- **Validation**: ran `python -m compileall analytics engine app.py config.py`; syntax compilation passed.
- **Sandbox wallet classification prototype** (`sbx/wallet_classification_prototype.py`): local-only prototype for classifying all wallets with `primary_category`, `behavior_type`, `classification_confidence`, `consequence_score`, and reviewable reason strings. Categories are capped at 10 and include market infrastructure, project/team, contract/lock, treasury candidate, strategic holder, accumulator, active trader, exiter, retail holder, and small/dust. The script emits full parquet, top-1000 CSV, top-1000 HTML, and summary JSON when run successfully.
- **Classifier design**: uses existing `wallet_events`, `wallet_summary`, known labels, balance replay, counterparty counts, mint-source exposure, retention, trading intensity, and early-wallet/consequence scoring. Entity type and behavior type are kept separate to avoid forcing wallets into one overloaded label.
- **Verification status**: syntax checks pass with the Anaconda `onchain` environment. Full local execution was blocked by GCS network/auth access in the Codex sandbox, so the manual GitHub Actions verifier was run successfully instead (`run 25595029595`). The artifact was downloaded locally to `sbx/wallet_classification_action_run_25595029595/`.
- **Classifier refinement**: top-1000 review set now uses `peak_balance` descending rather than `consequence_score`. `config.CONTRACT_ADDRESS` is hard-labeled as `TIBBIR token contract` / `token_contract`, preventing the token contract from being classified as a normal exiter. The prototype now emits recursive zero-address flow artifacts: `null_flow_cluster_wallets.csv` and `null_flow_cluster_edges.csv`.
- **Refined verification**: manual GitHub Actions verifier succeeded again (`run 25595337777`), downloaded locally to `sbx/wallet_classification_action_run_25595337777/`. The top-1000 selection is peak-holdings based; the token contract now appears as `contract_or_lock`. The first null-flow pass found 173 cluster wallet rows and 312 cluster edge rows, dominated by the large `0x4213...` mint-source branch.

### 2026-05-08 (session 6)

- **Archetype chart** (`sbx/_build_archetype_chart.py`): standalone script producing `sbx/archetype_timeseries_all.html`. Covers all 101k+ circulating wallets (same universe as HODL waves). Nine categories: giga chad, chad, market, swinger-curious, swinger-degen, jeet, new, unknown, small.
- **Reworked turnover metric**: replaced `total_out / total_in` with `trading_intensity = total_out / peak_balance`. Rationale: the old ratio is bounded near 1.0 for active traders who buy/sell equal amounts; the new metric measures how many times a wallet has cycled through its peak position (>1.0 only possible via repeated buy/sell cycles).
- **New `market` category**: wallets identified as exchanges, DEX routers, or liquidity pools (sourced from `data/wallet_labels.json` confirmed entries with type `exchange`, `router`, or `lp`). Checked first in classification so known infrastructure is never misclassified. 5 wallets: MEXC 15, Uniswap V4 Router, TIBBIR/VIRTUAL LP, 2× TIBBIR/WETH LP.
- **`data/wallet_labels.json`**: tracked confirmed and watchlist addresses with labels, types, entities, and confidence scores. Currently 5 confirmed entries + 1 watchlist.
- **Top-100 wallet tables**: each archetype tab in the HTML shows a scrollable table (full address, label if known, current balance, peak balance, retention %, trading intensity).
- **Category definitions (final)**:
  - `giga chad`: retention = 100%, intensity = 0 (never sold)
  - `chad`: retention ≥ 70%, intensity < 0.3
  - `jeet`: retention < 20%
  - `swinger-degen`: intensity > 2.0 (sold >2× peak; 77 wallets)
  - `swinger-curious`: intensity 0.5–2.0
  - `new`: first seen < 90 days ago
  - `small`: current balance < 100k TIBBIR
  - `market`: known exchange/LP address

### 2026-05-07 – 2026-05-08 (session 5)

- **Sandbox exploration** (`sbx/wallet_explore.ipynb`): extended with archetype classification, time series, and HODL waves. All sandbox-only — no production code changed.
- **Archetype classification** (notebook): five categories — `chad` (retention ≥ 0.7), `jeet` (retention < 0.2), `swinger` (turnover ≥ 0.5, not chad/jeet), `new` (first seen < 90 days ago), `unknown`. Key fix: `new` uses `days_since_first_seen` (today − first_seen_timestamp), NOT `wallet_age_days` (last_seen − first_seen). The latter misclassified old single-burst wallets as new.
- **Archetype time series**: daily balance replay from `wallet_events` for all 1,146 candidate wallets, stacked area chart per archetype (`sbx/archetype_timeseries.html`).
- **HODL waves** (`sbx/hodl_waves.html`): daily coin-age chart covering all 101,778 circulating wallets (includes exchanges). Age = days since last inbound transfer, floored to day. Six bands: < 1w · 1w–1m · 1m–3m · 3m–6m · 6m–12m · 12m+. Verifies to 0.0000 discrepancy against expected circulating supply.
- **Profiler rebuild**: ran `build_wallet_profiler` to sync profiler with latest `wallet_events` (prior build was 13h stale; 2 wallets had sold tokens in the gap).

### 2026-05-06 (session 4)

- **New** `analytics/wallet_profiler.py`: Candidate wallet universe for future archetype classification. `ProfilerConfig` dataclass holds all thresholds. `filter_wallets` excludes exchange/system wallets (combined activity + single-side thresholds) with tracked exclusion reasons. `compute_peak_balances` replays wallet histories using `(block_number, log_index)` ordering (log_index extracted from event_id) to find peak holding. `build_wallet_profiler_table` runs the full pipeline and computes `retention_ratio`, `wallet_age_days`. `validate_profiler_table` enforces sanity invariants. No archetype labels — those are a downstream layer.
- **New GCS file**: `tibbir_wallet_profiler.parquet` — 1,145 candidate wallets (≥1M peak balance, not exchange/system). 206 excluded by activity filter, 100,324 below peak threshold.
- **New metadata fields**: `wallet_profiler_wallet_count`, `wallet_profiler_excluded_count`, `wallet_profiler_excl_breakdown`, `wallet_profiler_built_utc`, `wallet_profiler_config`.
- **New job**: `build_wallet_profiler` in `run_job.py` and `run_job.yml`.

### 2026-05-06 (session 3)

- **New** `analytics/wallet.py`: Pure analytics module for the wallet-centric event layer. Functions: `build_wallet_events` (expands master ledger to one row per wallet per transfer, direction-tagged), `build_wallet_summary` (per-wallet raw stats — balance, tx counts, first/last seen, totals received/sent), `get_wallet_events` (slice event log for one address), `replay_wallet_balance` (chronological balance timeline for one address).
- **New GCS files**: `tibbir_wallet_events.parquet` (6,435,360 rows, 101,675 addresses), `tibbir_wallet_summary.parquet` (101,675 rows).
- **New metadata fields**: `wallet_events_row_count`, `wallet_events_address_count`, `wallet_events_built_utc`, `transfers_master_row_count`.
- **New jobs**: `build_wallet_events`, `build_wallet_summary` — added to `run_job.py`, `run_job.yml`, and `run_daily.py`.
- **New** `sbx/wallet_events_prototype.ipynb`: validation notebook for the new layer.
- **Design principle**: wallet_events and wallet_summary store raw events/stats only — no jeet/chad/swinger classifications. All downstream analysis builds on these as inputs.

### 2026-05-06 (session 2)

- **Change** (`engine/update.py` `build_wallet_snapshot`): now computes and writes three new metadata fields — `total_minted_supply` (tokens ever sent from zero address, ~1B), `dead_address_supply` (dead address balance, ~369k), `holders_10k_plus` (wallet count with balance ≥ 10k). `wallet_snapshot_total_supply` is now superseded by `total_minted_supply` for supply display.
- **Change** (`app.py`): Dataset section restructured. Contract/address/supply info moved into a collapsible "Contract & Supply" expander. Metrics section shows Last updated, Latest block. Raw data tables moved into a collapsible "Inspect raw data" expander with a full-width "Pull from storage" button inside. Supply labels updated to "Total initial supply", "Initial supply − burns", "Initial supply − (burns + dead)".

### 2026-05-06

- **New** `data/known_addresses.json`: labeled address registry. Currently contains zero address (burn/mint sink), dead address (0x000...dead), and MEXC 15. To be extended as more wallets are identified.
- **Change** (`engine/update.py` `build_wallet_activity`): dead address is now included in `wallet_activity` so its balance is visible. Zero address remains excluded (minting source, not a real wallet). Coin age functions explicitly exclude dead address separately from the exchange filter.

### 2026-05-05

- **Bug fix** (`sbx/coin_age.py` → `analytics/coin_age.py`): `apply_outgoing` now clamps `amount/balance` fraction to 1.0 and both `age_mass` and `balance` to `>= 0`. Root cause: float rounding caused `amount` to slightly exceed `balance` on full-exit transfers, making balance and age_mass go negative. Subsequent `apply_time` calls accumulated a huge negative age_mass; later `apply_outgoing` calls then flipped it to a huge positive, producing `avg_age` values up to 10^302 in the raw CSV.
- **New** `analytics/coin_age.py`: promoted coin age algorithm to production. Contains `WalletState`, `build_weekly_snapshots`, and `project_snapshots_forward` (projects inactive wallets forward in time without re-scanning transfers).
- **New GCS files**: `tibbir_wallet_activity.parquet` (101,625 addresses with balance + tx counts), `tibbir_coin_age_snapshots.parquet` (4,671,130 rows across 101,370 wallets).
- **New engine functions** (`engine/update.py`): `build_wallet_activity`, `rebuild_coin_age_snapshots`, `update_coin_age_snapshots`.
- **Daily pipeline** (`engine/run_daily.py`): now also runs `build_wallet_activity` and `update_coin_age_snapshots` each day.
- **run_job.yml + run_job.py**: three new manual job options — `build_wallet_activity`, `rebuild_coin_age_snapshots`, `update_coin_age_snapshots`.
- **New** `sbx/coin_age_viz.ipynb`: exploratory viz notebook with balance-overview-per-week (stacked area, bucketed) and coin-age-per-week (single balance-weighted line). Loads from `sbx/all_snapshots_coinAge.csv`; includes a data-cleaning step that removes rows with `balance ≤ 0`, `avg_age < 0`, `avg_age > 730`, or NaN age.

### 2026-05-04
- **Legacy workflow note**: `CLAUDE.md` previously documented an sbx-first testing and session wrap-up protocol; it has since been removed.
- **Bug fix** (`sbx/coin_age.py`): removed final partial-week snapshot from `build_weekly_snapshots`. It was emitting a current-state row alongside complete-week rows, making the last avg_age increment look anomalously small.
- **New** `sbx/wallet_activity.ipynb`: builds address/balance/tx_in/tx_out table for every wallet that ever transacted on the CA (not just current holders).
- **New** `sbx/coin_age_pipeline.ipynb`: end-to-end coin age pipeline — builds wallet activity, saves to parquet, filters exchanges/LPs (tx_in > 1000 AND tx_out > 1000), pre-indexes transfers by address for O(1) per-wallet lookup, runs `build_weekly_snapshots` for ~101k wallets in ~12 min, emits progress every 1000 wallets.
- **New** `sbx/coin_age_verification.ipynb`: balance accounting checks — snap_balance + excl_balance + burned_balance vs total supply, weekly time series of all three columns.
- **Fix** (pipeline + verification): burn address (`0x000...dead`) now excluded from wallet_activity and treated as its own group in verification. Previously it slipped through the exchange filter (high tx_in, zero tx_out) and was included in coin age computation.
- **Fix** (verification Cell 7): excluded wallet balance lookup aligned to W+7 boundary to match snapshot semantics, fixing ~5M token timing mismatch in weekly totals.

## Decisions

- **Archetype `new` uses first-seen recency, not activity span**: `wallet_age_days` (last_seen − first_seen) measures how long a wallet was *active*, not how old it is. A wallet that bought and sold on day 1 has age_days=0 and would falsely appear "new" 500 days later. `days_since_first_seen` (now − first_seen_timestamp) correctly identifies genuinely recent wallets.
- **HODL waves excludes dead address, includes exchanges**: dead address (~369k tokens) holds permanently burned supply — including it would misrepresent circulating coins. Exchanges are included; they are filtered only at the profiler layer, not at wallet_events.
- **HODL waves age floored to day**: `last_in_ts` is an exact timestamp; `date` is midnight. Computing `date − last_in_ts` raw gives negative ages for same-day receivers (received at 14:00, date is 00:00). Flooring `last_in_ts` to the day before subtraction makes age = 0 for same-day receipts and eliminates values outside the bin range that `pd.cut` would silently drop.
- **HODL waves long-format computation**: avoids materializing a 481 × 101k balance matrix (~1.5 GB). Instead: aggregate to one row per (address, active_day), then reindex × ffill in long format (~49M rows). Faster and within normal RAM.

- **wallet_profiler — classification-free candidate universe**: The profiler table contains only computable facts (peak balance, retention ratio, age). Jeet/chad/swinger labels are a downstream interpretation layer, not part of this table. This keeps the data layer stable as classification logic evolves.
- **log_index from event_id**: Alchemy event_id format is `<txhash>:log:<n>`. We extract the integer log index for correct intra-block ordering in balance replay. This avoids needing a separate log_index column in the master transfers.
- **wallet_events design — store events, not conclusions**: The index layer (`wallet_events`, `wallet_summary`) contains only raw facts. No wallet classifications live in the index. Downstream analysis (coin age, behavioral scoring) uses these as inputs.
- **wallet_events sorted by (address, block_number)**: Enables fast per-wallet slicing via pandas boolean indexing; also compatible with parquet predicate pushdown for future query optimization.
- **build_wallet_summary timing from combined events**: First/last block and timestamp computed from a single merged in+out frame (one groupby pass) to avoid NaT min/max issues with reindexed per-direction DataFrames.

- **Exchange/LP filter**: tx_in > 1000 AND tx_out > 1000 (both must be high). Excludes 200 wallets from ~101k. Burn address handled separately (would pass filter due to zero tx_out).
- **Dead address** (`0x000...dead`): included in `wallet_activity` (its ~369k token balance is visible), but excluded from coin age computation. Zero address remains fully excluded everywhere.
- **`data/known_addresses.json`**: single source of truth for labeled addresses (burn destinations, exchanges, etc.). Keyed by lowercase address.
- **Pre-indexing transfers**: build an address→row_index dict in O(n_transfers) before the wallet loop, avoiding O(n_wallets × n_transfers) full scans. Cut expected runtime from days to ~12 min.
- **Partial-week snapshot removed**: `build_weekly_snapshots` now only emits at completed Monday boundaries, keeping the time series semantically consistent.
- **sbx/ stays gitignored**: coin age work remains exploratory until it's ready to promote to `engine/` or `analytics/`.
- **Chad current/peak and sold/bought definitions**: the peak-holdings filter is implemented as `current_balance / peak_balance >= 0.90`; sold/bought follows the example as `total_sent / total_received < 0.20`.

## Known Issues

- `AGENTS.md` still documents manual jobs as `python engine/run_job.py <job_name>`, but the implemented CLI requires `python engine/run_job.py --job <job_name>`.
- Wallet classification clustering is still conservative and review-oriented: current recursive null-flow settings follow the top 30 direct mint recipients, max depth 3, top 20 outgoing edges per node, and edges >= 100k TIBBIR. These thresholds may need tuning after manual review.
- 24 included wallets have no snapshot (likely single-transfer wallets whose only event falls within the current partial-week boundary). Balance is negligible.
- `wallet_activity.parquet` balance uses float64 division of raw int128 amounts — negligible precision loss but worth noting if sub-token accuracy ever matters.
- `sbx/all_snapshots_coinAge.csv` (local, gitignored) was generated before the `apply_outgoing` float-clamp fix and contains corrupt avg_age values; superseded by the GCS parquet.

## Build & Test Notes

Price history jobs (run via `python engine/run_job.py --job <name>`):
- `rebuild_price_history` - full daily TIBBIR/USD history rebuild from Alchemy Prices API
- `update_price_history` - incremental daily TIBBIR/USD refresh; drops/refetches latest stored day
- `build_soulbound_holder_supply` - rebuilds daily TIBBIR balances for addresses in the soulbound NFT holder CSV
- `build_chad_cohorts` - rebuilds current chad cohort aggregates from wallet events, wallet summary, and coin-age snapshots

New production jobs (run via `python engine/run_job.py --job <name>`):
- `build_wallet_events` — ~30 s, produces 6.4M-row event log
- `build_wallet_summary` — ~20 s, produces 101k-row summary table
- Both depend on `tibbir_transfers_master.parquet` being current

Old production jobs (run via `python engine/run_job.py --job <name>`):
- `build_wallet_activity` — ~5 s, must run before coin age rebuild
- `rebuild_coin_age_snapshots` — ~10 min full rebuild
- `update_coin_age_snapshots` — incremental daily update; fast for weeks with few active wallets

All three are also in the `run_job.yml` GitHub Actions dropdown.
