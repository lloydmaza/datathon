"""
SVE Timing connector — handles Monterey Bay Half Marathon 2025.

SVE Timing serves results as server-rendered HTML (no JSON API).
Pages are fetched from:
    <search_url>?page=N

Each page contains ~50 runners in an HTML table.
Total page count is parsed from `data-page` attributes on pagination links.
Pages are cached as data/<race_key>/pages/<page:04d>.html.
"""

import asyncio
import time
from pathlib import Path

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from core.cache import load_meta, save_meta, archive_cache, fetch_all_with_retry
from core.connector import RaceConnector
from core.normalize import hhmmss_to_ms, ms_to_hhmmss, parse_name

SVE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
}


class SVETimingConnector(RaceConnector):
    """
    Subclasses must define: race_key, display_name, distance_m, search_url.
    """

    search_url: str
    concurrency: int = 5   # conservative — HTML server, not a JSON API
    has_category: bool = False
    has_short_course: bool = False

    def __init__(self):
        super().__init__()
        self.meta_path = self.cache_dir / "meta.json"

    @property
    def _referer(self) -> str:
        # Derive results page URL from search URL
        return self.search_url.replace("/search", "/results")

    # ── Fetch ─────────────────────────────────────────────────────────────────

    async def _fetch_impl(self):
        start = time.monotonic()
        semaphore = asyncio.Semaphore(self.concurrency)
        headers = {**SVE_HEADERS, "Referer": self._referer}

        async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
            # Probe page 1 to determine total page count
            print("Probing page 1 for total page count...")
            probe_resp = await client.get(self.search_url, params={"page": 1})
            probe_resp.raise_for_status()
            probe_html = probe_resp.text
            total_pages = self._parse_total_pages(probe_html)
            print(f"Total pages: {total_pages}  (~{total_pages * 50:,} runners)")

            meta = load_meta(self.meta_path)
            if meta is not None and meta["totalPages"] != total_pages:
                print(f"Page count changed ({meta['totalPages']} → {total_pages}). Archiving cache.")
                archive_cache(self.cache_dir)

            all_pages = list(range(1, total_pages + 1))

            # Save page 1 from probe if not already cached
            page1_path = self.cache_dir / "0001.html"
            if not page1_path.exists():
                page1_path.write_text(probe_html, encoding="utf-8")

            async def fetch_and_save(page: int):
                async with semaphore:
                    resp = await client.get(self.search_url, params={"page": page})
                    resp.raise_for_status()
                    (self.cache_dir / f"{page:04d}.html").write_text(resp.text, encoding="utf-8")

            def get_missing():
                cached = {int(p.stem) for p in self.cache_dir.glob("*.html") if p.stem.isdigit()}
                return [p for p in all_pages if p not in cached]

            cached_count = len(all_pages) - len(get_missing())
            print(f"Cached: {cached_count}, to fetch: {len(get_missing())}")

            await fetch_all_with_retry(fetch_and_save, get_missing, label="page")

        save_meta(self.meta_path, {"totalPages": total_pages})
        elapsed = time.monotonic() - start
        print(f"Done. {total_pages} pages cached ({elapsed:.1f}s)")

    @staticmethod
    def _parse_total_pages(html: str) -> int:
        soup = BeautifulSoup(html, "html.parser")
        pages = [int(a["data-page"]) for a in soup.find_all("a", attrs={"data-page": True})]
        if not pages:
            raise ValueError("Could not find pagination links — page structure may have changed.")
        return max(pages)

    # ── Parse ─────────────────────────────────────────────────────────────────

    def _parse_impl(self) -> tuple[pd.DataFrame, None]:
        page_files = sorted(p for p in self.cache_dir.glob("*.html") if p.stem.isdigit())
        if not page_files:
            raise FileNotFoundError(f"No cached pages in {self.cache_dir}/. Run fetch first.")

        print(f"Parsing {len(page_files)} pages...")
        all_records = []
        for page_file in page_files:
            all_records.extend(self._parse_page(page_file.read_text(encoding="utf-8")))

        df = pd.DataFrame(all_records)
        # Drop duplicates — runners can appear in multiple award tables on the same page
        df = df.drop_duplicates(subset=["bib"])
        print(f"Loaded {len(df):,} unique runners from {len(page_files)} pages")

        return df, None

    @staticmethod
    def _parse_page(html: str) -> list[dict]:
        """
        Column layout in SVE Timing HTML table:
        [0] Race Place → overall
        [1] Bib        → bib
        [2] Name       → full_name
        [3] City       → city
        [4] State      → state
        [5] Gun Elapsed→ clocktime
        [6] Chip Elapsed→ chiptime
        [7] Pace       → (dropped)
        [8] Age        → age
        [9] Age Place  → age_place (dropped)
        [10] Gender    → sex
        [11] Gender Place → oversex
        """
        soup = BeautifulSoup(html, "html.parser")
        records = []
        for row in soup.find_all("tr", class_="clickable"):
            cells = row.find_all("td")
            if len(cells) < 12:
                continue

            def cell(i):
                return cells[i].get_text(strip=True)

            chiptime_raw  = cell(6)
            clocktime_raw = cell(5)
            chiptime_ms   = hhmmss_to_ms(chiptime_raw)
            clocktime_ms  = hhmmss_to_ms(clocktime_raw)
            full_name     = cell(2)
            first, last   = parse_name(full_name)

            records.append({
                "bib":          row.get("data-bib-number") or cell(1),
                "full_name":    full_name,
                "firstname":    first,
                "lastname":     last,
                "age":          int(cell(8)) if cell(8).isdigit() else None,
                "sex":          cell(10),
                "city":         cell(3),
                "state":        cell(4),
                "overall":      int(cell(0)) if cell(0).isdigit() else None,
                "oversex":      int(cell(11)) if cell(11).isdigit() else None,
                "chiptime_ms":  chiptime_ms,
                "clocktime_ms": clocktime_ms,
                "chiptime":     ms_to_hhmmss(chiptime_ms),
                "clocktime":    ms_to_hhmmss(clocktime_ms),
                "dnf":          chiptime_ms is None,
            })
        return records
