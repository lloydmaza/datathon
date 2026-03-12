from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

AGE_GROUP_BINS   = [0,  18, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 200]
AGE_GROUP_LABELS = ["<18", "18-24", "25-29", "30-34", "35-39", "40-44", "45-49",
                    "50-54", "55-59", "60-64", "65-69", "70-74", "75-79", "80+"]

# Canonical column order for results.csv — all columns always present (None where unavailable)
RESULTS_COLUMNS = [
    "bib", "full_name", "firstname", "lastname", "age", "sex",
    "city", "state", "country",
    "overall", "oversex", "overdiv",
    "wave_id", "external_id", "start_time_ms",
    "chiptime_ms", "clocktime_ms", "chiptime", "clocktime",
    "dq", "dnf", "short_course", "category",
]

# Canonical column order for splits.csv
SPLITS_COLUMNS = ["bib", "label", "distance_m", "displayorder", "elapsed_ms", "delta_ms"]


class RaceConnector(ABC):
    """Abstract base class for all race data connectors."""

    race_key: str       # e.g. "la_marathon_2026"
    display_name: str   # e.g. "2026 LA Marathon"
    distance_m: int     # course distance in metres
    has_category: bool = False    # True if runner category data (Runners / Adaptive) is available
    has_short_course: bool = False  # True if short-course detection is applicable

    def __init__(self):
        self.data_dir     = Path("data") / self.race_key
        self.cache_dir    = self.data_dir / "pages"
        self.results_path = self.data_dir / "results.csv"
        self.splits_path  = self.data_dir / "splits.csv"

    # ── Public interface ──────────────────────────────────────────────────────

    async def fetch(self):
        """Fetch raw data from the source and cache it locally."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        await self._fetch_impl()

    def parse(self) -> tuple[pd.DataFrame, pd.DataFrame | None]:
        """
        Process cached raw data → results.csv (and splits.csv if available).
        Returns (results_df, splits_df).
        """
        df, splits_df = self._parse_impl()
        df, splits_df = self._post_process(df, splits_df)
        df = self._coerce_schema(df)

        self.data_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(self.results_path, index=False)
        print(f"Saved {len(df):,} rows → {self.results_path}")

        if splits_df is not None and not splits_df.empty:
            splits_df.to_csv(self.splits_path, index=False)
            print(f"Saved {len(splits_df):,} split rows → {self.splits_path}")

        return df, splits_df

    def load_results(self) -> pd.DataFrame:
        """Load results.csv and add derived columns (age_group, full_name)."""
        df = pd.read_csv(self.results_path)
        # Ensure full_name is populated (Xacte stores firstname/lastname separately)
        if df.get("full_name") is None or df["full_name"].isna().all():
            df["full_name"] = (
                df["firstname"].fillna("").str.strip() + " " +
                df["lastname"].fillna("").str.strip()
            ).str.strip()
        df["age_group"] = pd.cut(
            df["age"], bins=AGE_GROUP_BINS, labels=AGE_GROUP_LABELS, right=False
        )
        return df

    # ── Hooks ─────────────────────────────────────────────────────────────────

    @abstractmethod
    async def _fetch_impl(self): ...

    @abstractmethod
    def _parse_impl(self) -> tuple[pd.DataFrame, pd.DataFrame | None]: ...

    def _post_process(
        self, df: pd.DataFrame, splits_df: pd.DataFrame | None
    ) -> tuple[pd.DataFrame, pd.DataFrame | None]:
        """Override in race subclasses for race-specific logic (e.g. short_course detection)."""
        return df, splits_df

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _coerce_schema(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure df has exactly RESULTS_COLUMNS, adding missing ones as None."""
        for col in RESULTS_COLUMNS:
            if col not in df.columns:
                df[col] = None
        for col in ("dq", "dnf", "short_course"):
            df[col] = df[col].fillna(False).astype(bool)
        return df[RESULTS_COLUMNS]
