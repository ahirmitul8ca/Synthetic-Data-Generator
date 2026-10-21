"""
generators/payflow_ledger.py   (run with: python run.py payflow_ledger)

Generates five related synthetic tables for a payments platform:
  1. accounts     - chart of accounts (account_type, normal_balance)
  2. merchants    - merchant list (onboarded_at, risk_tier, currency)
  3. payment_intents - every payment attempt, INCLUDING failed ones (failure_reason)
  4. ledger       - double-entry lines for payments that posted, plus refunds, optional messy rows
  5. settlements  - merchant payouts on a risk-based schedule, built from the clean ledger

Reference tables are defined in code so ids, names, countries and currencies
always match. NeMo Data Designer generates the random columns of each payment
intent; pandas/numpy then add the business rules (timestamps, currency from
merchant, amount_cents derived from amount, one debit + one credit per entry).

SEED drives everything done in pandas/numpy. The four Data Designer columns
(merchant, amount, status, gateway) are not tied to it, so they can differ between runs.
"""
import logging
import random

import numpy as np
import pandas as pd
import data_designer.config as dd
from data_designer.interface import DataDesigner

from File_Manager import (
    create_parquet_timestamped_dir,
    ensure_directories,
    get_latest_dir,
)
from helpers import new_uuid, raise_if_problems, random_timestamps, save_table, setup_logging

DATASET_NAME = "payflow_ledger"
logger = logging.getLogger(DATASET_NAME)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
SEED = 42
TARGET_PAYMENT_INTENTS = 27_000     # all payment attempts, failed included (non-failed become 2 ledger lines each)
HISTORY_DAYS = 365                  # how far back the data goes
REFUND_RATE = 0.03                  # share of succeeded payments that get a refund
FEE_RATE = 0.029                    # platform fee taken in each settlement

# Settlement schedule by merchant risk_tier, plus reserve and payout lag per schedule
SETTLEMENT_SCHEDULE = {"LOW": "daily", "MEDIUM": "weekly", "HIGH": "monthly"}
RESERVE_RATE = {"daily": 0.0, "weekly": 0.0, "monthly": 0.10}   # share of net held back
PAYOUT_LAG_DAYS = {"daily": 1, "weekly": 2, "monthly": 5}       # settlement_date -> paid_at
INJECT_ISSUES = True                # add duplicates / null gateways to the ledger
DUPLICATE_RATE = 0.005
NULL_GATEWAY_RATE = 0.003

END_DATE = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
START_DATE = END_DATE - pd.Timedelta(days=HISTORY_DAYS)

# ---------------------------------------------------------------------------
# Reference data (edit these to change the world being simulated)
# ---------------------------------------------------------------------------
ACCOUNTS = [
    # account_id,     name,                                   type,        normal,   currency, balance
    ("ACT-ROOT-001", "Main Operating Checking Account",       "asset",     "DEBIT",  "USD", 154320.50),
    ("ACT-CLR-002",  "Gateway Clearing Settlement Account",   "asset",     "DEBIT",  "USD", 89400.12),
    ("ACT-REC-003",  "Merchant Accounts Receivable",          "asset",     "DEBIT",  "USD", 1250000.00),
    ("ACT-FEE-004",  "Platform Service Fee Account",          "revenue",   "CREDIT", "USD", 45200.75),
    ("ACT-SET-005",  "Daily Settlement Holding Account",      "asset",     "DEBIT",  "USD", 300000.00),
    ("ACT-REV-006",  "Platform Commission & Markup Revenue",  "revenue",   "CREDIT", "USD", 12500.00),
    ("ACT-TAX-007",  "Tax Liability Withholding Account",     "liability", "CREDIT", "USD", 154320.50),
    ("ACT-RES-008",  "Merchant Rolling Reserve Account",      "liability", "CREDIT", "USD", 89400.12),
    ("ACT-REF-009",  "Customer Refund & Dispute Liability",   "liability", "CREDIT", "USD", 45200.75),
    ("ACT-BNK-010",  "External Merchant Bank Payout Account", "asset",     "DEBIT",  "USD", 300000.00),
]

MERCHANTS = [
    # merchant_id,   merchant_name,                      country, currency, risk,     industry,                     onboarded_at
    ("MCH-9921-US", "Acme Cloud Services Corp",          "US", "USD", "LOW",    "SaaS & Technology",          "2023-01-15"),
    ("MCH-4410-GB", "Global Office Supplies Inc",        "GB", "GBP", "LOW",    "Office Supplies",            "2023-03-02"),
    ("MCH-8832-CA", "Metro Utilities & Power",           "CA", "CAD", "MEDIUM", "Utilities & Infrastructure", "2023-06-20"),
    ("MCH-1109-AU", "Apex Legal & Accounting Partners",  "AU", "AUD", "LOW",    "Professional Services",      "2023-09-10"),
    ("MCH-5542-DE", "Prime Logistics & Freight",         "DE", "EUR", "MEDIUM", "Logistics & Freight",        "2023-11-05"),
    ("MCH-3318-FR", "Vanguard Tech Solutions",           "FR", "EUR", "LOW",    "SaaS & Technology",          "2024-01-18"),
    ("MCH-7790-JP", "Horizon Global Enterprise",         "JP", "JPY", "MEDIUM", "Professional Services",      "2024-03-25"),
    ("MCH-2245-SG", "Pacific Rim Holdings",              "SG", "SGD", "HIGH",   "Professional Services",      "2024-05-12"),
    ("MCH-6612-NL", "Nordic Digital Services",           "NL", "EUR", "LOW",    "SaaS & Technology",          "2024-07-30"),
    ("MCH-1184-SE", "Meridian Logistics Group",          "SE", "SEK", "MEDIUM", "Logistics & Freight",        "2024-09-14"),
    ("MCH-9933-BR", "Cordillera Trading Co",             "BR", "BRL", "HIGH",   "Office Supplies",            "2024-11-02"),
    ("MCH-4477-MX", "Aztec Financial Systems",           "MX", "MXN", "HIGH",   "Professional Services",      "2024-12-10"),
]

DESCRIPTIONS = {
    "SaaS & Technology": "SaaS cloud infrastructure software subscription renewal fee",
    "Office Supplies": "Office stationery, supplies, and equipment purchase ledger audit",
    "Utilities & Infrastructure": "Monthly office rent and utilities payment settlement record",
    "Professional Services": "Professional legal and corporate accounting consulting services",
    "Logistics & Freight": "Client invoice direct wire transfer multi-gateway routing entry",
}

GATEWAYS = [
    "Stripe-Gateway-Primary",
    "Razorpay-Gateway-Primary",
    "Adyen-Failover-Gateway",
    "CheckoutCom-Routing-Engine",
    "PayPal-Braintree-Gateway",
    "Worldpay-Global-Processor",
    "AuthorizeNet-Payment-Hub",
    "Mollie-European-Routing",
]

# Data Designer samples the non-failed statuses; failures are applied afterwards
# using per-gateway failure rates (see below), so failures depend on the gateway.
DD_STATUSES = ["succeeded", "pending", "requires_capture"]
DD_STATUS_WEIGHTS = [0.85, 0.10, 0.05]

# Chance that an attempt fails, by gateway. Mollie is the deliberately flaky one.
GATEWAY_FAILURE_RATE = {
    "Stripe-Gateway-Primary": 0.02,
    "Adyen-Failover-Gateway": 0.03,
    "Razorpay-Gateway-Primary": 0.04,
    "PayPal-Braintree-Gateway": 0.04,
    "CheckoutCom-Routing-Engine": 0.05,
    "Worldpay-Global-Processor": 0.06,
    "AuthorizeNet-Payment-Hub": 0.08,
    "Mollie-European-Routing": 0.12,
}
# Riskier merchants fail more often
RISK_FAILURE_MULTIPLIER = {"LOW": 0.8, "MEDIUM": 1.0, "HIGH": 1.6}

FAILURE_REASONS = ["card_declined", "insufficient_funds", "invalid_card", "gateway_timeout", "fraud_block"]
FAILURE_REASON_WEIGHTS = [0.40, 0.30, 0.12, 0.10, 0.08]
TIMEOUT_BOOST = {"Mollie-European-Routing": 4.0, "AuthorizeNet-Payment-Hub": 2.0}  # gateway_timeout x
FRAUD_BOOST = {"LOW": 0.5, "MEDIUM": 1.0, "HIGH": 3.0}                             # fraud_block x

# Placeholder posting rules: (debit account, credit account). Failed payments post nothing.
POSTING_RULES = {
    "succeeded":        ("ACT-CLR-002", "ACT-REC-003"),
    "pending":          ("ACT-SET-005", "ACT-CLR-002"),
    "requires_capture": ("ACT-RES-008", "ACT-CLR-002"),
}
REFUND_RULE = ("ACT-REF-009", "ACT-CLR-002")

PAYMENT_INTENT_COLUMNS = ["payment_intent_id", "merchant_id", "amount", "amount_cents", "currency",
                          "status", "failure_reason", "routed_to", "created_at", "posted_at"]

# Seconds between created_at and posted_at, by status: (min, max)
POSTING_DELAY = {
    "succeeded": (5, 600),
    "pending": (3_600, 3 * 86_400),
    "requires_capture": (3_600, 7 * 86_400),
    "failed": (1, 30),          # only used to fill the lookup; failed rows get no posted_at
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Table builders
# ---------------------------------------------------------------------------
def build_accounts() -> pd.DataFrame:
    df = pd.DataFrame(
        ACCOUNTS,
        columns=["account_id", "name", "account_type", "normal_balance", "currency", "balance"],
    )
    df.insert(1, "owner_id", "PLATFORM")
    return df


def build_merchants() -> pd.DataFrame:
    df = pd.DataFrame(
        MERCHANTS,
        columns=["merchant_id", "merchant_name", "country_code", "currency",
                 "risk_tier", "industry_category", "onboarded_at"],
    )
    df["onboarded_at"] = pd.to_datetime(df["onboarded_at"])
    return df


def generate_intents(n_intents: int, merchants: pd.DataFrame, artifact_dir) -> pd.DataFrame:
    """Use NeMo Data Designer for the random columns of each payment intent."""
    builder = dd.DataDesignerConfigBuilder()

    builder.add_column(dd.SamplerColumnConfig(
        name="merchant_id",
        sampler_type=dd.SamplerType.CATEGORY,
        params=dd.CategorySamplerParams(values=merchants["merchant_id"].tolist()),
    ))
    builder.add_column(dd.SamplerColumnConfig(
        name="amount",
        sampler_type=dd.SamplerType.UNIFORM,
        params=dd.UniformSamplerParams(low=10.0, high=5000.0),
    ))
    builder.add_column(dd.SamplerColumnConfig(
        name="status",
        sampler_type=dd.SamplerType.CATEGORY,
        params=dd.CategorySamplerParams(values=DD_STATUSES, weights=DD_STATUS_WEIGHTS),
    ))
    builder.add_column(dd.SamplerColumnConfig(
        name="routed_to",
        sampler_type=dd.SamplerType.CATEGORY,
        params=dd.CategorySamplerParams(values=GATEWAYS),
    ))

    designer = DataDesigner(artifact_path=str(artifact_dir))
    results = designer.create(builder, num_records=n_intents, dataset_name="ledger_intents")
    return results.load_dataset()


def pick_failure_reasons(failed: pd.DataFrame, rng: np.random.Generator) -> list:
    """Failure reason depends on the gateway (timeouts) and merchant risk (fraud blocks)."""
    base = np.array(FAILURE_REASON_WEIGHTS, dtype=float)
    reasons = []
    for gateway, risk in zip(failed["routed_to"], failed["risk_tier"]):
        w = base.copy()
        w[FAILURE_REASONS.index("gateway_timeout")] *= TIMEOUT_BOOST.get(gateway, 1.0)
        w[FAILURE_REASONS.index("fraud_block")] *= FRAUD_BOOST[risk]
        reasons.append(FAILURE_REASONS[rng.choice(len(w), p=w / w.sum())])
    return reasons


def build_payment_intents(intents: pd.DataFrame, merchants: pd.DataFrame,
                          rnd: random.Random, rng: np.random.Generator) -> pd.DataFrame:
    """One row per payment attempt, including failed ones."""
    df = intents.merge(
        merchants[["merchant_id", "currency", "industry_category", "risk_tier"]],
        on="merchant_id", how="left", validate="m:1",
    )
    df = df.head(TARGET_PAYMENT_INTENTS).reset_index(drop=True)
    if len(df) < TARGET_PAYMENT_INTENTS:
        raise RuntimeError(f"Data Designer returned {len(df)} rows, need {TARGET_PAYMENT_INTENTS}.")

    n = len(df)
    df["payment_intent_id"] = [new_uuid(rnd) for _ in range(n)]
    df["amount_cents"] = (df["amount"] * 100).round().astype("int64")
    df["amount"] = df["amount_cents"] / 100
    df["created_at"] = random_timestamps(n, rng, START_DATE, END_DATE).to_numpy()

    # Failures: depend on the gateway and on merchant risk tier
    fail_prob = (df["routed_to"].map(GATEWAY_FAILURE_RATE)
                 * df["risk_tier"].map(RISK_FAILURE_MULTIPLIER)).to_numpy()
    failed = rng.random(n) < fail_prob
    df.loc[failed, "status"] = "failed"
    df["failure_reason"] = None
    df.loc[failed, "failure_reason"] = pick_failure_reasons(df[failed], rng)

    # posted_at: when the payment posted to the ledger; failed attempts never post
    lo = df["status"].map(lambda s: POSTING_DELAY[s][0]).to_numpy()
    hi = df["status"].map(lambda s: POSTING_DELAY[s][1]).to_numpy()
    delay = rng.integers(lo, hi + 1)
    df["posted_at"] = (df["created_at"] + pd.to_timedelta(delay, unit="s")).where(~failed)
    logger.info("Built %d payment intents (%d failed, %.1f%%).", n, failed.sum(), 100 * failed.mean())
    return df


def build_entries(payment_intents: pd.DataFrame, rnd: random.Random,
                  rng: np.random.Generator) -> pd.DataFrame:
    """One row per payment or refund that posts to the ledger (failed intents are excluded)."""
    df = payment_intents[payment_intents["status"] != "failed"].copy().reset_index(drop=True)
    df["original_payment_intent_id"] = None
    df["entry_type"] = "payment"
    df["description"] = df["industry_category"].map(DESCRIPTIONS)
    df["debit_account"] = df["status"].map(lambda s: POSTING_RULES[s][0])
    df["credit_account"] = df["status"].map(lambda s: POSTING_RULES[s][1])
    n = len(df)

    # Refunds: a share of succeeded payments, full or partial, 1-30 days later
    refunds = df[df["status"] == "succeeded"].sample(frac=REFUND_RATE, random_state=SEED).copy()
    r = len(refunds)
    fraction = rng.uniform(0.2, 1.0, size=r)
    refunds["original_payment_intent_id"] = refunds["payment_intent_id"]
    refunds["payment_intent_id"] = [new_uuid(rnd) for _ in range(r)]
    refunds["entry_type"] = "refund"
    refunds["amount_cents"] = np.maximum((refunds["amount_cents"] * fraction).round(), 1).astype("int64")
    refunds["created_at"] = (
        refunds["posted_at"] + pd.to_timedelta(rng.integers(1, 31, size=r), unit="D")
    ).clip(upper=END_DATE + pd.Timedelta(days=1))
    refunds["posted_at"] = refunds["created_at"] + pd.to_timedelta(rng.integers(5, 601, size=r), unit="s")
    refunds["description"] = "Customer refund - " + refunds["description"]
    refunds["debit_account"], refunds["credit_account"] = REFUND_RULE

    entries = pd.concat([df, refunds], ignore_index=True)
    entries["amount"] = entries["amount_cents"] / 100      # amount always equals cents / 100
    logger.info("Built %d posted payments and %d refunds.", n, r)
    return entries


def build_ledger(entries: pd.DataFrame, rnd: random.Random) -> pd.DataFrame:
    """Split each entry into one DEBIT and one CREDIT line."""
    keep = ["payment_intent_id", "original_payment_intent_id", "entry_type", "merchant_id",
            "amount", "amount_cents", "currency", "status", "routed_to", "description",
            "created_at", "posted_at"]
    debit = entries[keep].assign(account_id=entries["debit_account"], direction="DEBIT")
    credit = entries[keep].assign(account_id=entries["credit_account"], direction="CREDIT")

    ledger = (
        pd.concat([debit, credit], ignore_index=True)
        .sort_values(["created_at", "payment_intent_id", "direction"], kind="stable")
        .reset_index(drop=True)
    )
    ledger.insert(0, "ledger_line_id", [new_uuid(rnd) for _ in range(len(ledger))])

    return ledger[["ledger_line_id", "payment_intent_id", "original_payment_intent_id",
                   "entry_type", "merchant_id", "account_id", "amount", "amount_cents",
                   "currency", "direction", "status", "routed_to", "description",
                   "created_at", "posted_at"]]


def build_settlements(entries: pd.DataFrame, merchants: pd.DataFrame,
                      rnd: random.Random, rng: np.random.Generator) -> pd.DataFrame:
    """Payout schedule depends on merchant risk tier:
    LOW = daily, MEDIUM = weekly (Friday), HIGH = monthly with a rolling reserve held back."""
    ok = entries[entries["status"] == "succeeded"].copy()
    ok["risk_tier"] = ok["merchant_id"].map(merchants.set_index("merchant_id")["risk_tier"])
    ok["schedule"] = ok["risk_tier"].map(SETTLEMENT_SCHEDULE)

    posted = ok["posted_at"]
    daily = posted.dt.normalize()
    weekly = posted.dt.to_period("W-FRI").dt.end_time.dt.normalize()
    monthly = posted.dt.to_period("M").dt.end_time.dt.normalize()
    ok["settlement_date"] = daily.where(
        ok["schedule"] == "daily", weekly.where(ok["schedule"] == "weekly", monthly)
    ).clip(upper=END_DATE)          # the still-open period is dated today and marked pending

    ok["gross_cents"] = ok["amount_cents"].where(ok["entry_type"] == "payment", 0)
    ok["refund_cents"] = ok["amount_cents"].where(ok["entry_type"] == "refund", 0)

    s = (
        ok.groupby(["merchant_id", "currency", "schedule", "settlement_date"], as_index=False)
        [["gross_cents", "refund_cents"]].sum()
    )
    s["fee_cents"] = (s["gross_cents"] * FEE_RATE).round().astype("int64")
    s["net_cents"] = s["gross_cents"] - s["refund_cents"] - s["fee_cents"]
    s["reserve_cents"] = (
        s["net_cents"].clip(lower=0) * s["schedule"].map(RESERVE_RATE)
    ).round().astype("int64")
    s["payout_cents"] = s["net_cents"] - s["reserve_cents"]
    s["payout_account_id"] = "ACT-BNK-010"

    is_recent = s["settlement_date"] >= END_DATE - pd.Timedelta(days=3)
    failed = rng.random(len(s)) < 0.01
    s["status"] = np.where(is_recent, "pending", np.where(failed, "failed", "paid"))
    lag = pd.to_timedelta(s["schedule"].map(PAYOUT_LAG_DAYS), unit="D")
    s["paid_at"] = (s["settlement_date"] + lag).where(s["status"] == "paid")
    s.insert(0, "settlement_id", [new_uuid(rnd) for _ in range(len(s))])
    return s.sort_values(["settlement_date", "merchant_id"]).reset_index(drop=True)


def inject_issues(ledger: pd.DataFrame) -> pd.DataFrame:
    """Add realistic mess so downstream data tests have something to catch."""
    dupes = ledger.sample(frac=DUPLICATE_RATE, random_state=SEED)       # exact duplicates
    out = pd.concat([ledger, dupes], ignore_index=True)                 # arrive "late" at the end
    null_idx = out.sample(frac=NULL_GATEWAY_RATE, random_state=SEED + 1).index
    out.loc[null_idx, "routed_to"] = None
    logger.info("Injected %d duplicate rows and %d null routed_to values.", len(dupes), len(null_idx))
    return out


# ---------------------------------------------------------------------------
# Validation and output
# ---------------------------------------------------------------------------
def validate(accounts, merchants, payment_intents, ledger, settlements) -> None:
    """Runs on the CLEAN ledger, before any issues are injected."""
    problems = []

    if not accounts["account_id"].is_unique:
        problems.append("duplicate account_id in accounts")
    if not merchants["merchant_id"].is_unique:
        problems.append("duplicate merchant_id in merchants")
    if not payment_intents["payment_intent_id"].is_unique:
        problems.append("duplicate payment_intent_id in payment_intents")
    if not ledger["ledger_line_id"].is_unique:
        problems.append("duplicate ledger_line_id")
    if not ledger["merchant_id"].isin(merchants["merchant_id"]).all():
        problems.append("ledger has merchant_id missing from merchants")
    if not ledger["account_id"].isin(accounts["account_id"]).all():
        problems.append("ledger has account_id missing from accounts")
    if ledger.isna().drop(columns="original_payment_intent_id").any().any():
        problems.append("ledger contains unexpected nulls")
    if (ledger["amount_cents"] != (ledger["amount"] * 100).round().astype("int64")).any():
        problems.append("amount and amount_cents disagree")
    if (ledger["posted_at"] < ledger["created_at"]).any():
        problems.append("posted_at is earlier than created_at")

    # payment_intents <-> ledger consistency
    pi = payment_intents.set_index("payment_intent_id")
    pay_ids = ledger.loc[ledger["entry_type"] == "payment", "payment_intent_id"].unique()
    if not pd.Index(pay_ids).isin(pi.index).all():
        problems.append("ledger payment missing from payment_intents")
    elif (pi.loc[pay_ids, "status"] == "failed").any():
        problems.append("failed payment intent found in the ledger")
    refund_orig = ledger.loc[ledger["entry_type"] == "refund", "original_payment_intent_id"].dropna()
    if not refund_orig.isin(pi.index).all():
        problems.append("refund points to an unknown payment intent")
    failed = payment_intents["status"] == "failed"
    if payment_intents.loc[failed, "failure_reason"].isna().any() or \
            payment_intents.loc[~failed, "failure_reason"].notna().any():
        problems.append("failure_reason must be set only on failed intents")

    onboarded = ledger["merchant_id"].map(merchants.set_index("merchant_id")["onboarded_at"])
    if (ledger["created_at"] < onboarded).any():
        problems.append("ledger rows exist before the merchant was onboarded")

    signed = ledger["amount_cents"].where(ledger["direction"] == "DEBIT", -ledger["amount_cents"])
    unbalanced = signed.groupby(ledger["payment_intent_id"]).sum()
    if (unbalanced != 0).any():
        problems.append(f"{int((unbalanced != 0).sum())} entries do not balance")

    ledger_gross = ledger.loc[
        (ledger["entry_type"] == "payment") & (ledger["status"] == "succeeded")
        & (ledger["direction"] == "DEBIT"), "amount_cents"].sum()
    if ledger_gross != settlements["gross_cents"].sum():
        problems.append("settlement gross does not match succeeded payments in the ledger")

    raise_if_problems(problems)
    logger.info("Validation passed (%d intents, %d ledger lines, %d settlements).",
                len(payment_intents), len(ledger), len(settlements))


def main() -> None:
    ensure_directories()
    setup_logging(DATASET_NAME)

    run_dir = create_parquet_timestamped_dir(DATASET_NAME)
    latest_dir = get_latest_dir(DATASET_NAME)
    logger.info("Output folder: %s", run_dir)

    rnd = random.Random(SEED)
    rng = np.random.default_rng(SEED)

    # Order matters: reference tables first, then ledger, then settlements.
    accounts = build_accounts()
    merchants = build_merchants()

    logger.info("Generating %d payment attempts with Data Designer...", TARGET_PAYMENT_INTENTS)
    intents = generate_intents(TARGET_PAYMENT_INTENTS, merchants, run_dir / "dd_artifacts")

    payment_intents = build_payment_intents(intents, merchants, rnd, rng)
    entries = build_entries(payment_intents, rnd, rng)
    ledger = build_ledger(entries, rnd)
    settlements = build_settlements(entries, merchants, rnd, rng)
    validate(accounts, merchants, payment_intents, ledger, settlements)

    if INJECT_ISSUES:
        ledger = inject_issues(ledger)

    save_table(accounts, "accounts", run_dir, latest_dir)
    save_table(merchants, "merchants", run_dir, latest_dir)
    save_table(payment_intents[PAYMENT_INTENT_COLUMNS], "payment_intents", run_dir, latest_dir)
    save_table(ledger, "ledger", run_dir, latest_dir)
    save_table(settlements, "settlements", run_dir, latest_dir)
    logger.info("Done.")


if __name__ == "__main__":
    main()
