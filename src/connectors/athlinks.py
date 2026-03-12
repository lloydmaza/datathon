"""
Athlinks connector — handles SF Marathon 2025.

API:
  Metadata : https://reignite-api.athlinks.com/event/<EVENT_ID>/metadata
  Results  : https://reignite-api.athlinks.com/event/<EVENT_ID>/race/<RACE_ID>/results
               ?correlationId=&from=<OFFSET>&limit=<PAGE_SIZE>

Pagination uses `from` (offset) + `limit`. Total from division.totalAthletes.
Pages are cached as data/<race_key>/pages/<offset:06d>.json.
"""

import asyncio
import json
import time
from pathlib import Path

import httpx
import pandas as pd

from core.cache import load_meta, save_meta, archive_cache, fetch_all_with_retry
from core.connector import RaceConnector
from core.normalize import ms_to_hhmmss_series, parse_name

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.athlinks.com/",
}


class AthlinkConnector(RaceConnector):
    """
    Subclasses must define: race_key, display_name, distance_m, event_id, race_id.
    """

    event_id: int
    race_id: int
    page_size: int = 100
    concurrency: int = 10
    has_category: bool = False
    has_short_course: bool = False

    def __init__(self):
        super().__init__()
        self.metadata_path = self.data_dir / "metadata.json"
        self.meta_path = self.cache_dir / "meta.json"

    @property
    def _metadata_url(self) -> str:
        return f"https://reignite-api.athlinks.com/event/{self.event_id}/metadata"

    @property
    def _results_url(self) -> str:
        return f"https://reignite-api.athlinks.com/event/{self.event_id}/race/{self.race_id}/results"

    # ── Fetch ─────────────────────────────────────────────────────────────────

    async def _fetch_impl(self):
        start = time.monotonic()
        semaphore = asyncio.Semaphore(self.concurrency)

        async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
            # Always refresh metadata
            meta_resp = await client.get(self._metadata_url)
            meta_resp.raise_for_status()
            self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
            self.metadata_path.write_text(meta_resp.text)
            print(f"Fetched metadata → {self.metadata_path}")

            # Probe for total count
            probe_resp = await client.get(
                self._results_url,
                params={"correlationId": "", "from": 0, "limit": self.page_size},
            )
            probe_resp.raise_for_status()
            probe_data = probe_resp.json()
            total = probe_data["division"]["totalAthletes"]

            meta = load_meta(self.meta_path)
            if meta is not None and meta["totalAthletes"] != total:
                print(f"Total changed ({meta['totalAthletes']} → {total}). Archiving cache.")
                archive_cache(self.cache_dir)

            all_offsets = list(range(0, total, self.page_size))
            print(f"Total records: {total:,} ({len(all_offsets)} pages)")

            # Save page 0 from probe if not already cached
            page0_path = self.cache_dir / "000000.json"
            if not page0_path.exists():
                self._save_page(0, probe_data)

            async def fetch_and_save(offset: int):
                async with semaphore:
                    resp = await client.get(
                        self._results_url,
                        params={"correlationId": "", "from": offset, "limit": self.page_size},
                    )
                    resp.raise_for_status()
                    self._save_page(offset, resp.json())

            def get_missing():
                cached = {int(p.stem) for p in self.cache_dir.glob("*.json") if p.stem.isdigit()}
                return [o for o in all_offsets if o not in cached]

            cached_count = len(all_offsets) - len(get_missing())
            print(f"Cached: {cached_count}, to fetch: {len(get_missing())}")

            await fetch_all_with_retry(fetch_and_save, get_missing, label="offset")

        save_meta(self.meta_path, {"totalAthletes": total})
        elapsed = time.monotonic() - start
        print(f"Done. {len(all_offsets)} pages cached ({elapsed:.1f}s)")

    def _save_page(self, offset: int, data: dict):
        path = self.cache_dir / f"{offset:06d}.json"
        with open(path, "w") as f:
            json.dump(data, f)

    # ── Parse ─────────────────────────────────────────────────────────────────

    def _parse_impl(self) -> tuple[pd.DataFrame, None]:
        div_map = self._load_division_map()
        print(f"Loaded {len(div_map)} division mappings from metadata")

        page_files = sorted(p for p in self.cache_dir.glob("*.json") if p.stem.isdigit())
        if not page_files:
            raise FileNotFoundError(f"No cached pages in {self.cache_dir}/. Run fetch first.")

        records = []
        for page_file in page_files:
            with open(page_file) as f:
                data = json.load(f)
            for interval in data.get("intervals", []):
                if interval.get("full"):
                    records.extend(interval["results"])
                    break
        print(f"Loaded {len(records):,} records from {self.cache_dir}/")

        df = pd.DataFrame(records)

        # Flatten location
        df["city"]    = df["location"].apply(lambda x: (x or {}).get("locality", ""))
        df["state"]   = df["location"].apply(lambda x: (x or {}).get("region", ""))
        df["country"] = df["location"].apply(lambda x: (x or {}).get("country", ""))

        # Flatten rankings
        df["overall"] = df["rankings"].apply(lambda x: (x or {}).get("overall"))
        df["oversex"] = df["rankings"].apply(lambda x: (x or {}).get("gender"))
        df["overdiv"] = df["rankings"].apply(lambda x: (x or {}).get("primary"))

        def _age_group_div(rankings):
            other = (rankings or {}).get("other", [])
            if other:
                return div_map.get(other[0]["id"], str(other[0]["id"]))
            return None
        df["age_group_div"] = df["rankings"].apply(_age_group_div)

        df = df.rename(columns={
            "gender":            "sex",
            "chipTimeInMillis":  "chiptime_ms",
            "gunTimeInMillis":   "clocktime_ms",
            "startTimeInMillis": "start_time_ms",
            "id":                "external_id",
            "displayName":       "full_name",
        })

        name_parsed  = df["full_name"].apply(parse_name)
        df["firstname"] = name_parsed.apply(lambda x: x[0])
        df["lastname"]  = name_parsed.apply(lambda x: x[1])

        df["chiptime"]  = ms_to_hhmmss_series(df["chiptime_ms"])
        df["clocktime"] = ms_to_hhmmss_series(df["clocktime_ms"])

        df["dnf"] = df["status"] != "CONF"
        df["dq"]  = df["status"] == "DQ"

        # Stash age_group_div in category column for profile display
        df["category"] = df["age_group_div"]

        return df, None

    def _load_division_map(self) -> dict[int, str]:
        if not self.metadata_path.exists():
            return {}
        with open(self.metadata_path) as f:
            meta = json.load(f)
        div_map = {}
        for race in meta.get("races", []):
            if race["id"] == self.race_id:
                for div in race.get("divisions", []):
                    div_map[div["id"]] = div["name"]
        return div_map
