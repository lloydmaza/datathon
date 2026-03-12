import asyncio
import json
from pathlib import Path
from typing import Callable

import httpx


def load_meta(meta_path: Path) -> dict | None:
    if meta_path.exists():
        with open(meta_path) as f:
            return json.load(f)
    return None


def save_meta(meta_path: Path, data: dict):
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_path, "w") as f:
        json.dump(data, f)


def archive_cache(cache_dir: Path):
    """Move current cache files into an incrementing subdirectory (cache000, cache001, ...)."""
    existing = [p for p in cache_dir.parent.iterdir() if p.is_dir() and p.name.startswith("cache")]
    next_index = len(existing)
    archive_dir = cache_dir.parent / f"cache{next_index:03d}"
    archive_dir.mkdir()
    for p in cache_dir.iterdir():
        if p.is_file():
            p.rename(archive_dir / p.name)
    print(f"Archived previous cache → {archive_dir}/")


async def fetch_all_with_retry(
    fetch_and_save_fn: Callable,
    get_missing_fn: Callable,
    label: str = "page",
    pause_seconds: int = 10,
):
    """
    Fetch all missing items with retry on TransportError.

    - get_missing_fn() is called at the start of each attempt to determine what still needs fetching.
    - fetch_and_save_fn(item) is an async function that fetches one item and saves it to disk.
    """
    while True:
        missing = get_missing_fn()
        if not missing:
            break

        print(f"Fetching {len(missing)} remaining {label}s...")
        completed = 0

        async def _fetch_one(item):
            nonlocal completed
            await fetch_and_save_fn(item)
            completed += 1
            print(f"  [{completed}/{len(missing)}] {label} {item}")

        tasks = [asyncio.create_task(_fetch_one(item)) for item in missing]
        try:
            await asyncio.gather(*tasks)
            break
        except httpx.TransportError as e:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            print(f"{type(e).__name__} — pausing {pause_seconds}s before resuming...")
            await asyncio.sleep(pause_seconds)
