import json
import pandas as pd
from pathlib import Path

CACHE_DIR = Path("data/pages")
EVENTCONFIG_PATH = Path("data/eventconfig.json")
OUTPUT_PATH = Path("data/results.csv")
SUBEVENT_ID = 6584

KEEP_COLUMNS = [
    "bib", "firstname", "lastname", "age", "sex",
    "city", "state", "country",
    "overall", "oversex", "overdiv",
    "chiptime_ms", "clocktime_ms", "chiptime", "clocktime",
    "dq", "dnf", "short_course", "category",
]


def load_records() -> list:
    page_files = sorted(p for p in CACHE_DIR.glob("*.json") if p.stem.isdigit())
    if not page_files:
        raise FileNotFoundError(f"No cached pages found in {CACHE_DIR}/. Run fetch.py first.")
    records = []
    for page_file in page_files:
        with open(page_file) as f:
            records.extend(json.load(f))
    return records


def load_split_labels() -> tuple[list[dict], int]:
    """Return splits for our subevent sorted by displayorder, and the finish distance ID."""
    if not EVENTCONFIG_PATH.exists():
        raise FileNotFoundError(f"{EVENTCONFIG_PATH} not found. Run fetch.py first.")
    with open(EVENTCONFIG_PATH) as f:
        config = json.load(f)
    subevent = config["schema"]["subevents"][str(SUBEVENT_ID)]
    finish_distance_id = subevent["finish_distance_id"]
    distances = subevent["legs"]["0"]["distances"]
    splits = [
        {"id": str(k), "label": v["label"], "distance_m": v["distance"], "displayorder": v["displayorder"]}
        for k, v in distances.items()
    ]
    return sorted(splits, key=lambda x: x["displayorder"]), finish_distance_id


def load_category_names() -> dict[int, str]:
    """Return a mapping of categoryId -> category name for our subevent."""
    with open(EVENTCONFIG_PATH) as f:
        config = json.load(f)
    categories = config["schema"]["subevents"][str(SUBEVENT_ID)]["categories"]
    return {int(cid): cat["name"] for cid, cat in categories.items() if cat.get("name")}


def ms_to_hhmmss(ms_series: pd.Series) -> pd.Series:
    result = pd.Series("", index=ms_series.index, dtype=str)
    mask = ms_series.notna()
    s = (ms_series[mask] // 1000).astype(int)
    hours = s // 3600
    minutes = (s % 3600) // 60
    seconds = s % 60
    result[mask] = hours.map(str) + ":" + minutes.map(lambda x: f"{x:02d}") + ":" + seconds.map(lambda x: f"{x:02d}")
    return result


def extract_splits(df: pd.DataFrame, split_labels: list[dict]) -> pd.DataFrame:
    """Add a delta_net column per split, named split_<LABEL>_ms."""
    for split in split_labels:
        col = f"split_{split['label']}_ms"
        df[col] = df["splits"].apply(
            lambda s, sid=split["id"]: s[sid]["delta_net"] if s and sid in s else None
        )
    return df


def main():
    split_labels, finish_distance_id = load_split_labels()
    print(f"Loaded {len(split_labels)} split labels: {[s['label'] for s in split_labels]}")

    category_names = load_category_names()

    records = load_records()
    df = pd.DataFrame(records)
    print(f"Loaded {len(df)} records from {CACHE_DIR}/")

    df = df.rename(columns={"chiptime": "chiptime_ms", "clocktime": "clocktime_ms"})
    df["chiptime"] = ms_to_hhmmss(df["chiptime_ms"])
    df["clocktime"] = ms_to_hhmmss(df["clocktime_ms"])

    df = extract_splits(df, split_labels)

    df["dnf"] = (df["distanceId"] != finish_distance_id) & ~df["dq"]
    df["category"] = df["categoryId"].map(category_names).fillna("Unknown")

    def _split_missing(col: str) -> pd.Series:
        return (df[col] == 0) | df[col].isna()

    df["short_course"] = (~df["dnf"] & ~df["dq"]) & (
        _split_missing("split_30K_ms") &
        _split_missing("split_35K_ms") &
        _split_missing("split_40K_ms")
    )

    split_cols = [f"split_{s['label']}_ms" for s in split_labels]
    df = df[KEEP_COLUMNS + split_cols]

    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Saved {len(df)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
