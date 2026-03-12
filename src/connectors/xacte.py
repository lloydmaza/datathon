"""
Xacte connector — handles LA Marathon 2025 and 2026.

API endpoint: https://results.xacte.com/json/search
Eventconfig:  https://feeds.xacte.com/eventconfig?id=<EVENT_ID>

Each page returns up to PAGE_SIZE records under the "aaData" key.
Total record count is in "iTotalRecords".
Pages are cached as data/<race_key>/pages/<offset:06d>.json.
"""

import asyncio
import json
import time
from pathlib import Path

import httpx
import pandas as pd

from core.cache import load_meta, save_meta, archive_cache, fetch_all_with_retry
from core.connector import RaceConnector, SPLITS_COLUMNS
from core.normalize import ms_to_hhmmss_series, parse_name

BASE_URL       = "https://results.xacte.com/json/search"
EVENTCONFIG_URL = "https://feeds.xacte.com/eventconfig?id={event_id}"


class XacteConnector(RaceConnector):
    """
    Subclasses must define: race_key, display_name, distance_m, event_id, subevent_id.
    """

    event_id: int
    subevent_id: int
    page_size: int = 100
    concurrency: int = 10
    has_category: bool = True
    has_short_course: bool = True

    def __init__(self):
        super().__init__()
        self.eventconfig_path = self.data_dir / "eventconfig.json"
        self.meta_path = self.cache_dir / "meta.json"

    # ── Fetch ─────────────────────────────────────────────────────────────────

    async def _fetch_impl(self):
        start = time.monotonic()
        semaphore = asyncio.Semaphore(self.concurrency)

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Always refresh eventconfig
            cfg_resp = await client.get(EVENTCONFIG_URL.format(event_id=self.event_id))
            cfg_resp.raise_for_status()
            self.eventconfig_path.parent.mkdir(parents=True, exist_ok=True)
            self.eventconfig_path.write_text(cfg_resp.text)
            print(f"Fetched eventconfig → {self.eventconfig_path}")

            # Probe to get total record count
            probe_resp = await client.get(BASE_URL, params={
                "eventId": self.event_id,
                "subeventId": self.subevent_id,
                "offset": 0,
                "limit": self.page_size,
            })
            probe_resp.raise_for_status()
            probe_data = probe_resp.json()
            total = probe_data["iTotalRecords"]

            meta = load_meta(self.meta_path)
            if meta is not None and meta["iTotalRecords"] != total:
                print(f"Total changed ({meta['iTotalRecords']} → {total}). Archiving cache.")
                archive_cache(self.cache_dir)

            all_offsets = list(range(0, total, self.page_size))
            print(f"Total records: {total:,} ({len(all_offsets)} pages)")

            # Save page 0 from probe if not already cached
            page0_path = self.cache_dir / "000000.json"
            if not page0_path.exists():
                self._save_page(0, probe_data["aaData"])

            async def fetch_and_save(offset: int):
                async with semaphore:
                    resp = await client.get(BASE_URL, params={
                        "eventId": self.event_id,
                        "subeventId": self.subevent_id,
                        "offset": offset,
                        "limit": self.page_size,
                    })
                    resp.raise_for_status()
                    self._save_page(offset, resp.json()["aaData"])

            def get_missing():
                cached = {int(p.stem) for p in self.cache_dir.glob("*.json") if p.stem.isdigit()}
                return [o for o in all_offsets if o not in cached]

            cached_count = len(all_offsets) - len(get_missing())
            print(f"Cached: {cached_count}, to fetch: {len(get_missing())}")

            await fetch_all_with_retry(fetch_and_save, get_missing, label="offset")

        save_meta(self.meta_path, {"iTotalRecords": total})
        elapsed = time.monotonic() - start
        print(f"Done. {len(all_offsets)} pages cached ({elapsed:.1f}s)")

    def _save_page(self, offset: int, records: list):
        path = self.cache_dir / f"{offset:06d}.json"
        with open(path, "w") as f:
            json.dump(records, f)

    # ── Parse ─────────────────────────────────────────────────────────────────

    def _parse_impl(self) -> tuple[pd.DataFrame, pd.DataFrame | None]:
        split_labels, finish_distance_id = self._load_split_labels()
        print(f"Loaded {len(split_labels)} split labels: {[s['label'] for s in split_labels]}")

        category_names = self._load_category_names()

        page_files = sorted(p for p in self.cache_dir.glob("*.json") if p.stem.isdigit())
        if not page_files:
            raise FileNotFoundError(f"No cached pages in {self.cache_dir}/. Run fetch first.")

        records = []
        for page_file in page_files:
            with open(page_file) as f:
                records.extend(json.load(f))
        print(f"Loaded {len(records):,} records from {self.cache_dir}/")

        df = pd.DataFrame(records)

        df = df.rename(columns={
            "chiptime":  "chiptime_ms",
            "clocktime": "clocktime_ms",
            "waveId":    "wave_id",
            "externalId": "external_id",
        })
        df["chiptime"]  = ms_to_hhmmss_series(df["chiptime_ms"])
        df["clocktime"] = ms_to_hhmmss_series(df["clocktime_ms"])

        df["dnf"]      = (df["distanceId"] != finish_distance_id) & ~df["dq"]
        df["category"] = df["categoryId"].map(category_names).fillna("Unknown")

        # full_name from firstname/lastname
        df["full_name"] = (
            df["firstname"].fillna("").str.strip() + " " +
            df["lastname"].fillna("").str.strip()
        ).str.strip()

        # Build long-format splits DataFrame
        splits_df = self._build_splits_df(df, split_labels)

        return df, splits_df

    def _build_splits_df(self, df: pd.DataFrame, split_labels: list[dict]) -> pd.DataFrame:
        """
        Build long-format splits DataFrame.

        In the Xacte API, `delta_net` is the CUMULATIVE chip elapsed time from the
        runner's chip start to that checkpoint (confirmed: FINISH delta_net == chiptime_ms).
        Per-segment time is computed by differencing consecutive delta_net values,
        sorted by displayorder.  The raw cumulative value is stored as elapsed_ms.
        """
        rows = []
        for _, runner in df.iterrows():
            bib = runner["bib"]
            splits_raw = runner.get("splits") or {}
            prev_elapsed = 0
            for split in split_labels:
                sid        = split["id"]
                split_data = splits_raw.get(sid) if splits_raw else None
                elapsed    = split_data.get("delta_net") if split_data else None

                if elapsed is not None:
                    delta        = elapsed - prev_elapsed
                    prev_elapsed = elapsed
                else:
                    delta = None   # don't advance prev_elapsed for missing splits

                rows.append({
                    "bib":          bib,
                    "label":        split["label"],
                    "distance_m":   split["distance_m"],
                    "displayorder": split["displayorder"],
                    "elapsed_ms":   elapsed,
                    "delta_ms":     delta,
                })
        return pd.DataFrame(rows, columns=SPLITS_COLUMNS)

    def _load_split_labels(self) -> tuple[list[dict], int]:
        if not self.eventconfig_path.exists():
            raise FileNotFoundError(f"{self.eventconfig_path} not found. Run fetch first.")
        with open(self.eventconfig_path) as f:
            config = json.load(f)
        subevent = config["schema"]["subevents"][str(self.subevent_id)]
        finish_distance_id = subevent["finish_distance_id"]
        distances = subevent["legs"]["0"]["distances"]
        splits = [
            {
                "id":           str(k),
                "label":        v["label"],
                "distance_m":   v["distance"],
                "displayorder": v["displayorder"],
            }
            for k, v in distances.items()
        ]
        return sorted(splits, key=lambda x: x["displayorder"]), finish_distance_id

    def _load_category_names(self) -> dict[int, str]:
        with open(self.eventconfig_path) as f:
            config = json.load(f)
        cats = config["schema"]["subevents"][str(self.subevent_id)]["categories"]
        return {int(cid): cat["name"] for cid, cat in cats.items() if cat.get("name")}
