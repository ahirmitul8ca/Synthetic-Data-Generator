# Synthetic Data Playbook (lessons from a previous project)

> Give this file to an AI model at the start of a new synthetic data project. It describes the techniques, design choices and pitfalls from an earlier project. It contains no table or column names on purpose: the new project has its own schema, so apply these ideas to it.

## 1. What was built before (in general terms)

- A multi-table synthetic dataset for an analytics engineering portfolio project (dbt, a cloud warehouse, a BI tool).
- Built with **NVIDIA NeMo Data Designer** (Python package) plus **pandas/numpy**, in a single generator script.
- The data had a small set of fixed reference entities, one large transactional table, a set of derived records, and a periodic rollup table.
- Output: one timestamped folder per run, plus a "latest" folder, each table saved as Parquet and CSV.
- Roughly 27,000 base records produced about 52,000 detail rows and about 2,000 rollup rows.

## 2. Architecture that worked

1. **Setup:** create directories, configure logging (file and console), create a timestamped output folder.
2. **Reference tables first:** small lists of entities (categories, accounts, customers, and so on) defined as fixed rows in code or CSV, not randomly sampled.
3. **Random base records:** Data Designer generates the independent random columns.
4. **Business rules in pandas:** everything that depends on other columns (derived values, relationships, time logic) is applied after generation.
5. **Derived tables:** detail rows, linked records and rollups are built from the base records.
6. **Validation:** a function checks the data and stops the script if anything is wrong.
7. **Optional mess injection:** deliberately damage a copy of one table.
8. **Save:** Parquet and CSV per table, to the run folder and to a stable "latest" folder.

Keep all tunable numbers (row counts, rates, weights, seed, date window) as named constants at the top of the file.

## 3. Techniques for realistic variance

### Weighted categories
- Use weights instead of uniform choice for status-like columns (for example, a dominant "good" value with small shares for others).
- Equal-probability choices look fake. Real data is skewed.

### Segment-dependent behavior
- Make a rate depend on more than one attribute at once. Example: the chance of a failure was a base rate per channel multiplied by a factor per risk segment.
- Then make the reason or sub-type depend on the same attributes (for example, one flaky channel gets many more timeouts, a high-risk segment gets more fraud-type reasons).
- Result: breakdowns by channel or segment show a real story, instead of identical percentages everywhere.

### Time patterns
- Spread timestamps over a fixed window (for example, 365 days) using per-day weights: quieter weekends, busier month ends.
- Add a second timestamp that follows the first by a delay that depends on status (fast for good outcomes, hours or days for slow ones). Enforce that the later timestamp is never earlier.
- Known gap: time of day was uniform. Real traffic peaks in business hours, so weight the hour of day too.
- Never generate records before the related entity existed (for example, before an onboarding date).

### Amount distributions
- Uniform amounts were used and look artificial. Prefer a skewed distribution (many small, few large), for example lognormal, then round to the currency's precision.
- Store money as integer minor units and derive the decimal value from it, never generate both independently.

### Linked and reversal records
- A small share (about 3%) of completed records spawned a follow-up record (a refund-like reversal) that points back to the original.
- Variation: full or partial amounts, and a random delay of days after the original.
- Result: enables net-versus-gross metrics and rate metrics.

### Paired records that must net to zero
- Each business event produced two lines with opposite directions and equal amounts, so every event balances.
- Failed events produced no lines at all. This makes balance checks meaningful.

### Rollups with different schedules
- Aggregate records into periodic summaries per entity, where the schedule depends on an attribute (daily, weekly, monthly).
- Higher-risk entities got a held-back share (a reserve) and a longer payout delay.
- A small share of rollups were marked failed, and the still-open period was marked pending.
- Check that rollup totals reconcile to the detail table.

### Deliberate mess
- Add a small share of exact duplicate rows (about 0.5%) and a small share of nulls in a non-critical column (about 0.3%) to the saved detail table only.
- Run validation on the clean data first, then inject the mess. This gives downstream data tests real problems to catch.
- Make it switchable with a flag.

## 4. Division of labor: Data Designer versus pandas

- **Data Designer:** good for independent random columns (categories with weights, uniform or Gaussian numbers, UUIDs, and LLM text if a model is configured).
- **pandas/numpy:** better for anything where one column depends on another, joins to reference tables, derived columns, time logic, pairing, and rollups.
- Using seed datasets or expression columns inside Data Designer can also do dependent logic, but I only verified the sampler and expression column types in the docs.

## 5. Validation checklist (adapt to your schema)

- Primary keys are unique in every table.
- Foreign keys all exist in their parent tables.
- No unexpected nulls (list the columns where null is allowed).
- Derived values match their source (for example, minor units equal decimal value times 100).
- Time ordering holds (end not earlier than start, nothing before its parent entity's start date).
- Paired records net to zero per event.
- Failed or excluded records do not appear where they should not.
- Child records (reversals) point to real parents.
- Rollup totals equal the detail totals they summarize.
- Make the function raise an error listing every problem found.

## 6. Reproducibility

- Use a seeded random generator for everything done in pandas/numpy, including UUID generation.
- Data Designer's own sampler columns were **not** tied to that seed, so runs differed. If exact repeatability matters, check whether Data Designer accepts a seed.
- Timestamps that depend on "today" shift between runs. Use a fixed end date if you need identical output.

## 7. Pitfalls and fixes

| Problem | Fix |
|---|---|
| Inventing a custom JSON schema for Data Designer | Data Designer has its own config format. Build with the Python builder, or export a sample config with `write_config()` to see the real structure. A method like `from_json` does not exist; the loader is `from_config`. |
| Independently sampling related columns (id, name, country, currency) | Keep reference entities as fixed rows and join to them. |
| Sampling an id with replacement for a table that should have one row per id | Build that table directly, do not sample it. |
| Globbing output folders to merge chunks | Use the result object's `load_dataset()` instead. Globbing mixed tables together and re-read earlier outputs on reruns. |
| Timestamped folder names with minute resolution | Include seconds, or two runs in the same minute share a folder. |
| Logger created but never configured | Call `logging.basicConfig` with a file handler and a console handler, after the log folder exists. |
| Tables generated in arbitrary file order | Generate tables in a fixed order that respects dependencies. |
| Generated data tracked by git | Add the output, log, artifact and virtual-environment folders to `.gitignore`. |
| Clean data makes tests and dashboards look trivial | Add skew, failures, time patterns and a little deliberate mess. |
| Mixed currencies | Keep the currency per entity and never sum across currencies without conversion. Zero-decimal currencies need special handling. |

## 8. API points that were not fully verified

Check these against the installed Data Designer version if an error appears:

- Whether `artifact_path` belongs on the `DataDesigner(...)` constructor or on `create(...)`.
- The exact parameter names for weighted categories and uniform ranges.
- Whether the config builder requires model configs or an API key even when no LLM columns are used.
- That the object returned by `create()` has `load_dataset()`.

## 9. Workflow that helped

- Start with a small preview (10 to 20 rows) before generating thousands.
- Write the validation function early.
- Test the pandas logic separately with stand-in data when the generation library is hard to run.
- Change one thing at a time and re-run validation.
- Keep a context file like this one, and update it when the script changes.

## 10. Instructions for the AI assistant reading this file

- Ask what the new project's data is for and what tables it needs before proposing a design.
- Apply the techniques above where they fit; do not copy them blindly.
- Verify Data Designer API usage against the official docs, and say when something is unverified.
- When given an error, explain the likely cause and give the exact fix.
- Keep changes small, explain them in plain language, and test the logic when possible.
