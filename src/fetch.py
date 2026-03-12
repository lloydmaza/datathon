import asyncio
import json
import time
import httpx
from pathlib import Path

BASE_URL = "https://results.xacte.com/json/search"
EVENTCONFIG_URL = "https://feeds.xacte.com/eventconfig?id=2626"
EVENT_ID = 2626
SUBEVENT_ID = 6584  # Full marathon (42km)
PAGE_SIZE = 100
CONCURRENCY = 10
CACHE_DIR = Path("data/pages")
EVENTCONFIG_PATH = Path("data/eventconfig.json")
META_PATH = CACHE_DIR / "meta.json"


async def fetch_page(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, offset: int) -> list:
    params = {
        "eventId": EVENT_ID,
        "subeventId": SUBEVENT_ID,
        "offset": offset,
        "limit": PAGE_SIZE,
    }
    async with semaphore:
        response = await client.get(BASE_URL, params=params)
        response.raise_for_status()
        return response.json()["aaData"]


def _load_meta() -> dict | None:
    if META_PATH.exists():
        with open(META_PATH) as f:
            return json.load(f)
    return None


def _save_meta(total: int):
    with open(META_PATH, "w") as f:
        json.dump({"iTotalRecords": total}, f)


def _archive_cache():
    """Move current cache contents into an incrementing subdirectory (cache000, cache001, ...)."""
    existing = [p for p in CACHE_DIR.parent.iterdir() if p.is_dir() and p.name.startswith("cache")]
    next_index = len(existing)
    archive_dir = CACHE_DIR.parent / f"cache{next_index:03d}"
    archive_dir.mkdir()
    for p in CACHE_DIR.glob("*.json"):
        p.rename(archive_dir / p.name)
    print(f"Archived previous cache → {archive_dir}/")


def _save_page(offset: int, records: list):
    path = CACHE_DIR / f"{offset:06d}.json"
    with open(path, "w") as f:
        json.dump(records, f)


async def _fetch_all(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, all_offsets: list[int]):
    """Fetch all missing pages with retry-on-timeout: cancels in-flight tasks, pauses, then resumes."""
    PAUSE_SECONDS = 10

    while True:
        cached = {int(p.stem) for p in CACHE_DIR.glob("*.json") if p.stem.isdigit()}
        missing = [o for o in all_offsets if o not in cached]

        if not missing:
            break

        print(f"Fetching {len(missing)} remaining pages...")
        completed = 0

        async def fetch_and_save(offset: int):
            nonlocal completed
            data = await fetch_page(client, semaphore, offset)
            _save_page(offset, data)
            completed += 1
            print(f"  [{completed}/{len(missing)}] offset {offset}")

        tasks = [asyncio.create_task(fetch_and_save(o)) for o in missing]
        try:
            await asyncio.gather(*tasks)
            break
        except httpx.TransportError as e:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            print(f"{type(e).__name__} — pausing {PAUSE_SECONDS}s before resuming...")
            await asyncio.sleep(PAUSE_SECONDS)


async def main():
    start = time.monotonic()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Always refresh eventconfig
        config_response = await client.get(EVENTCONFIG_URL)
        config_response.raise_for_status()
        with open(EVENTCONFIG_PATH, "w") as f:
            f.write(config_response.text)
        print(f"Fetched eventconfig → {EVENTCONFIG_PATH}")

        # Probe to get current total
        probe = await client.get(BASE_URL, params={
            "eventId": EVENT_ID,
            "subeventId": SUBEVENT_ID,
            "offset": 0,
            "limit": PAGE_SIZE,
        })
        probe.raise_for_status()
        probe_data = probe.json()
        total = probe_data["iTotalRecords"]

        # Validate total against cached metadata; wipe cache if it has changed
        meta = _load_meta()
        if meta is not None and meta["iTotalRecords"] != total:
            print(f"Total record count changed ({meta['iTotalRecords']} → {total}). Archiving cache.")
            _archive_cache()

        all_offsets = list(range(0, total, PAGE_SIZE))
        cached_offsets = {int(p.stem) for p in CACHE_DIR.glob("*.json") if p.stem.isdigit()}
        missing_offsets = [o for o in all_offsets if o not in cached_offsets]

        print(f"Total records: {total} ({len(all_offsets)} pages)")
        print(f"Cached: {len(cached_offsets)}, to fetch: {len(missing_offsets)}")

        if not missing_offsets:
            print("All pages already cached.")
            return

        # Reuse probe data for offset 0 if needed rather than re-fetching
        if 0 in missing_offsets:
            _save_page(0, probe_data["aaData"])
            missing_offsets.remove(0)

        await _fetch_all(client, semaphore, all_offsets)

    _save_meta(total)
    elapsed = time.monotonic() - start
    print(f"Done. {len(all_offsets)} pages cached in {CACHE_DIR}/ ({elapsed:.1f}s)")


if __name__ == "__main__":
    asyncio.run(main())
