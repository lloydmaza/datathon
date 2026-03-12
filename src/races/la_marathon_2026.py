import pandas as pd
from connectors.xacte import XacteConnector


class LAMarathon2026(XacteConnector):
    race_key     = "la_marathon_2026"
    display_name = "2026 LA Marathon"
    distance_m   = 42_195
    event_id     = 2626
    subevent_id  = 6584  # Full Marathon (42 km)

    def _post_process(
        self, df: pd.DataFrame, splits_df: pd.DataFrame | None
    ) -> tuple[pd.DataFrame, pd.DataFrame | None]:
        """Detect short-course finishers: runners who finished but lack 30K/35K/40K splits."""
        if splits_df is not None and not splits_df.empty:
            late_splits = splits_df[splits_df["label"].isin({"30K", "35K", "40K"})]
            bibs_with_late = set(
                late_splits[late_splits["delta_ms"].notna() & (late_splits["delta_ms"] != 0)]["bib"]
                .astype(str).unique()
            )
            df["short_course"] = (
                (~df["dnf"] & ~df["dq"]) &
                ~df["bib"].astype(str).isin(bibs_with_late)
            )
        else:
            df["short_course"] = False
        return df, splits_df
