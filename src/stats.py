import argparse
import pandas as pd
from pathlib import Path

INPUT_PATH = Path("data/results.csv")

MARATHON_DISTANCE_M = 42_195
AGE_GROUP_BINS   = [0,  18, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 200]
AGE_GROUP_LABELS = ["<18","18-24","25-29","30-34","35-39","40-44","45-49",
                    "50-54","55-59","60-64","65-69","70-74","75-79","80+"]


ADAPTIVE_CATEGORIES = {"Wheelchair", "Handcycle"}


def load_data() -> pd.DataFrame:
    df = pd.read_csv(INPUT_PATH)
    df["age_group"] = pd.cut(df["age"], bins=AGE_GROUP_BINS, labels=AGE_GROUP_LABELS, right=False)
    return df


def finishers(df: pd.DataFrame) -> pd.DataFrame:
    return df[
        ~df["dnf"] & ~df["dq"] & ~df["short_course"] &
        ~df["category"].isin(ADAPTIVE_CATEGORIES)
    ].copy()


def ms_to_hhmmss(ms: float) -> str:
    total_s = int(ms // 1000)
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def pace_per_mile(chiptime_ms: float) -> str:
    total_s = chiptime_ms / 1000
    sec_per_mile = total_s / (MARATHON_DISTANCE_M / 1609)
    m, s = divmod(int(sec_per_mile), 60)
    return f"{m}:{s:02d}/mi"


def percentile_of_rank(rank: int, total: int) -> float:
    """Percentile: what fraction of the field this runner beat."""
    return (total - rank) / total * 100


def print_overall_stats(df: pd.DataFrame, fin: pd.DataFrame):
    total = len(df)
    n_fin = len(fin)
    n_dnf = df["dnf"].sum()
    n_dq  = df["dq"].sum()
    n_sc  = df["short_course"].sum()
    n_wc  = df["category"].isin(ADAPTIVE_CATEGORIES).sum()

    print("=" * 50)
    print("OVERALL")
    print("=" * 50)
    print(f"  Total starters  : {total:,}")
    print(f"  Finishers       : {n_fin:,} ({n_fin/total*100:.1f}%)")
    print(f"  Short course    : {n_sc:,} ({n_sc/total*100:.1f}%)")
    print(f"  Wheelchair/HC   : {n_wc:,} ({n_wc/total*100:.1f}%)")
    print(f"  DNF             : {n_dnf:,} ({n_dnf/total*100:.1f}%)")
    print(f"  DQ              : {n_dq:,} ({n_dq/total*100:.1f}%)")


def print_time_distribution(fin: pd.DataFrame):
    ms = fin["chiptime_ms"]
    percentiles = [10, 25, 50, 75, 90]

    print("\n" + "=" * 50)
    print("FINISH TIME DISTRIBUTION")
    print("=" * 50)
    print(f"  Fastest  : {ms_to_hhmmss(ms.min())}")
    print(f"  Slowest  : {ms_to_hhmmss(ms.max())}")
    for p in percentiles:
        print(f"  {p}th pct  : {ms_to_hhmmss(ms.quantile(p/100))}")

    # 30-minute buckets
    bucket_ms = 30 * 60 * 1000
    min_bucket = (ms.min() // bucket_ms) * bucket_ms
    max_bucket = (ms.max() // bucket_ms + 1) * bucket_ms
    bins = range(int(min_bucket), int(max_bucket) + 1, int(bucket_ms))
    labels = [ms_to_hhmmss(b) for b in bins[:-1]]
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


def print_pace_stats(fin: pd.DataFrame):
    print("\n" + "=" * 50)
    print("PACE (min/mi)")
    print("=" * 50)
    for label, ms_val in [("Fastest", fin["chiptime_ms"].min()),
                           ("Median",  fin["chiptime_ms"].median()),
                           ("Slowest", fin["chiptime_ms"].max())]:
        print(f"  {label:<8}: {pace_per_mile(ms_val)}")


def print_runner_profile(df: pd.DataFrame, fin: pd.DataFrame, bib: str):
    matches = df[df["bib"].astype(str) == bib]
    if matches.empty:
        print(f"\nNo runner found with bib {bib}.")
        return

    r = matches.iloc[0]
    print("\n" + "=" * 50)
    print(f"RUNNER PROFILE — BIB {bib}")
    print("=" * 50)
    print(f"  Name     : {r['firstname'].strip()} {r['lastname'].strip()}")
    print(f"  Age      : {r['age']}  |  Sex: {r['sex']}  |  Age group: {r['age_group']}")
    location = f"{r['city']}, {r['state']}".strip(", ")
    if location:
        print(f"  Location : {location}")

    if r["category"] in ADAPTIVE_CATEGORIES:
        print(f"  Status   : {r['category'].upper()}")
        return
    if r["dq"]:
        print("  Status   : DISQUALIFIED")
        return
    if r["dnf"]:
        print("  Status   : DNF")
        return
    if r["short_course"]:
        print("  Status   : SHORT COURSE FINISHER")
        return

    n_total = len(fin)
    same_sex = fin[fin["sex"] == r["sex"]]
    same_ag  = fin[(fin["sex"] == r["sex"]) & (fin["age_group"] == r["age_group"])]

    overall_pct = percentile_of_rank(r["overall"], n_total)
    sex_pct     = percentile_of_rank(r["oversex"], len(same_sex))
    ag_pct      = percentile_of_rank(r["overdiv"], len(same_ag))

    median_ms   = fin["chiptime_ms"].median()
    delta_ms    = r["chiptime_ms"] - median_ms
    delta_sign  = "+" if delta_ms >= 0 else "-"
    delta_str   = f"{delta_sign}{ms_to_hhmmss(abs(delta_ms))} vs median"

    print(f"\n  Finish time : {r['chiptime']}")
    print(f"  Pace        : {pace_per_mile(r['chiptime_ms'])}")
    print(f"  vs median   : {delta_str}")
    print(f"\n  Overall     : {r['overall']:,} / {n_total:,}  ({overall_pct:.1f}th percentile)")
    print(f"  {r['sex']} rank    : {r['oversex']:,} / {len(same_sex):,}  ({sex_pct:.1f}th percentile)")
    print(f"  {r['age_group']} rank : {r['overdiv']:,} / {len(same_ag):,}  ({ag_pct:.1f}th percentile)")


def main():
    parser = argparse.ArgumentParser(description="LA Marathon 2026 statistics")
    parser.add_argument("--bib", type=str, help="Show profile for a specific bib number")
    args = parser.parse_args()

    df  = load_data()
    fin = finishers(df)

    print_overall_stats(df, fin)
    print_time_distribution(fin)
    print_gender_breakdown(fin)
    print_age_group_breakdown(fin)
    print_pace_stats(fin)

    if args.bib:
        print_runner_profile(df, fin, args.bib)


if __name__ == "__main__":
    main()
