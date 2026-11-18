#!/usr/bin/env python3
"""
Synthetic data generator for the Customer Churn & Revenue Intelligence Engine.

Produces the 5 raw (bronze) tables from the PRD:
    raw_customers, raw_subscriptions, raw_invoices, raw_product_events, raw_support_tickets
plus ground_truth_customers (answer key to validate your dbt marts against).

Design: a month-by-month billing simulation per customer drives everything else,
so the tables are mutually consistent (events decay before voluntary churn,
involuntary churn emerges from failed dunning cycles, tickets spike before churn, etc.).

Money columns are integer CENTS (your staging layer converts to decimals).
Every table has `_ingested_at`; invoices/events/tickets contain ~0.5-1% duplicate
webhook rows so your stg_ models have something to deduplicate.

Run:  python generators/churn_engine.py   (or: python run.py churn_engine)
Tune the RUN SETTINGS below.
"""
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# allow running this file directly: python generators/churn_engine.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import numpy as np
import pandas as pd

from File_Manager import create_parquet_timestamped_dir, get_latest_dir
from helpers import raise_if_problems, save_table, setup_logging

# --------------------------------------------------------------------------- #
# RUN SETTINGS
# --------------------------------------------------------------------------- #
N_CUSTOMERS = 5000
SEED = 42
DIRTY_RATE = 0.02        # fraction of rows corrupted with data-quality issues (0 = clean)
ADD_DUPLICATES = True    # duplicate webhook rows for invoices / events / tickets
OUTPUT_NAME = "churn_engine"

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
AS_OF = datetime(2026, 10, 31, 23, 59, 59)          # "today" inside the dataset
SIGNUP_START = datetime(2024, 1, 1)
SIGNUP_END = datetime(2026, 9, 30)
WEEK = 7 * 86400

PLANS = ["basic", "pro", "enterprise"]
PRICE_PER_SEAT = {"basic": 15, "pro": 49, "enterprise": 149}   # USD / month
SEAT_RANGE = {"1-10": (1, 2), "11-50": (1, 4), "51-200": (3, 8),
              "201-1000": (5, 15), "1000+": (10, 25)}
INIT_PLAN_P = {"1-10": [.70, .28, .02], "11-50": [.40, .50, .10],
               "51-200": [.15, .55, .30], "201-1000": [.05, .40, .55],
               "1000+": [.00, .20, .80]}

COUNTRIES = ["CA", "US", "GB", "DE", "AU", "IN", "FR", "NL", "BR", "SG"]
COUNTRY_P = [.18, .34, .10, .08, .07, .07, .05, .04, .04, .03]
CHANNELS = ["organic_search", "paid_search", "paid_social", "referral",
            "partner", "outbound_sales", "content_marketing"]
CHANNEL_P = [.22, .18, .14, .12, .08, .10, .16]
SIZES = ["1-10", "11-50", "51-200", "201-1000", "1000+"]
SIZE_P = [.38, .30, .18, .10, .04]
SIZE_P_ENTERPRISE_CH = [.10, .20, .30, .25, .15]     # outbound/partner skew larger

# churn drivers (multipliers on the base monthly voluntary hazard)
BASE_VOL = 0.026
CH_MULT = {"organic_search": .8, "paid_search": 1.2, "paid_social": 1.5, "referral": .6,
           "partner": .7, "outbound_sales": .9, "content_marketing": .9}
SIZE_MULT = {"1-10": 1.5, "11-50": 1.1, "51-200": .9, "201-1000": .7, "1000+": .5}
PLAN_MULT = {"basic": 1.4, "pro": 1.0, "enterprise": .6}
TENURE_MULT = {0: 2.2, 1: 1.8, 2: 1.4, 11: 2.8, 12: 1.5}   # onboarding drop-off + annual renewal spike

P_UP, P_DOWN, P_SEAT_UP, P_SEAT_DOWN = 0.022, 0.010, 0.030, 0.012
P_FAIL = {"basic": .08, "pro": .05, "enterprise": .025}     # first-attempt card failure
RETRY_SUCCESS = (0.45, 0.40, 0.30)                          # attempts 2, 3, 4

VOL_REASONS = ["too_expensive", "missing_features", "switched_to_competitor",
               "low_usage", "poor_support", "business_closed"]
VOL_REASON_P = [.25, .20, .20, .18, .10, .07]

EVENT_NAMES = ["login", "dashboard_view", "report_created", "report_shared",
               "export_data", "invite_user", "integration_connected", "api_call"]
EVENT_P = [.28, .25, .12, .06, .07, .03, .02, .17]
USAGE_SIZE_MULT = {"1-10": .7, "11-50": 1.0, "51-200": 1.5, "201-1000": 2.2, "1000+": 3.2}
TICKET_SIZE_MULT = {"1-10": .7, "11-50": 1.0, "51-200": 1.3, "201-1000": 1.7, "1000+": 2.2}
DECAY = np.array([0.12, 0.30, 0.55, 0.80])                  # index = weeks before end (0 = last week)

PRIORITIES = ["low", "medium", "high", "urgent"]
PRIORITY_P = [.35, .40, .20, .05]
PRIORITY_MEDIAN_HRS = {"low": 48, "medium": 24, "high": 10, "urgent": 4}


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #
def build_customers(rng: np.random.Generator, n: int) -> pd.DataFrame:
    months = pd.date_range(SIGNUP_START, SIGNUP_END, freq="MS")
    w = np.linspace(1, 3, len(months))                      # growing signup volume
    w /= w.sum()
    m_idx = rng.choice(len(months), n, p=w)
    signup = (months[m_idx]
              + pd.to_timedelta(rng.integers(0, 28, n), "D")
              + pd.to_timedelta(rng.integers(0, 86400, n), "s"))
    channel = rng.choice(CHANNELS, n, p=CHANNEL_P)
    size = np.empty(n, dtype=object)
    big = np.isin(channel, ["outbound_sales", "partner"])
    size[big] = rng.choice(SIZES, big.sum(), p=SIZE_P_ENTERPRISE_CH)
    size[~big] = rng.choice(SIZES, (~big).sum(), p=SIZE_P)
    df = pd.DataFrame({
        "customer_id": [f"cus_{i:06d}" for i in range(1, n + 1)],
        "signup_ts": signup,
        "country": rng.choice(COUNTRIES, n, p=COUNTRY_P),
        "acquisition_channel": channel,
        "company_size": size,
    })
    return df.sort_values("signup_ts").reset_index(drop=True).assign(
        customer_id=lambda d: [f"cus_{i:06d}" for i in range(1, len(d) + 1)])


# --------------------------------------------------------------------------- #
# Subscription / billing simulation (the engine that drives everything)
# --------------------------------------------------------------------------- #
def add_months(dt0: datetime, k: int, anchor: int) -> datetime:
    y = dt0.year + (dt0.month - 1 + k) // 12
    mo = (dt0.month - 1 + k) % 12 + 1
    return dt0.replace(year=y, month=mo, day=anchor)


def dunning(r: random.Random, plan: str, allow_fail: bool):
    if r.random() >= P_FAIL[plan]:
        return 1, "paid"
    for attempt, p in zip((2, 3, 4), RETRY_SUCCESS):
        if r.random() < p:
            return attempt, "paid"
    return (4, "failed") if allow_fail else (3, "paid")


def simulate_customer(c: dict, r: random.Random, counter: list):
    signup = c["signup_ts"].to_pydatetime()
    anchor = min(signup.day, 28)
    plan, seats = c["plan"], c["seats"]
    segs, invs, seg = [], [], None
    out = {"canceled_at": None, "churn_type": None, "reason": None}
    m = 0
    while True:
        cs = signup if m == 0 else add_months(signup, m, anchor)
        if cs > AS_OF:
            break
        new_seg = m == 0
        if m > 0:                                            # plan / seat changes at cycle start
            u = r.random()
            np_, ns = plan, seats
            if u < P_UP:
                if plan != "enterprise":
                    np_ = PLANS[PLANS.index(plan) + 1]
            elif u < P_UP + P_DOWN:
                if plan != "basic":
                    np_ = PLANS[PLANS.index(plan) - 1]
            elif u < P_UP + P_DOWN + P_SEAT_UP:
                ns = min(40, seats + r.randint(1, 3))
            elif u < P_UP + P_DOWN + P_SEAT_UP + P_SEAT_DOWN:
                ns = max(1, seats - r.randint(1, 2))
            if (np_, ns) != (plan, seats):
                seg["ended_at"], seg["status"] = cs, "Replaced"
                plan, seats, new_seg = np_, ns, True
        if new_seg:
            counter[0] += 1
            seg = {"subscription_id": f"sub_{counter[0]:07d}", "customer_id": c["customer_id"],
                   "plan_tier": plan.title(), "mrr_amount": PRICE_PER_SEAT[plan] * seats * 100,
                   "status": "Active", "started_at": cs, "ended_at": None,
                   "canceled_at": None, "cancellation_reason": None}
            segs.append(seg)

        allow_fail = cs + timedelta(days=14) <= AS_OF
        attempts, status = dunning(r, plan, allow_fail)
        invs.append({"customer_id": c["customer_id"], "subscription_id": seg["subscription_id"],
                     "amount_due": seg["mrr_amount"], "status": status,
                     "attempt_count": attempts, "invoice_date": cs.date()})

        canceled_at = None
        if status == "failed":                               # dunning exhausted -> involuntary churn
            canceled_at = cs + timedelta(days=14, hours=r.randint(0, 20))
            out.update(churn_type="involuntary", reason="payment_failed")
        else:
            hz = (BASE_VOL * TENURE_MULT.get(m, 1.0) * CH_MULT[c["acquisition_channel"]]
                  * SIZE_MULT[c["company_size"]] * PLAN_MULT[plan])
            if r.random() < min(hz, 0.5):
                ca = cs + timedelta(days=r.randint(2, 27), seconds=r.randint(0, 86399))
                if ca <= AS_OF:
                    canceled_at = ca
                    out.update(churn_type="voluntary",
                               reason=r.choices(VOL_REASONS, VOL_REASON_P)[0])
        if canceled_at:
            seg.update(status="Canceled", canceled_at=canceled_at, ended_at=canceled_at,
                       cancellation_reason=out["reason"])
            out["canceled_at"] = canceled_at
            break
        m += 1
    return segs, invs, out


# --------------------------------------------------------------------------- #
# Events + tickets from a shared customer-week grid
# --------------------------------------------------------------------------- #
def build_week_grid(cust: pd.DataFrame):
    signup_s = cust["signup_ts"].dt.as_unit("s").astype("int64").to_numpy()
    end_s = cust["end_ts"].dt.as_unit("s").astype("int64").to_numpy()
    n_weeks = np.ceil((end_s - signup_s) / WEEK).astype(int).clip(min=1)
    idx = np.repeat(np.arange(len(cust)), n_weeks)
    k = np.arange(n_weeks.sum()) - np.repeat(np.cumsum(n_weeks) - n_weeks, n_weeks)
    wte = n_weeks[idx] - 1 - k                                # weeks to end (0 = final week)
    w_start = signup_s[idx] + k * WEEK
    w_end = np.minimum(w_start + WEEK, end_s[idx])
    return idx, k, wte, w_start, w_end


def build_events(rng, cust, grid):
    idx, k, wte, w_start, w_end = grid
    lam = 7.0 * cust["usage_scale"].to_numpy()[idx]
    lam = lam * np.where(k == 0, 1.3, np.where(k == 1, 1.15, 1.0))
    lam = lam * (w_end - w_start) / WEEK                      # partial weeks
    decaying = cust["decaying"].to_numpy()[idx] & (wte < 4)
    f = DECAY[np.clip(wte, 0, 3)]
    f = np.where(cust["at_risk"].to_numpy()[idx], f ** 0.6, f)  # at-risk actives decay a bit less
    lam = np.where(decaying, lam * f, lam)
    counts = rng.poisson(lam)
    rep = np.repeat(np.arange(len(counts)), counts)
    ts = w_start[rep] + (rng.random(len(rep)) * (w_end[rep] - w_start[rep])).astype("int64")
    ev = pd.DataFrame({
        "customer_id": cust["customer_id"].to_numpy()[idx[rep]],
        "event_name": rng.choice(EVENT_NAMES, len(rep), p=EVENT_P),
        "event_timestamp": pd.to_datetime(ts, unit="s"),
    })
    ev = ev.sort_values("event_timestamp").reset_index(drop=True)
    ev.insert(0, "event_id", [f"evt_{i:09d}" for i in range(1, len(ev) + 1)])
    ev["_ingested_at"] = ev["event_timestamp"] + pd.to_timedelta(rng.integers(1, 300, len(ev)), "s")
    return ev


def build_tickets(rng, cust, grid):
    idx, k, wte, w_start, w_end = grid
    lam = 0.06 * cust["ticket_scale"].to_numpy()[idx] * (w_end - w_start) / WEEK
    friction = cust["decaying"].to_numpy()[idx] & (wte < 8)
    lam = np.where(friction, lam * 4, lam)
    counts = rng.poisson(lam)
    rep = np.repeat(np.arange(len(counts)), counts)
    created = w_start[rep] + (rng.random(len(rep)) * (w_end[rep] - w_start[rep])).astype("int64")
    n = len(rep)
    prio = rng.choice(PRIORITIES, n, p=PRIORITY_P)
    med = np.array([PRIORITY_MEDIAN_HRS[p] for p in prio], dtype=float)
    slow = np.where(friction[rep], 2.5, 1.0)
    hours = rng.lognormal(np.log(med * slow), 0.8)
    resolved = created + (hours * 3600).astype("int64")
    unresolved = rng.random(n) < np.where(friction[rep], 0.25, 0.03)
    as_of_s = int(pd.Timestamp(AS_OF).timestamp())
    open_mask = unresolved | (resolved > as_of_s)
    status = np.where(open_mask, rng.choice(["open", "pending"], n, p=[.7, .3]),
                      rng.choice(["resolved", "closed"], n, p=[.4, .6]))
    tk = pd.DataFrame({
        "customer_id": cust["customer_id"].to_numpy()[idx[rep]],
        "priority": prio, "status": status,
        "created_at": pd.to_datetime(created, unit="s"),
        "resolved_at": pd.to_datetime(np.where(open_mask, np.iinfo("int64").min // 10**9, resolved),
                                      unit="s", errors="coerce"),
    })
    tk.loc[open_mask, "resolved_at"] = pd.NaT
    tk = tk.sort_values("created_at").reset_index(drop=True)
    tk.insert(0, "ticket_id", [f"tkt_{i:07d}" for i in range(1, len(tk) + 1)])
    tk["_ingested_at"] = tk["created_at"] + pd.to_timedelta(rng.integers(1, 600, len(tk)), "s")
    return tk


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def add_duplicates(rng, df, frac, lag_max):
    """Simulate webhook retries: re-delivered rows with a later _ingested_at."""
    if frac <= 0 or df.empty:
        return df
    dup = df.sample(frac=frac, random_state=int(rng.integers(0, 2**31 - 1))).copy()
    dup["_ingested_at"] = dup["_ingested_at"] + pd.to_timedelta(rng.integers(5, lag_max, len(dup)), "s")
    return pd.concat([df, dup]).sort_values("_ingested_at").reset_index(drop=True)



def inject_dirty(rng, t, rate):
    """Inject realistic data-quality problems into the raw tables (ground truth stays clean)."""
    log = {}
    def idx(df, frac):
        return df.sample(frac=min(frac, 1.0), random_state=int(rng.integers(0, 2**31 - 1))).index
    def messy_case(series, ix):
        v = series.loc[ix].astype(str)
        mode = rng.integers(0, 3, len(v))
        return pd.Series(np.where(mode == 0, v.str.upper(), np.where(mode == 1, " " + v + " ", v.str.title())),
                         index=v.index)

    c = t["raw_customers"]
    ix = idx(c, rate);        c.loc[ix, "country"] = rng.choice(["usa", "United States", "UK", "can", None], len(ix)); log["customers.country variants/nulls"] = len(ix)
    ix = idx(c, rate);        c.loc[ix, "acquisition_channel"] = messy_case(c["acquisition_channel"], ix); log["customers.channel casing/whitespace"] = len(ix)
    ix = idx(c, rate / 2);    c.loc[ix, "company_size"] = None; log["customers.company_size null"] = len(ix)

    s_ = t["raw_subscriptions"]
    ix = idx(s_, rate);       s_.loc[ix, "status"] = messy_case(s_["status"], ix); log["subscriptions.status casing/whitespace"] = len(ix)
    ix = idx(s_, rate / 4);   s_.loc[ix, "mrr_amount"] = -s_.loc[ix, "mrr_amount"]; log["subscriptions.negative mrr"] = len(ix)
    cx = s_[s_["canceled_at"].notna()]
    ix = idx(cx, rate / 4);   s_.loc[ix, "canceled_at"] = s_.loc[ix, "started_at"] - pd.Timedelta(days=3); log["subscriptions.canceled_at before started_at"] = len(ix)

    i_ = t["raw_invoices"]
    i_["attempt_count"] = i_["attempt_count"].astype("Int64")
    ix = idx(i_, rate);       i_.loc[ix, "status"] = messy_case(i_["status"], ix); log["invoices.status casing/whitespace"] = len(ix)
    ix = idx(i_, rate / 2);   i_.loc[ix, "attempt_count"] = pd.NA; log["invoices.attempt_count null"] = len(ix)
    ix = idx(i_, rate / 4);   i_.loc[ix, "amount_due"] = 0; log["invoices.zero amount_due"] = len(ix)

    e = t["raw_product_events"]
    ix = idx(e, rate / 10);   e.loc[ix, "event_name"] = messy_case(e["event_name"], ix); log["events.event_name casing/whitespace"] = len(ix)
    ix = idx(e, rate / 40);   e.loc[ix, "customer_id"] = None; log["events.null customer_id"] = len(ix)
    ix = idx(e, rate / 40);   e.loc[ix, "customer_id"] = "cus_999999"; log["events.orphan customer_id"] = len(ix)
    ix = idx(e, rate / 100);  e.loc[ix, "event_timestamp"] = pd.Timestamp(AS_OF) + pd.Timedelta(days=45); log["events.future timestamp"] = len(ix)

    k = t["raw_support_tickets"]
    ix = idx(k, rate);        k.loc[ix, "priority"] = messy_case(k["priority"], ix); log["tickets.priority casing/whitespace"] = len(ix)
    rx = k[k["resolved_at"].notna()]
    ix = idx(rx, rate / 2);   k.loc[ix, "resolved_at"] = k.loc[ix, "created_at"] - pd.Timedelta(hours=5); log["tickets.resolved_at before created_at"] = len(ix)
    return log


def validate_clean(t):
    """Integrity checks on the CLEAN tables (before duplicates / dirty data are injected)."""
    c, s, i, e = t["raw_customers"], t["raw_subscriptions"], t["raw_invoices"], t["raw_product_events"]
    problems = []
    if (s["canceled_at"] < s["started_at"]).any():
        problems.append("subscriptions canceled before started")
    if s[s["status"] == "Active"]["customer_id"].duplicated().any():
        problems.append("customer with more than one active subscription")
    if not s["customer_id"].isin(c["customer_id"]).all():
        problems.append("subscriptions with unknown customer_id")
    if not i["subscription_id"].isin(s["subscription_id"]).all():
        problems.append("invoices with unknown subscription_id")
    if not e["customer_id"].isin(c["customer_id"]).all():
        problems.append("events with unknown customer_id")
    if (e["event_timestamp"] > pd.Timestamp(AS_OF)).any():
        problems.append("events after the as-of date")
    raise_if_problems(problems)


def main():
    log = setup_logging(OUTPUT_NAME)
    rng = np.random.default_rng(SEED)
    r = random.Random(SEED)
    run_dir = create_parquet_timestamped_dir(OUTPUT_NAME)
    latest_dir = get_latest_dir(OUTPUT_NAME)

    cust = build_customers(rng, N_CUSTOMERS)

    # customer-level latent attributes
    cust["plan"] = [r.choices(PLANS, INIT_PLAN_P[s])[0] for s in cust["company_size"]]
    cust["seats"] = [r.randint(*SEAT_RANGE[s]) for s in cust["company_size"]]
    cust["usage_scale"] = (rng.lognormal(0, 0.45, len(cust))
                           * cust["company_size"].map(USAGE_SIZE_MULT).to_numpy()
                           * cust["plan"].map({"basic": .8, "pro": 1.0, "enterprise": 1.3}).to_numpy())
    cust["ticket_scale"] = cust["company_size"].map(TICKET_SIZE_MULT).to_numpy()

    # billing simulation
    counter, subs, invs, outcomes = [0], [], [], []
    for c in cust.to_dict("records"):
        s, i, o = simulate_customer(c, r, counter)
        subs += s
        invs += i
        outcomes.append(o)
    oc = pd.DataFrame(outcomes)
    cust["canceled_at"] = pd.to_datetime(oc["canceled_at"])
    cust["churn_type"] = oc["churn_type"]
    cust["cancellation_reason"] = oc["reason"]
    cust["end_ts"] = cust["canceled_at"].fillna(pd.Timestamp(AS_OF))

    tenure_days = (cust["end_ts"] - cust["signup_ts"]).dt.days
    cust["at_risk"] = (cust["canceled_at"].isna() & (tenure_days > 60)
                       & (rng.random(len(cust)) < 0.10))
    cust["decaying"] = (cust["churn_type"] == "voluntary") | cust["at_risk"]
    grid = build_week_grid(cust)

    raw_customers = pd.DataFrame({
        "customer_id": cust["customer_id"],
        "signup_date": cust["signup_ts"].dt.date,
        "country": cust["country"],
        "acquisition_channel": cust["acquisition_channel"],
        "company_size": cust["company_size"],
        "_ingested_at": cust["signup_ts"],
    })
    raw_subscriptions = pd.DataFrame(subs)
    raw_subscriptions["_ingested_at"] = raw_subscriptions["started_at"]
    raw_subscriptions = raw_subscriptions[[
        "subscription_id", "customer_id", "plan_tier", "mrr_amount", "status",
        "started_at", "ended_at", "canceled_at", "cancellation_reason", "_ingested_at"]]

    raw_invoices = pd.DataFrame(invs).sort_values(["invoice_date", "customer_id"]).reset_index(drop=True)
    raw_invoices.insert(0, "invoice_id", [f"inv_{i:08d}" for i in range(1, len(raw_invoices) + 1)])
    raw_invoices["_ingested_at"] = (pd.to_datetime(raw_invoices["invoice_date"])
                                    + pd.to_timedelta(raw_invoices["attempt_count"] * 2, "D")
                                    + pd.to_timedelta(rng.integers(60, 3600, len(raw_invoices)), "s"))
    raw_invoices = raw_invoices[["invoice_id", "subscription_id", "customer_id", "amount_due", "status",
                                 "attempt_count", "invoice_date", "_ingested_at"]]

    truth = cust[["customer_id", "signup_ts", "canceled_at", "churn_type",
                  "cancellation_reason", "at_risk"]].rename(columns={"signup_ts": "signup_at"})
    tables = {"raw_customers": raw_customers, "raw_subscriptions": raw_subscriptions,
              "raw_invoices": raw_invoices, "raw_product_events": build_events(rng, cust, grid),
              "raw_support_tickets": build_tickets(rng, cust, grid)}

    validate_clean(tables)                       # fail fast on the clean data
    log.info("Clean-data validation passed")

    if ADD_DUPLICATES:
        tables["raw_invoices"] = add_duplicates(rng, tables["raw_invoices"], 0.01, 3600)
        tables["raw_product_events"] = add_duplicates(rng, tables["raw_product_events"], 0.004, 120)
        tables["raw_support_tickets"] = add_duplicates(rng, tables["raw_support_tickets"], 0.005, 600)
    if DIRTY_RATE > 0:
        for k_, v_ in inject_dirty(rng, tables, DIRTY_RATE).items():
            log.info("dirty: %-46s %8s", k_, f"{v_:,}")

    tables["ground_truth_customers"] = truth     # answer key stays clean
    for name, df in tables.items():
        save_table(df, name, run_dir, latest_dir)

    churned = truth["churn_type"].notna().sum()
    log.info("customers=%s churned=%s (%.1f%%) voluntary_share=%.1f%% at_risk=%s",
             f"{len(truth):,}", f"{churned:,}", 100 * churned / len(truth),
             100 * (truth["churn_type"] == "voluntary").sum() / max(churned, 1), int(truth["at_risk"].sum()))
    log.info("Output: %s (copied to %s)", run_dir, latest_dir)


if __name__ == "__main__":
    main()