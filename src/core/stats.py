"""
Race-agnostic statistics module.

Works with any RaceConnector. Handles optional columns (dq, short_course, category)
gracefully — if they're all False/None, they have no effect on output.
"""

import argparse

import numpy as np
import pandas as pd

from core.connector import RaceConnector

HALF_MARATHON_DISTANCE_M = 21_082
METRES_PER_MILE = 1_609.344


def finishers(df: pd.DataFrame) -> pd.DataFrame:
    """Return true finishers: not DNF, not DQ, not short_course."""
    mask = ~df["dnf"].fillna(False).astype(bool)
    mask &= ~df["dq"].fillna(False).astype(bool)
    mask &= ~df["short_course"].fillna(False).astype(bool)
    return df[mask].copy()


def ms_to_hhmmss(ms: float) -> str:
    total_s = int(ms) // 1000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def pace_per_mile(chiptime_ms: float, distance_m: int) -> str:
    total_s = chiptime_ms / 1000
    sec_per_mile = total_s / (distance_m / METRES_PER_MILE)
    m, s = divmod(int(sec_per_mile), 60)
    return f"{m}:{s:02d}/mi"


def percentile_of_rank(rank: int, total: int) -> float:
    return (total - rank) / total * 100


# ── Print helpers ─────────────────────────────────────────────────────────────

def print_overall_stats(df: pd.DataFrame, fin: pd.DataFrame):
    total = len(df)
    n_fin = len(fin)
    n_dnf = df["dnf"].fillna(False).sum()
    n_dq  = df["dq"].fillna(False).sum()
    n_sc  = df["short_course"].fillna(False).sum()

    print("=" * 50)
    print("OVERALL")
    print("=" * 50)
    print(f"  Total starters  : {total:,}")
    print(f"  Finishers       : {n_fin:,} ({n_fin / total * 100:.1f}%)")
    print(f"  DNF             : {n_dnf:,} ({n_dnf / total * 100:.1f}%)")
    if n_dq:
        print(f"  DQ              : {n_dq:,}")
    if n_sc:
        print(f"  Short course    : {n_sc:,}")


def print_time_distribution(fin: pd.DataFrame):
    ms = fin["chiptime_ms"]
    percentiles = [10, 25, 50, 75, 90]

    print("\n" + "=" * 50)
    print("FINISH TIME DISTRIBUTION")
    print("=" * 50)
    print(f"  Fastest  : {ms_to_hhmmss(ms.min())}")
    print(f"  Slowest  : {ms_to_hhmmss(ms.max())}")
    for p in percentiles:
        print(f"  {p}th pct  : {ms_to_hhmmss(ms.quantile(p / 100))}")

    bucket_ms = 30 * 60 * 1000
    min_bucket = (ms.min() // bucket_ms) * bucket_ms
    max_bucket = (ms.max() // bucket_ms + 1) * bucket_ms
    bins = range(int(min_bucket), int(max_bucket) + 1, int(bucket_ms))
    labels = [ms_to_hhmmss(b) for b in list(bins)[:-1]]
    bucketed = pd.cut(ms, bins=list(bins), labels=labels, right=False)
    counts = bucketed.value_counts().sort_index()

    print("\n  30-minute buckets:")
    for label, count in counts.items():
        bar = "█" * (count // 50)
        print(f"    {label}  {count:>5,}  {bar}")


def print_gender_breakdown(fin: pd.DataFrame):
    print("\n" + "=" * 50)
    print("BY GENDER")
    print("=" * 50)
    for sex, grp in fin.groupby("sex"):
        ms = grp["chiptime_ms"]
        print(f"  {sex}  n={len(grp):,}  median={ms_to_hhmmss(ms.median())}  "
              f"fastest={ms_to_hhmmss(ms.min())}  slowest={ms_to_hhmmss(ms.max())}")


def print_age_group_breakdown(fin: pd.DataFrame):
    print("\n" + "=" * 50)
    print("BY AGE GROUP")
    print("=" * 50)
    for ag, grp in fin.groupby("age_group", observed=True):
        ms = grp["chiptime_ms"]
        print(f"  {ag:<7}  n={len(grp):>5,}  median={ms_to_hhmmss(ms.median())}  "
              f"fastest={ms_to_hhmmss(ms.min())}")


def print_pace_stats(fin: pd.DataFrame, distance_m: int):
    print("\n" + "=" * 50)
    print("PACE (min/mi)")
    print("=" * 50)
    for label, ms_val in [
        ("Fastest", fin["chiptime_ms"].min()),
        ("Median",  fin["chiptime_ms"].median()),
        ("Slowest", fin["chiptime_ms"].max()),
    ]:
        print(f"  {label:<8}: {pace_per_mile(ms_val, distance_m)}")


def print_runner_profile(df: pd.DataFrame, fin: pd.DataFrame, bib: str, distance_m: int):
    matches = df[df["bib"].astype(str) == bib]
    if matches.empty:
        print(f"\nNo runner found with bib {bib}.")
        return

    r = matches.iloc[0]
    print("\n" + "=" * 50)
    print(f"RUNNER PROFILE — BIB {bib}")
    print("=" * 50)

    full_name = r.get("full_name") or f"{r.get('firstname', '')} {r.get('lastname', '')}".strip()
    print(f"  Name     : {full_name}")
    print(f"  Age      : {r['age']}  |  Sex: {r['sex']}  |  Age group: {r['age_group']}")

    location = ", ".join(filter(None, [str(r.get("city") or ""), str(r.get("state") or "")]))
    if location:
        print(f"  Location : {location}")

    if r["dnf"]:
        print("  Status   : DNF")
        return
    if r.get("dq"):
        print("  Status   : DQ")
        return

    n_total   = len(fin)
    same_sex  = fin[fin["sex"] == r["sex"]]
    median_ms = fin["chiptime_ms"].median()
    delta_ms  = r["chiptime_ms"] - median_ms
    sign      = "+" if delta_ms >= 0 else "-"
    delta_str = f"{sign}{ms_to_hhmmss(abs(delta_ms))} vs median"

    print(f"\n  Finish time : {r['chiptime']}")
    print(f"  Pace        : {pace_per_mile(r['chiptime_ms'], distance_m)}")
    print(f"  vs median   : {delta_str}")

    overall_rank = r.get("overall")
    sex_rank     = r.get("oversex")
    div_rank     = r.get("overdiv")

    if pd.notna(overall_rank):
        pct = percentile_of_rank(int(overall_rank), n_total)
        print(f"\n  Overall     : {int(overall_rank):,} / {n_total:,}  ({pct:.1f}th percentile)")
    if pd.notna(sex_rank):
        sex_pct = percentile_of_rank(int(sex_rank), len(same_sex))
        print(f"  {r['sex']} rank    : {int(sex_rank):,} / {len(same_sex):,}  ({sex_pct:.1f}th percentile)")
    if pd.notna(div_rank):
        print(f"  Div rank    : {int(div_rank)}")


# ── Entry point ───────────────────────────────────────────────────────────────

def run_stats(connector: RaceConnector, bib: str | None = None):
    df  = connector.load_results()
    fin = finishers(df)

    print_overall_stats(df, fin)
    print_time_distribution(fin)
    print_gender_breakdown(fin)
    print_age_group_breakdown(fin)
    print_pace_stats(fin, connector.distance_m)

    if bib:
        print_runner_profile(df, fin, bib, connector.distance_m)
