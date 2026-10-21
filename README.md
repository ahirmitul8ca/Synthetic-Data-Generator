# Synthetic Data Generator

A small toolkit for building realistic, internally consistent synthetic datasets with **NVIDIA NeMo Data Designer** and **pandas/numpy**. Each dataset is one self-contained script in `generators/`; shared code (folders, logging, UUIDs, timestamps, saving) lives in `helpers.py` and `File_Manager.py`.

All data is synthetic. No real customer or financial data is used.

## Datasets

| Generator | Description | Docs |
|---|---|---|
| `payflow_ledger` | Payments platform with a double-entry ledger, refunds, failed payments and risk-based settlements (5 tables) | [docs/payflow_ledger.md](docs/payflow_ledger.md) |

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt     # data-designer, pandas, numpy, pyarrow (Python 3.10 to 3.13)

python run.py                       # list available generators
python run.py payflow_ledger        # run one
```

If Data Designer complains about missing model providers or models (even though the ledger generator uses no LLM columns), set them up once:

```bash
data-designer config providers      # configure a model provider
data-designer config models         # configure model settings
data-designer config list           # view current settings
```

Output goes to `Synthetic_Data/<dataset>/<timestamp>/` (one folder per run) and `Synthetic_Data/<dataset>/latest/` (always the newest run). Every table is saved as Parquet and CSV. Logs go to `logs/<dataset>.log`.

## Repository structure

```
.
├── run.py                  # entry point: python run.py <generator>
├── File_Manager.py         # paths, run folders, "latest" folders
├── requirements.txt
├── helpers.py              # logging, uuids, timestamps, validation helper, save_table
├── generators/
│   ├── __init__.py
│   └── payflow_ledger.py   # one script per dataset
├── docs/
│   ├── payflow_ledger.md   # dataset documentation
│   └── Synthetic_Data_Playbook.md   # techniques and lessons, reusable for new datasets
├── Synthetic_Data/         # generated output (git-ignored)
└── logs/                   # run logs (git-ignored)
```

## Adding a new dataset

1. Create `generators/<name>.py` with a `main()` function.
2. In it, set `DATASET_NAME = "<name>"` and use the shared helpers:

```python
from File_Manager import create_parquet_timestamped_dir, ensure_directories, get_latest_dir
from helpers import new_uuid, raise_if_problems, random_timestamps, save_table, setup_logging

DATASET_NAME = "my_dataset"
logger = logging.getLogger(DATASET_NAME)

def main() -> None:
    ensure_directories()
    setup_logging(DATASET_NAME)
    run_dir = create_parquet_timestamped_dir(DATASET_NAME)
    latest_dir = get_latest_dir(DATASET_NAME)
    ...  # build tables, validate, then:
    save_table(df, "my_table", run_dir, latest_dir)
```

3. Run it with `python run.py <name>`. It shows up in the generator list automatically.
4. Add a docs page in `docs/` and a row in the table above.

Keep dataset-specific settings (row counts, rates, reference data) inside the generator. Only put code in `helpers.py` if at least two datasets need it. Read `docs/Synthetic_Data_Playbook.md` for the design pattern (reference tables, Data Designer for random columns, pandas for rules, validation, injected issues) and the pitfalls to avoid.

## Run generators from the repo root

Run commands from the repository root (`python run.py ...`), not from inside `generators/`, so the shared modules can be imported.

## License

Add your preferred license here (for example, MIT).