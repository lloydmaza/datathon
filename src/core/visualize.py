"""
Multi-race interactive Dash app.

Features:
  - Race selector dropdown (loads all races with results.csv at startup)
  - Gender, age group, and (for LA races) category filters
  - Bib lookup and name search
  - Runner details panel: stats card + segment pace chart (Xacte races)
    or peer cohort histogram (races without splits)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import gaussian_kde

import dash
from dash import dcc, html, Input, Output, State, no_update
import dash_mantine_components as dmc

# Ensure src/ is on path so imports work when run directly
_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from core.connector import AGE_GROUP_LABELS
from core.normalize import fmt_time_minutes

# ── Constants ─────────────────────────────────────────────────────────────────

BIN_WIDTH           = 5   # histogram bucket width, minutes
ADAPTIVE_CATEGORIES = {"Wheelchair", "Handcycle"}

HIST_COLOR   = "rgba(64, 192, 255, 0.45)"
KDE_COLOR    = "#40C0FF"
CDF_COLOR    = "#20D9A0"
MEDIAN_COLOR = "rgba(255,255,255,0.7)"
BIB_COLOR    = "#FF6B6B"
GRID_COLOR   = "rgba(255,255,255,0.07)"
BG_COLOR     = "#1A1B1E"
PAPER_COLOR  = "#25262B"
CARD_COLOR   = "#2C2E33"

# ── Race data (populated by run_app) ──────────────────────────────────────────

RACE_DATA: dict = {}   # race_key → {connector, df, splits_df}


def _load_all_races() -> dict:
    from races import REGISTRY
    data = {}
    for key, cls in REGISTRY.items():
        c = cls()
        if not c.results_path.exists():
            continue
        df = c.load_results()
        splits_df = pd.read_csv(c.splits_path) if c.splits_path.exists() else None
        data[key] = {"connector": c, "df": df, "splits_df": splits_df}
        note = f", {len(splits_df):,} split rows" if splits_df is not None else ""
        print(f"  Loaded {key}: {len(df):,} runners{note}")
    return data


# ── Small helpers ─────────────────────────────────────────────────────────────

def _finishers(df: pd.DataFrame) -> pd.DataFrame:
    mask = (
        ~df["dnf"].fillna(False).astype(bool) &
        ~df["dq"].fillna(False).astype(bool) &
        ~df["short_course"].fillna(False).astype(bool)
    )
    return df[mask].copy()


def _fmt_pace(sec_per_mile: float) -> str:
    m = int(sec_per_mile) // 60
    s = int(sec_per_mile) % 60
    return f"{m}:{s:02d}"


def _ms_to_clock(ms: float) -> str:
    s = int(ms) // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# ── Main distribution figure ──────────────────────────────────────────────────

def build_main_figure(df, connector, gender, age_group, category_filter, active_bib):
    mask = ~df["dnf"].fillna(False) & ~df["dq"].fillna(False)
    if connector.has_short_course:
        mask &= ~df["short_course"].fillna(False)
    if connector.has_category and category_filter == "Runners":
        mask &= ~df["category"].isin(ADAPTIVE_CATEGORIES)
    elif connector.has_category and category_filter == "Adaptive":
        mask &= df["category"].isin(ADAPTIVE_CATEGORIES)

    fin = df[mask].copy()
    if gender != "All":
        fin = fin[fin["sex"] == gender]
    if age_group != "All":
        fin = fin[fin["age_group"] == age_group]

    times = fin["chiptime_ms"].dropna() / 60_000

    if len(times) < 2:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark", paper_bgcolor=PAPER_COLOR, plot_bgcolor=BG_COLOR,
            title_text="Not enough data for selected filters",
        )
        return fig

    x_min = (times.min() // BIN_WIDTH) * BIN_WIDTH
    x_max = (times.max() // BIN_WIDTH + 1) * BIN_WIDTH
    bin_edges   = np.arange(x_min, x_max + BIN_WIDTH, BIN_WIDTH)
    counts, _   = np.histogram(times, bins=bin_edges)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    bin_hover   = [
        f"{fmt_time_minutes(lo)} – {fmt_time_minutes(hi)}: {n:,} runners"
        for lo, hi, n in zip(bin_edges[:-1], bin_edges[1:], counts)
    ]
    kde_x = np.linspace(times.min(), times.max(), 1000)
    kde_y = gaussian_kde(times, bw_method="scott")(kde_x) * len(times) * BIN_WIDTH
    sorted_times = np.sort(times)
    cdf = np.arange(1, len(sorted_times) + 1) / len(sorted_times)

    # Per-runner data for interactive CDF scatter
    fin_sorted        = fin.sort_values("chiptime_ms").reset_index(drop=True)
    runner_times_min  = fin_sorted["chiptime_ms"] / 60_000
    runner_cdf_vals   = np.arange(1, len(fin_sorted) + 1) / len(fin_sorted)
    runner_bibs       = fin_sorted["bib"].astype(str).tolist()
    runner_hover      = [
        f"<b>{row['full_name']}</b>  ·  #{row['bib']}<br>"
        f"Finish: {fmt_time_minutes(t)}  ·  {p:.1%} of finishers"
        for (_, row), t, p in zip(fin_sorted.iterrows(), runner_times_min, runner_cdf_vals)
    ]
    median = float(np.median(times))

    tick_min  = (times.min() // 30) * 30
    tick_max  = (times.max() // 30 + 1) * 30
    tick_vals = np.arange(tick_min, tick_max + 1, 30).tolist()
    tick_text = [fmt_time_minutes(v) for v in tick_vals]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        subplot_titles=("Distribution (PDF)", "Cumulative (CDF)"),
        vertical_spacing=0.12,
    )
    fig.add_trace(go.Bar(
        x=bin_centers, y=counts, width=BIN_WIDTH,
        marker_color=HIST_COLOR, marker_line_width=0,
        customdata=bin_hover, hovertemplate="%{customdata}<extra></extra>",
        showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=kde_x, y=kde_y, mode="lines",
        line=dict(color=KDE_COLOR, width=2),
        hoverinfo="skip", showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=sorted_times, y=cdf, mode="lines",
        line=dict(color=CDF_COLOR, width=2),
        hoverinfo="skip", showlegend=False,
    ), row=2, col=1)
    fig.add_trace(go.Scattergl(
        x=runner_times_min, y=runner_cdf_vals, mode="markers",
        marker=dict(size=6, color=CDF_COLOR, opacity=0.45),
        customdata=runner_bibs,
        hovertext=runner_hover,
        hovertemplate="%{hovertext}<extra></extra>",
        showlegend=False,
    ), row=2, col=1)

    for row in (1, 2):
        fig.add_vline(x=median, line_dash="dot",
                      line_color=MEDIAN_COLOR, line_width=1.5, row=row, col=1)
    fig.add_annotation(
        x=median, y=1.0, xref="x", yref="paper",
        text=f"Median {fmt_time_minutes(median)}",
        showarrow=False, xanchor="left", xshift=6,
        font=dict(size=11, color=MEDIAN_COLOR), yanchor="top",
    )

    bib = (active_bib or "").strip()
    if bib:
        matches = df[df["bib"].astype(str) == bib]
        if not matches.empty:
            r = matches.iloc[0]
            bib_ms = r.get("chiptime_ms")
            if pd.notna(bib_ms):
                bib_min   = bib_ms / 60_000
                bib_name  = r.get("full_name") or f"Bib {bib}"
                bib_cdf   = float(np.searchsorted(sorted_times, bib_min, "right") / len(sorted_times))
                bib_label = f"{bib_name} (#{bib})"
                for row in (1, 2):
                    fig.add_vline(x=bib_min, line_dash="dash",
                                  line_color=BIB_COLOR, line_width=1.5, row=row, col=1)
                fig.add_trace(go.Scatter(
                    x=[bib_min], y=[bib_cdf], mode="markers",
                    marker=dict(color=BIB_COLOR, size=9, symbol="circle",
                                line=dict(color="white", width=1)),
                    text=[f"{bib_label}<br>{fmt_time_minutes(bib_min)}  ({bib_cdf:.1%})"],
                    hoverinfo="text", showlegend=False,
                ), row=2, col=1)
                fig.add_annotation(
                    x=bib_min, y=1.0, xref="x", yref="paper",
                    text=bib_label, showarrow=False,
                    xanchor="right", xshift=-6,
                    font=dict(size=11, color=BIB_COLOR), yanchor="top",
                )

    axis_style = dict(tickvals=tick_vals, ticktext=tick_text, tickangle=45,
                      showgrid=True, gridcolor=GRID_COLOR, zeroline=False)
    fig.update_xaxes(**axis_style)
    fig.update_xaxes(title_text="Finish time", row=2, col=1)
    fig.update_yaxes(title_text="Runners", showgrid=True, gridcolor=GRID_COLOR,
                     zeroline=False, row=1, col=1)
    fig.update_yaxes(title_text="% of finishers", tickformat=".0%",
                     showgrid=True, gridcolor=GRID_COLOR, zeroline=False, row=2, col=1)

    fig.update_layout(
        template="plotly_dark", paper_bgcolor=PAPER_COLOR, plot_bgcolor=BG_COLOR,
        title=dict(
            text=f"{connector.display_name} — Finish Time Distribution  ·  n={len(fin):,}",
            font=dict(size=15, color="rgba(255,255,255,0.85)"),
            x=0.01, xanchor="left",
        ),
        hovermode="closest",
        hoverlabel=dict(bgcolor="#2C2E33", font_color="white", bordercolor="#555"),
        showlegend=False, height=720,
        margin=dict(t=70, b=20, l=60, r=20),
    )
    for ann in fig.layout.annotations:
        ann.font.color = "rgba(255,255,255,0.55)"
        ann.font.size  = 12
    return fig


# ── Runner panel: segment pace chart (Xacte races) ───────────────────────────

def build_splits_figure(
    bib: str,
    splits_df: pd.DataFrame,
    fin_df: pd.DataFrame,
    distance_m: int,
) -> go.Figure | None:
    runner_splits = (
        splits_df[splits_df["bib"].astype(str) == bib]
        .sort_values("displayorder")
    )
    runner_splits = runner_splits[runner_splits["distance_m"] > 0].reset_index(drop=True)
    if runner_splits.empty or runner_splits["delta_ms"].isna().all():
        return None

    labels    = runner_splits["label"].tolist()
    cum_dists = runner_splits["distance_m"].tolist()
    seg_dists = [cum_dists[0]] + [cum_dists[i] - cum_dists[i - 1] for i in range(1, len(cum_dists))]

    # Runner pace per segment (sec/mile)
    runner_paces = [
        (delta / 1000) / (seg_dist / 1609.344)
        if (pd.notna(delta) and delta > 0 and seg_dist > 0) else None
        for delta, seg_dist in zip(runner_splits["delta_ms"], seg_dists)
    ]

    # Field median pace per segment (all finishers)
    label_to_seg_dist = dict(zip(labels, seg_dists))
    median_paces = []
    for label in labels:
        seg_dist   = label_to_seg_dist[label]
        seg_deltas = splits_df[splits_df["label"] == label]["delta_ms"].dropna()
        seg_deltas = seg_deltas[seg_deltas > 0]
        if len(seg_deltas) > 0 and seg_dist > 0:
            median_paces.append((seg_deltas.median() / 1000) / (seg_dist / 1609.344))
        else:
            median_paces.append(None)

    # Convert to speed (mph) — higher bar = faster
    def to_speed(pace):
        return 3600.0 / pace if pace else None

    runner_speeds = [to_speed(p) for p in runner_paces]
    median_speeds = [to_speed(p) for p in median_paces]

    bar_colors = [
        CDF_COLOR  if (rs is not None and ms is not None and rs > ms) else
        BIB_COLOR  if (rs is not None and ms is not None and rs <= ms) else
        "rgba(120,120,120,0.5)"
        for rs, ms in zip(runner_speeds, median_speeds)
    ]

    # First / second half split
    half_dist = distance_m / 2
    fh_ms = runner_splits[runner_splits["distance_m"] <= half_dist]["delta_ms"].dropna().sum()
    sh_ms = runner_splits[runner_splits["distance_m"] >  half_dist]["delta_ms"].dropna().sum()
    split_note = ""
    if fh_ms > 0 and sh_ms > 0:
        diff_ms   = sh_ms - fh_ms
        sign      = "+" if diff_ms >= 0 else "-"
        split_note = (
            f"  ·  1st {_ms_to_clock(fh_ms)} / 2nd {_ms_to_clock(sh_ms)}"
            f"  ({sign}{_ms_to_clock(abs(diff_ms))} {'positive' if diff_ms >= 0 else 'negative'} split)"
        )

    # Y-axis range with room for text labels above bars
    valid_speeds = [s for s in runner_speeds + median_speeds if s is not None]
    speed_range  = max(valid_speeds) - min(valid_speeds) if len(valid_speeds) > 1 else 1.0
    y_max = max(valid_speeds) + speed_range * 0.45
    y_min = min(valid_speeds) - speed_range * 0.05

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels,
        y=runner_speeds,
        marker_color=bar_colors,
        marker_line_width=0,
        text=[f"{_fmt_pace(p)}" if p else "—" for p in runner_paces],
        textposition="outside",
        textfont=dict(size=10, color="rgba(255,255,255,0.85)"),
        hovertext=[
            f"{lbl}: {_fmt_pace(p)}/mi" if p else f"{lbl}: missing"
            for lbl, p in zip(labels, runner_paces)
        ],
        hoverinfo="text",
        showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=labels,
        y=median_speeds,
        mode="lines+markers",
        line=dict(color=MEDIAN_COLOR, dash="dot", width=1.5),
        marker=dict(size=5, color=MEDIAN_COLOR),
        hovertext=[
            f"Median {lbl}: {_fmt_pace(p)}/mi" if p else ""
            for lbl, p in zip(labels, median_paces)
        ],
        hoverinfo="text",
        showlegend=False,
    ))
    fig.add_annotation(
        x=1.0, y=1.05, xref="paper", yref="paper",
        text=(
            f"<span style='color:{CDF_COLOR}'>▌</span> faster than median  "
            f"<span style='color:{BIB_COLOR}'>▌</span> slower  "
            f"<span style='color:{MEDIAN_COLOR}'>- - -</span> field median"
        ),
        showarrow=False, xanchor="right", yanchor="bottom",
        font=dict(size=10, color="rgba(255,255,255,0.5)"),
    )
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=PAPER_COLOR, plot_bgcolor=BG_COLOR,
        title=dict(
            text=f"Pace by Segment{split_note}",
            font=dict(size=12, color="rgba(255,255,255,0.65)"),
            x=0.01,
        ),
        xaxis=dict(showgrid=False, tickfont=dict(size=11)),
        yaxis=dict(
            showticklabels=False, showgrid=False, zeroline=False,
            range=[y_min, y_max],
        ),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#2C2E33", font_color="white"),
        showlegend=False,
        height=290,
        margin=dict(t=50, b=20, l=20, r=20),
    )
    return fig


# ── Runner panel: peer cohort histogram (races without splits) ────────────────

def build_cohort_figure(runner_row, fin_df, connector) -> go.Figure | None:
    sex       = runner_row.get("sex")
    age_group = str(runner_row.get("age_group"))
    bib_ms    = runner_row.get("chiptime_ms")
    if pd.isna(bib_ms):
        return None

    cohort = fin_df[(fin_df["sex"] == sex) & (fin_df["age_group"].astype(str) == age_group)]
    cohort_label = f"{sex} / {age_group}"
    if len(cohort) < 5:
        cohort = fin_df[fin_df["sex"] == sex]
        cohort_label = sex

    times = cohort["chiptime_ms"].dropna() / 60_000
    if len(times) < 2:
        return None

    bib_min = bib_ms / 60_000
    x_min = (times.min() // BIN_WIDTH) * BIN_WIDTH
    x_max = (times.max() // BIN_WIDTH + 1) * BIN_WIDTH
    bin_edges   = np.arange(x_min, x_max + BIN_WIDTH, BIN_WIDTH)
    counts, _   = np.histogram(times, bins=bin_edges)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    bar_colors = [
        BIB_COLOR if lo <= bib_min < hi else HIST_COLOR
        for lo, hi in zip(bin_edges[:-1], bin_edges[1:])
    ]

    cohort_rank = int((times < bib_min).sum()) + 1
    cohort_pct  = (len(times) - cohort_rank) / len(times) * 100

    tick_min  = (times.min() // 30) * 30
    tick_max  = (times.max() // 30 + 1) * 30
    tick_vals = np.arange(tick_min, tick_max + 1, 30).tolist()
    tick_text = [fmt_time_minutes(v) for v in tick_vals]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=bin_centers, y=counts, width=BIN_WIDTH,
        marker_color=bar_colors, marker_line_width=0,
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_vline(x=bib_min, line_dash="dash", line_color=BIB_COLOR, line_width=1.5)
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=PAPER_COLOR, plot_bgcolor=BG_COLOR,
        title=dict(
            text=(
                f"Peer Cohort: {cohort_label}  ·  "
                f"Rank {cohort_rank:,} / {len(times):,}  ({cohort_pct:.1f}th pct)"
            ),
            font=dict(size=12, color="rgba(255,255,255,0.65)"),
            x=0.01,
        ),
        xaxis=dict(tickvals=tick_vals, ticktext=tick_text, tickangle=45,
                   title="Finish time", showgrid=True, gridcolor=GRID_COLOR, zeroline=False),
        yaxis=dict(title="Runners", showgrid=True, gridcolor=GRID_COLOR, zeroline=False),
        height=290,
        margin=dict(t=50, b=60, l=60, r=20),
    )
    return fig


# ── Runner panel: stats card ──────────────────────────────────────────────────

def build_stats_card(runner_row, fin_df, splits_df, connector):
    bib       = str(runner_row.get("bib", ""))
    full_name = (
        runner_row.get("full_name") or
        f"{runner_row.get('firstname', '')} {runner_row.get('lastname', '')}".strip() or
        f"Bib {bib}"
    )
    age       = runner_row.get("age")
    sex       = runner_row.get("sex")
    age_group = str(runner_row.get("age_group"))
    city      = str(runner_row.get("city") or "")
    state     = str(runner_row.get("state") or "")
    location  = ", ".join(filter(None, [city, state]))
    chiptime  = str(runner_row.get("chiptime") or "")
    chiptime_ms = runner_row.get("chiptime_ms")

    # Pace
    pace_str = "—"
    if pd.notna(chiptime_ms) and chiptime_ms > 0:
        spm = (chiptime_ms / 1000) / (connector.distance_m / 1609.344)
        pace_str = f"{_fmt_pace(spm)}/mi"

    # Ranks
    n_total  = len(fin_df)
    same_sex = fin_df[fin_df["sex"] == sex]
    same_ag  = fin_df[
        (fin_df["sex"] == sex) & (fin_df["age_group"].astype(str) == age_group)
    ]

    overall_rank = runner_row.get("overall")
    sex_rank     = runner_row.get("oversex")

    # Compute age group rank from data (more accurate than stored overdiv)
    ag_rank = ag_total = ag_pct = None
    if len(same_ag) > 0 and pd.notna(chiptime_ms):
        ag_rank  = int((same_ag["chiptime_ms"] < chiptime_ms).sum()) + 1
        ag_total = len(same_ag)
        ag_pct   = (ag_total - ag_rank) / ag_total * 100

    def _pct(rank, total):
        return (total - int(rank)) / total * 100 if pd.notna(rank) else None

    overall_pct = _pct(overall_rank, n_total)
    sex_pct     = _pct(sex_rank, len(same_sex))

    def rank_row(label, rank, total, pct):
        if rank is None or pd.isna(rank):
            return None
        return dmc.Group(
            justify="space-between",
            children=[
                dmc.Text(label, size="sm", c="dimmed"),
                dmc.Group(gap=6, children=[
                    dmc.Text(f"{int(rank):,} / {total:,}", size="sm", c="white"),
                    dmc.Badge(f"{pct:.1f}th %ile", color="blue", variant="light", size="sm"),
                ]),
            ],
        )

    rank_rows = [
        rank_row("Overall",           overall_rank, n_total,       overall_pct),
        rank_row(f"{sex} gender",     sex_rank,     len(same_sex), sex_pct),
        rank_row(f"{age_group}",      ag_rank,      ag_total,      ag_pct),
    ]
    rank_rows = [r for r in rank_rows if r is not None]

    badges = [
        dmc.Badge(f"Age {age}", color="gray", variant="light", size="sm"),
        dmc.Badge(str(sex),     color="gray", variant="light", size="sm"),
        dmc.Badge(age_group,    color="gray", variant="light", size="sm"),
    ]
    if location:
        badges.append(dmc.Badge(location, color="gray", variant="light", size="sm"))

    # First/second half split (Xacte races only)
    split_section = []
    if splits_df is not None and pd.notna(chiptime_ms):
        runner_splits = (
            splits_df[splits_df["bib"].astype(str) == bib]
            .sort_values("displayorder")
        )
        runner_splits = runner_splits[runner_splits["distance_m"] > 0]
        half_dist = connector.distance_m / 2
        fh_ms = runner_splits[runner_splits["distance_m"] <= half_dist]["delta_ms"].dropna().sum()
        sh_ms = runner_splits[runner_splits["distance_m"] >  half_dist]["delta_ms"].dropna().sum()
        if fh_ms > 0 and sh_ms > 0:
            diff_ms  = sh_ms - fh_ms
            sign     = "+" if diff_ms >= 0 else "-"
            color    = "red" if diff_ms > 0 else "teal"
            split_section = [
                dmc.Divider(my=6),
                dmc.Text("Split analysis", size="xs", c="dimmed", fw=500),
                dmc.Group(justify="space-between", children=[
                    dmc.Text("1st half", size="sm", c="dimmed"),
                    dmc.Text(_ms_to_clock(fh_ms), size="sm", c="white"),
                ]),
                dmc.Group(justify="space-between", children=[
                    dmc.Text("2nd half", size="sm", c="dimmed"),
                    dmc.Text(_ms_to_clock(sh_ms), size="sm", c="white"),
                ]),
                dmc.Group(justify="space-between", children=[
                    dmc.Text("Net split", size="sm", c="dimmed"),
                    dmc.Badge(
                        f"{sign}{_ms_to_clock(abs(diff_ms))} "
                        f"({'positive' if diff_ms >= 0 else 'negative'})",
                        color=color, variant="light", size="sm",
                    ),
                ]),
            ]

        # Fastest / slowest segment
        valid_splits = runner_splits[runner_splits["delta_ms"].notna() & (runner_splits["delta_ms"] > 0)].copy()
        if not valid_splits.empty:
            cum_dists = valid_splits["distance_m"].tolist()
            prev_dists = [0.0] + cum_dists[:-1]
            seg_dists = [c - p for c, p in zip(cum_dists, prev_dists)]
            valid_splits = valid_splits.copy()
            valid_splits["seg_dist"] = seg_dists
            valid_splits["pace"] = (valid_splits["delta_ms"] / 1000) / (
                valid_splits["seg_dist"] / 1609.344
            )
            fastest = valid_splits.loc[valid_splits["pace"].idxmin()]
            slowest = valid_splits.loc[valid_splits["pace"].idxmax()]
            split_section += [
                dmc.Group(justify="space-between", children=[
                    dmc.Text("Fastest seg.", size="sm", c="dimmed"),
                    dmc.Text(
                        f"{fastest['label']}  {_fmt_pace(fastest['pace'])}/mi",
                        size="sm", c=CDF_COLOR,
                    ),
                ]),
                dmc.Group(justify="space-between", children=[
                    dmc.Text("Slowest seg.", size="sm", c="dimmed"),
                    dmc.Text(
                        f"{slowest['label']}  {_fmt_pace(slowest['pace'])}/mi",
                        size="sm", c=BIB_COLOR,
                    ),
                ]),
            ]

    return dmc.Paper(
        p="md", radius="md",
        style={"backgroundColor": CARD_COLOR, "height": "100%"},
        children=[dmc.Stack(gap="xs", children=[
            # Name + time
            dmc.Group(justify="space-between", align="flex-start", children=[
                dmc.Stack(gap=2, children=[
                    dmc.Text(full_name, size="lg", fw=700, c="white"),
                    dmc.Text(f"Bib #{bib}", size="sm", c="dimmed"),
                ]),
                dmc.Stack(gap=2, align="flex-end", children=[
                    dmc.Text(chiptime, size="xl", fw=700, c=KDE_COLOR),
                    dmc.Text(pace_str, size="sm", c="dimmed"),
                ]),
            ]),
            dmc.Divider(my=2),
            dmc.Group(gap=6, children=badges),
            dmc.Divider(my=2),
            *rank_rows,
            *split_section,
        ])],
    )


# ── App builder ───────────────────────────────────────────────────────────────

def _select(id_, label, data, value, w=150):
    return dmc.Select(
        id=id_, label=label,
        data=[{"label": d, "value": d} for d in data],
        value=value, allowDeselect=False,
        styles={
            "input":    {"backgroundColor": CARD_COLOR, "borderColor": "#444", "color": "white"},
            "dropdown": {"backgroundColor": CARD_COLOR},
            "option":   {"color": "white"},
        },
        w=w,
    )


def build_app(default_race: str | None = None) -> dash.Dash:
    if not RACE_DATA:
        raise RuntimeError("RACE_DATA is empty — call run_app() which populates it first.")

    first_race = default_race if default_race in RACE_DATA else next(iter(RACE_DATA))
    first_conn = RACE_DATA[first_race]["connector"]
    first_df   = RACE_DATA[first_race]["df"]

    race_options = [
        {"label": RACE_DATA[k]["connector"].display_name, "value": k}
        for k in RACE_DATA
    ]
    init_genders    = ["All"] + sorted(first_df["sex"].dropna().unique().tolist())
    init_cat_style  = {"display": "flex"} if first_conn.has_category else {"display": "none"}

    app = dash.Dash(__name__, suppress_callback_exceptions=True)

    app.layout = dmc.MantineProvider(
        forceColorScheme="dark",
        children=html.Div(
            style={"backgroundColor": BG_COLOR, "minHeight": "100vh", "padding": "0 0 40px 0"},
            children=[
                # ── Header ────────────────────────────────────────────────────
                html.Div(
                    style={"backgroundColor": "#16171A", "padding": "14px 28px 12px",
                           "borderBottom": "1px solid #2C2E33"},
                    children=[dmc.Group(justify="space-between", align="center", children=[
                        dmc.Stack(gap=0, children=[
                            dmc.Text("Marathon Finish Time Analysis", size="xl", fw=700, c="white"),
                            dmc.Text("Select a race, then filter by gender, age group, or bib number",
                                     size="sm", c="dimmed"),
                        ]),
                        dmc.Select(
                            id="race-selector",
                            data=race_options,
                            value=first_race,
                            allowDeselect=False,
                            styles={
                                "input":    {"backgroundColor": CARD_COLOR, "borderColor": "#555",
                                             "color": "white", "fontWeight": "600"},
                                "dropdown": {"backgroundColor": CARD_COLOR},
                                "option":   {"color": "white"},
                            },
                            w=280,
                        ),
                    ])],
                ),

                # ── Controls ──────────────────────────────────────────────────
                html.Div(
                    style={"padding": "16px 28px 4px", "display": "flex",
                           "flexWrap": "wrap", "gap": "20px", "alignItems": "flex-end"},
                    children=[
                        _select("gender-filter", "Gender",
                                init_genders, "All"),
                        _select("age-group-filter", "Age Group",
                                ["All"] + AGE_GROUP_LABELS, "All"),

                        # Category control — visibility toggled by callback
                        html.Div(
                            id="category-wrapper",
                            style=init_cat_style,
                            children=[dmc.Stack(gap=6, children=[
                                dmc.Text("Category", size="sm", fw=500, c="dimmed"),
                                dmc.SegmentedControl(
                                    id="category-filter",
                                    data=["Runners", "Adaptive", "All"],
                                    value="Runners",
                                    color="blue",
                                    styles={
                                        "root":  {"backgroundColor": CARD_COLOR},
                                        "label": {"color": "rgba(255,255,255,0.7)"},
                                    },
                                ),
                            ])],
                        ),

                        dmc.Divider(orientation="vertical",
                                    style={"height": "52px", "alignSelf": "flex-end"}),

                        html.Div(
                            style={"display": "flex", "gap": "12px", "alignItems": "flex-end"},
                            children=[
                                dmc.TextInput(
                                    id="bib-input", label="Bib Number",
                                    placeholder="e.g. 1234", debounce=True,
                                    styles={"input": {"backgroundColor": CARD_COLOR,
                                                      "borderColor": "#444", "color": "white",
                                                      "width": "110px"}},
                                ),
                                dmc.TextInput(
                                    id="name-search", label="Name Search",
                                    placeholder="First or last name", debounce=True,
                                    styles={"input": {"backgroundColor": CARD_COLOR,
                                                      "borderColor": "#444", "color": "white",
                                                      "width": "200px"}},
                                ),
                                html.Div(id="name-results-container"),
                                dmc.Select(
                                    id="name-result-select", label="Select runner",
                                    data=[], placeholder="Choose…", allowDeselect=True,
                                    style={"display": "none"},
                                    styles={
                                        "input":    {"backgroundColor": CARD_COLOR,
                                                     "borderColor": "#444", "color": "white",
                                                     "width": "240px"},
                                        "dropdown": {"backgroundColor": CARD_COLOR},
                                        "option":   {"color": "white"},
                                    },
                                    w=240,
                                ),
                            ],
                        ),
                    ],
                ),

                # ── Main chart ────────────────────────────────────────────────
                dcc.Graph(
                    id="main-chart",
                    config={"displayModeBar": True, "displaylogo": False},
                    style={"padding": "8px 12px 0"},
                ),

                # ── Runner panel (shown when bib resolved) ────────────────────
                html.Div(id="runner-panel"),

                # ── Stores ────────────────────────────────────────────────────
                dcc.Store(id="active-bib", data=""),
            ],
        ),
    )

    # ── Callbacks ─────────────────────────────────────────────────────────────

    @app.callback(
        Output("gender-filter",    "data"),
        Output("gender-filter",    "value"),
        Output("category-filter",  "value"),
        Output("category-wrapper", "style"),
        Input("race-selector", "value"),
    )
    def update_race_controls(race_key):
        if race_key not in RACE_DATA:
            return no_update, no_update, no_update, no_update
        rd        = RACE_DATA[race_key]
        df        = rd["df"]
        connector = rd["connector"]
        genders   = ["All"] + sorted(df["sex"].dropna().unique().tolist())
        cat_style = {"display": "flex"} if connector.has_category else {"display": "none"}
        return (
            [{"label": g, "value": g} for g in genders],
            "All",
            "Runners",
            cat_style,
        )

    @app.callback(
        Output("bib-input",   "value", allow_duplicate=True),
        Output("name-search", "value", allow_duplicate=True),
        Input("race-selector", "value"),
        prevent_initial_call=True,
    )
    def clear_search_on_race_change(_):
        return "", ""

    @app.callback(
        Output("name-results-container",  "children"),
        Output("name-result-select",      "data"),
        Output("name-result-select",      "style"),
        Input("name-search",   "value"),
        Input("race-selector", "value"),
    )
    def populate_name_results(query, race_key):
        hidden = {"display": "none"}
        visible = {"display": "block"}
        if not query or len(query.strip()) < 2 or race_key not in RACE_DATA:
            return None, [], hidden
        df = RACE_DATA[race_key]["df"]
        q  = query.strip().lower()
        matches = df[df["full_name"].str.lower().str.contains(q, na=False)].head(20)
        if matches.empty:
            return (
                dmc.Text("No matches", size="xs", c="dimmed",
                         style={"paddingBottom": "8px"}),
                [], hidden,
            )
        options = [
            {"label": f"{row['full_name']}  #{row['bib']}", "value": str(row["bib"])}
            for _, row in matches.iterrows()
        ]
        return None, options, visible

    @app.callback(
        Output("active-bib", "data"),
        Input("bib-input",         "value"),
        Input("name-result-select", "value"),
        State("active-bib",        "data"),
        prevent_initial_call=True,
    )
    def resolve_bib(bib_input, name_select, current_bib):
        from dash import ctx
        resolved = (bib_input if ctx.triggered_id == "bib-input" else name_select) or ""
        resolved = resolved.strip()
        if resolved == (current_bib or "").strip():
            return no_update
        return resolved

    @app.callback(
        Output("active-bib", "data", allow_duplicate=True),
        Input("main-chart",  "clickData"),
        prevent_initial_call=True,
    )
    def click_cdf_to_bib(click_data):
        if not click_data:
            return no_update
        point = click_data["points"][0]
        bib = point.get("customdata")
        # Only the CDF Scattergl trace stores a bib string as customdata
        if isinstance(bib, str) and bib:
            return bib
        return no_update

    @app.callback(
        Output("bib-input",          "value", allow_duplicate=True),
        Output("name-search",        "value", allow_duplicate=True),
        Output("name-result-select", "value", allow_duplicate=True),
        Input("active-bib",  "data"),
        State("race-selector", "value"),
        prevent_initial_call=True,
    )
    def sync_fields_from_active_bib(active_bib, race_key):
        bib = (active_bib or "").strip()
        if not bib or race_key not in RACE_DATA:
            return no_update, no_update, no_update
        df = RACE_DATA[race_key]["df"]
        matches = df[df["bib"].astype(str) == bib]
        if matches.empty:
            return no_update, no_update, no_update
        full_name = matches.iloc[0].get("full_name") or ""
        return bib, full_name, bib

    @app.callback(
        Output("main-chart", "figure"),
        Input("race-selector",    "value"),
        Input("gender-filter",    "value"),
        Input("age-group-filter", "value"),
        Input("category-filter",  "value"),
        Input("active-bib",       "data"),
    )
    def update_chart(race_key, gender, age_group, category_filter, active_bib):
        if race_key not in RACE_DATA:
            return go.Figure()
        rd = RACE_DATA[race_key]
        return build_main_figure(
            rd["df"], rd["connector"],
            gender          or "All",
            age_group       or "All",
            category_filter or "All",
            active_bib      or "",
        )

    @app.callback(
        Output("runner-panel", "children"),
        Input("race-selector", "value"),
        Input("active-bib",    "data"),
    )
    def update_runner_panel(race_key, active_bib):
        bib = (active_bib or "").strip()
        if not bib or race_key not in RACE_DATA:
            return []

        rd        = RACE_DATA[race_key]
        df        = rd["df"]
        connector = rd["connector"]
        splits_df = rd["splits_df"]

        matches = df[df["bib"].astype(str) == bib]
        if matches.empty:
            return []

        runner_row = matches.iloc[0]
        fin_df     = _finishers(df)

        # Right-side chart
        right_fig = None
        if splits_df is not None and not runner_row.get("dnf", False):
            right_fig = build_splits_figure(bib, splits_df, fin_df, connector.distance_m)
        if right_fig is None:
            right_fig = build_cohort_figure(runner_row, fin_df, connector)

        stats_card = build_stats_card(runner_row, fin_df, splits_df, connector)

        right_col = (
            [dcc.Graph(figure=right_fig, config={"displayModeBar": False})]
            if right_fig is not None else []
        )

        return [
            dmc.Divider(style={"margin": "4px 12px"}),
            dmc.Grid(
                gutter="md",
                style={"padding": "8px 16px 24px"},
                children=[
                    dmc.GridCol(span=4, children=[stats_card]),
                    dmc.GridCol(span=8, children=right_col),
                ],
            ),
        ]

    return app


# ── Entry point ───────────────────────────────────────────────────────────────

def run_app(default_race: str | None = None, debug: bool = True):
    global RACE_DATA
    print("Loading race data...")
    RACE_DATA = _load_all_races()
    if not RACE_DATA:
        raise RuntimeError("No races found with results.csv. Run --parse first.")
    app = build_app(default_race=default_race)
    app.run(debug=debug)
