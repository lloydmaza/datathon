"""
Convert parsed race CSVs → JSON files for the static JS frontend.

Output:
    web/public/data/manifest.json        — list of available races
    web/public/data/<race_key>.json      — runners + splits per race

Run from the repo root:
    python scripts/build_web_data.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make src/ importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.connector import AGE_GROUP_BINS, AGE_GROUP_LABELS
from races import REGISTRY

OUTPUT_DIR = Path(__file__).parent.parent / "web" / "public" / "data"

RUNNER_COLS = [
    "bib", "full_name", "age", "sex",
    "city", "state", "country",
    "overall", "oversex", "overdiv",
    "chiptime_ms", "chiptime",
    "dq", "dnf", "short_course", "category",
]
SPLITS_COLS = ["bib", "label", "distance_m", "displayorder", "elapsed_ms", "delta_ms"]


def derive_age_group(age_series: pd.Series) -> pd.Series:
    return pd.cut(
        age_series,
        bins=AGE_GROUP_BINS,
        labels=AGE_GROUP_LABELS,
        right=False,
    ).astype(str).replace("nan", None)


def to_json_safe(val):
    """Convert numpy/pandas scalars to plain Python types."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (np.bool_,)):
        return bool(val)
    return val


def build_race(race_key: str, connector_cls) -> dict | None:
    connector = connector_cls()
    results_path = connector.results_path
    splits_path  = connector.splits_path

    if not results_path.exists():
        print(f"  skipping {race_key}: no results.csv")
        return None

    df = pd.read_csv(results_path, dtype={"bib": str})

    # Derive age_group (not stored in CSV)
    if "age" in df.columns:
        df["age_group"] = derive_age_group(df["age"])
    else:
        df["age_group"] = None

    # Keep only columns present in the file
    keep = [c for c in RUNNER_COLS if c in df.columns] + ["age_group"]
    df = df[keep]

    # Replace NaN with None
    df = df.where(pd.notna(df), None)

    runners = [
        {k: to_json_safe(v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]

    splits = []
    if splits_path.exists():
        sdf = pd.read_csv(splits_path, dtype={"bib": str})
        sdf = sdf[[c for c in SPLITS_COLS if c in sdf.columns]]
        sdf = sdf.where(pd.notna(sdf), None)
        splits = [
            {k: to_json_safe(v) for k, v in row.items()}
            for row in sdf.to_dict(orient="records")
        ]

    finishers = [r for r in runners if not r.get("dnf") and not r.get("dq") and not r.get("short_course")]

    # Write splits as a separate file (lazy-loaded by the JS app)
    if splits:
        splits_path_out = OUTPUT_DIR / f"{race_key}_splits.json"
        with open(splits_path_out, "w") as f:
            json.dump(splits, f, separators=(",", ":"))
        size_kb = splits_path_out.stat().st_size / 1024
        print(f"  → {splits_path_out}  ({size_kb:.0f} KB,  {len(splits):,} split rows)")

    return {
        "meta": {
            "race_key":        race_key,
            "display_name":    connector.display_name,
            "distance_m":      connector.distance_m,
            "has_category":    connector.has_category,
            "has_short_course": connector.has_short_course,
            "has_splits":      len(splits) > 0,
            "runner_count":    len(finishers),
        },
        "runners": runners,
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []

    for race_key, connector_cls in REGISTRY.items():
        print(f"Building {race_key}...")
        data = build_race(race_key, connector_cls)
        if data is None:
            continue

        out_path = OUTPUT_DIR / f"{race_key}.json"
        with open(out_path, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        size_kb = out_path.stat().st_size / 1024
        print(f"  → {out_path}  ({size_kb:.0f} KB,  {data['meta']['runner_count']:,} finishers)")

        manifest.append(data["meta"])

    manifest_path = OUTPUT_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest → {manifest_path}  ({len(manifest)} races)")


if __name__ == "__main__":
    main()
