import re
import pandas as pd


def hhmmss_to_ms(s: str) -> int | None:
    """Convert 'H:MM:SS' or 'HH:MM:SS' string to milliseconds. Returns None if blank/invalid."""
    s = (s or "").strip()
    if not s:
        return None
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})", s)
    if not match:
        return None
    h, m, sec = int(match.group(1)), int(match.group(2)), int(match.group(3))
    return (h * 3600 + m * 60 + sec) * 1000


def ms_to_hhmmss(ms: float | None) -> str:
    """Convert milliseconds to 'H:MM:SS' string. Returns '' for None/NaN."""
    if ms is None or pd.isna(ms):
        return ""
    total_s = int(ms) // 1000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def ms_to_hhmmss_series(ms_series: pd.Series) -> pd.Series:
    """Vectorized ms → 'H:MM:SS' conversion over a Series."""
    result = pd.Series("", index=ms_series.index, dtype=str)
    mask = ms_series.notna()
    s = (ms_series[mask] // 1000).astype(int)
    hours = s // 3600
    minutes = (s % 3600) // 60
    seconds = s % 60
    result[mask] = (
        hours.map(str) + ":" +
        minutes.map(lambda x: f"{x:02d}") + ":" +
        seconds.map(lambda x: f"{x:02d}")
    )
    return result


def parse_name(full_name: str) -> tuple[str, str]:
    """Best-effort split: 'FIRST LAST' → (first, last). Splits on last space."""
    parts = (full_name or "").strip().rsplit(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "")


def fmt_time_minutes(minutes: float) -> str:
    """Format a duration in minutes as 'H:MM' for chart axis labels."""
    h = int(minutes) // 60
    m = int(minutes) % 60
    return f"{h}:{m:02d}"
