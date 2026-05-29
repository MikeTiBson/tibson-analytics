# Todo

## Coin Age Pipeline

- [ ] Re-run `sbx/coin_age_pipeline.ipynb` Cells 3–7 to regenerate `wallet_activity.parquet` and `all_snapshots_coinAge.csv` now that the burn address is excluded from wallet_activity
- [ ] Run `sbx/coin_age_verification.ipynb` end-to-end on the clean data and confirm `total` column is stable across all weeks
- [ ] Decide on next use of coin age data — options:
  - Compute a global balance-weighted avg_age time series (already scaffolded in `build_global_avg_age`)
  - Add coin age distribution chart to the Streamlit dashboard
  - Export weekly global avg_age as a GCS parquet for the dashboard to consume

## Potential Improvements

- [ ] Review the 24 wallets with no snapshot — confirm they are genuinely edge cases (e.g. received tokens this week only) and their balance is negligible
- [ ] Consider promoting `sbx/coin_age.py` logic to `analytics/` once it's validated, so it can be used in the production pipeline
