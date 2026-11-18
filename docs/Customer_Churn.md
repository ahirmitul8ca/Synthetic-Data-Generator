
# Customer_Churn
 
Synthetic B2B SaaS data for the **Customer Churn & Revenue Intelligence Engine** project (dbt Core, BigQuery/DuckDB, Power BI). It produces the five raw (bronze) tables from the project requirements plus an answer key.
 
All data is synthetic.
 
## Run
 
```bash
python run.py Customer_Churn
# or
python generators/Customer_Churn.py
```
 
Needs `numpy`, `pandas`, `pyarrow` (no Data Designer or LLM). Output goes to `Synthetic_Data/Customer_Churn/<timestamp>/` and `Synthetic_Data/Customer_Churn/latest/`, as Parquet and CSV. Runs are seeded, so the same settings give the same data.
 
## Settings
 
Set at the top of `generators/Customer_Churn.py`:
 
| Setting | Default | Meaning |
|---|---|---|
| `N_CUSTOMERS` | 5000 | Number of customers. About 500 events per customer, so 5,000 gives about 2.5M events |
| `SEED` | 42 | Random seed |
| `DIRTY_RATE` | 0.02 | Fraction of rows corrupted with data-quality issues. `0` gives clean data |
| `ADD_DUPLICATES` | True | Add duplicate webhook rows to invoices, events and tickets |
| `OUTPUT_NAME` | `Customer_Churn` | Output folder name |
 
Churn behaviour is tuned with the constants below the settings. The main one is `BASE_VOL` (base monthly voluntary churn, default 0.026). Lower it to about 0.018 for a gentler churn curve.
 
## Timeline
 
Customers sign up from 2024-01-01 to 2026-09-30 with growing monthly volume. The data is cut off at 2026-10-31 (the "as of" date).
 
## Tables
 
Money columns are **integer cents**. Every table has `_ingested_at`.
 
| Table | Grain | Columns |
|---|---|---|
| `raw_customers` | one row per customer | `customer_id`, `signup_date`, `country`, `acquisition_channel`, `company_size`, `_ingested_at` |
| `raw_subscriptions` | one row per subscription version | `subscription_id`, `customer_id`, `plan_tier`, `mrr_amount`, `status`, `started_at`, `ended_at`, `canceled_at`, `cancellation_reason`, `_ingested_at` |
| `raw_invoices` | one row per monthly invoice | `invoice_id`, `subscription_id`, `customer_id`, `amount_due`, `status`, `attempt_count`, `invoice_date`, `_ingested_at` |
| `raw_product_events` | one row per event | `event_id`, `customer_id`, `event_name`, `event_timestamp`, `_ingested_at` |
| `raw_support_tickets` | one row per ticket | `ticket_id`, `customer_id`, `priority`, `status`, `created_at`, `resolved_at`, `_ingested_at` |
| `ground_truth_customers` | one row per customer | `customer_id`, `signup_at`, `canceled_at`, `churn_type`, `cancellation_reason`, `at_risk` |
 
Notes:
- **Subscriptions are SCD-style.** A new `subscription_id` is created whenever the plan or seat count changes. Superseded versions have status `Replaced` and an `ended_at`. The current version is `Active`. A cancelled one is `Canceled` with `canceled_at`.
- **Plan tiers:** `Basic`, `Pro`, `Enterprise`.
- **Invoice status** is `paid` or `failed`. `attempt_count` is 1 to 4 (dunning retries). A failed invoice means all four attempts failed.
- **Event names:** `login`, `dashboard_view`, `report_created`, `report_shared`, `export_data`, `invite_user`, `integration_connected`, `api_call`.
- **Ticket status:** `open`, `pending`, `resolved`, `closed`. Open and pending tickets have no `resolved_at`.
- `invoices.customer_id` is an extra column beyond the requirements, to make joins easier.
## How the data is built
 
A month-by-month billing simulation runs for each customer. Everything else is derived from it, so the tables agree with each other.
 
- **Voluntary churn** uses a monthly hazard driven by tenure (spikes in months 1 to 3 and at the 12-month renewal), acquisition channel, company size and plan. Each voluntary churn gets a `cancellation_reason`.
- **Involuntary churn** comes only from billing: an invoice that fails all four dunning attempts leads to cancellation 14 days later with reason `payment_failed`. About a quarter of churn is involuntary.
- **MRR movements:** new, upgrade, downgrade, seat expansion and seat contraction all occur, so the MRR waterfall has every movement type.
- **Usage decay:** voluntary churners' weekly events fall sharply in the last four weeks before they cancel. Involuntary churners show no decay.
- **At-risk customers:** about 10% of active customers are disengaging, with falling usage and more slow or unresolved tickets. They are flagged in `ground_truth_customers.at_risk`.
- **Support friction:** tickets rise and resolve more slowly in the weeks before voluntary churn.
## Planted data-quality issues
 
Controlled by `DIRTY_RATE`. Counts below are for the default 5,000 customers and `0.02`. The injected counts are written to `logs/Customer_Churn.log` on every run.
 
| Table | Issue | Approx. rows |
|---|---|---|
| `raw_customers` | country variants and nulls (`usa`, `United States`, `UK`, null) | 100 |
| `raw_customers` | `acquisition_channel` casing and stray spaces | 100 |
| `raw_customers` | null `company_size` | 50 |
| `raw_subscriptions` | `status` casing and stray spaces | 157 |
| `raw_subscriptions` | negative `mrr_amount` | 39 |
| `raw_subscriptions` | `canceled_at` before `started_at` | 11 |
| `raw_invoices` | `status` casing and stray spaces | 1,000 |
| `raw_invoices` | null `attempt_count` | 510 |
| `raw_invoices` | zero `amount_due` | 255 |
| `raw_product_events` | `event_name` casing and stray spaces | 5,000 |
| `raw_product_events` | null `customer_id` | 1,250 |
| `raw_product_events` | orphan `customer_id` (`cus_999999`) | 1,250 |
| `raw_product_events` | timestamp in the future | 500 |
| `raw_support_tickets` | `priority` casing and stray spaces | 351 |
| `raw_support_tickets` | `resolved_at` before `created_at` | 162 |
| invoices, events, tickets | duplicate webhook rows (later `_ingested_at`) | about 1%, 0.4%, 0.5% |
 
`ground_truth_customers` is never corrupted.
 
## Validation
 
Before duplicates and dirty data are added, the generator checks the clean tables and stops with an error if any of these fail:
- no subscription cancelled before it started
- at most one `Active` subscription per customer
- every subscription, invoice and event points to a real customer or subscription
- no events after the as-of date
## Using it with dbt
 
- **Staging:** lowercase and trim the enums, deduplicate invoices, events and tickets on their id keeping the latest `_ingested_at`, convert cents to decimals, and drop or quarantine rows that fail your tests.
- **Tests:** `relationships` on events, `accepted_values` on status and priority fields, and a singular test that `canceled_at` is never before `started_at`. The planted issues are there so these tests have something to catch.
- **Check your marts:** compare `fct_churn_events` and the voluntary versus involuntary split against `ground_truth_customers`.
## Output size
 
At the default size the events CSV is about 190 MB, over GitHub's 100 MB limit. Keep `Synthetic_Data/` git-ignored and recreate the data with the seed.
 
