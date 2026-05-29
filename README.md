# tibson analytics

Public Streamlit dashboard for Tibbir analytics on Base.

The dataset starts from the Tibbir contract address on Base:

```text
0xa4a2e2ca3fbfe21aed83471d28b6f65a233c6e00
```

Alchemy is used to fetch the full ERC-20 transaction history for that contract. The dashboard then builds derived wallet and holder views from that history.

Price data is built separately:

- Jan 12-Mar 24, 2025: UTC end-of-day DEX reserve-derived close proxy from the TIBBIR/VIRTUAL pool
- Mar 25, 2025 onward: Alchemy daily token prices

## Public Dataset

A public transaction dataset is also published here:

```text
https://storage.googleapis.com/tibson-public
```

Includes the following files:

- `metadata.json` - dataset stats and file listing
- `schema.json` - column definitions, dtypes, examples, and Python quickstart
- `sample_transfers.parquet` - first 1,000 transaction rows
- `transfers_master.parquet` - full transaction dataset

Quickstart:

```python
import requests
import pandas as pd

base = "https://storage.googleapis.com/tibson-public"
metadata = requests.get(f"{base}/metadata.json").json()
schema = requests.get(f"{base}/schema.json").json()
sample = pd.read_parquet(f"{base}/sample_transfers.parquet")
transactions = pd.read_parquet(f"{base}/transfers_master.parquet")
```
