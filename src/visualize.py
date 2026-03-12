import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from scipy.stats import gaussian_kde

import dash
from dash import dcc, html, Input, Output

INPUT_PATH = Path("data/results.csv")
ADAPTIVE_CATEGORIES = {"Wheelchair", "Handcycle"}
BIN_WIDTH = 5  # minutes

AGE_GROUP_BINS   = [0,  18, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 200]
AGE_GROUP_LABELS = ["<18","18-24","25-29","30-34","35-39","40-44","45-49",
                    "50-54","55-59","60-64","65-69","70-74","75-79","80+"]


def load_data() -> pd.DataFrame:
    df = pd.read_csv(INPUT_PATH)
    df["age_group"] = pd.cut(df["age"], bins=AGE_GROUP_BINS, labels=AGE_GROUP_LABELS, right=False)
    return df


def fmt_time(minutes: float) -> str:
    h = int(minutes) // 60
    m = int(minutes) % 60
    return f"{h}:{m:02d}"


def build_figure(df: pd.DataFrame, gender: str, age_group: str, category_filter: str, bib: str) -> go.Figure:
    # Apply category filter
    if category_filter == "Runners":
        fin = df[~df["dnf"] & ~df["dq"] & ~df["short_course"] & ~df["category"].isin(ADAPTIVE_CATEGORIES)].copy()
    elif category_filter == "Adaptive":
        fin = df[~df["dnf"] & ~df["dq"] & ~df["short_course"] & df["category"].isin(ADAPTIVE_CATEGORIES)].copy()
    else:  # All
        fin = df[~df["dnf"] & ~df["dq"] & ~df["short_course"]].copy()

    # Apply gender filter
    if gender != "All":
        fin = fin[fin["sex"] == gender]

    # Apply age group filter
    if age_group != "All":
        fin = fin[fin["age_group"] == age_group]

    times = fin["chiptime_ms"] / 60_000  # ms → minutes

    if len(times) < 2:
        fig = go.Figure()
        fig.update_layout(title_text="Not enough data for selected filters")
        return fig

    # Histogram bins
    x_min = (times.min() // BIN_WIDTH) * BIN_WIDTH
    x_max = (times.max() // BIN_WIDTH + 1) * BIN_WIDTH
    bin_edges = np.arange(x_min, x_max + BIN_WIDTH, BIN_WIDTH)
    counts, _ = np.histogram(times, bins=bin_edges)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    bin_hover = [
        f"{fmt_time(lo)} – {fmt_time(hi)}: {n:,} runners"
        for lo, hi, n in zip(bin_edges[:-1], bin_edges[1:], counts)
    ]

    # KDE scaled to count axis
    kde_x = np.linspace(times.min(), times.max(), 1000)
    kde_y = gaussian_kde(times, bw_method="scott")(kde_x) * len(times) * BIN_WIDTH

    # Empirical CDF
    sorted_times = np.sort(times)
    cdf = np.arange(1, len(sorted_times) + 1) / len(sorted_times)
    cdf_hover = [
        f"<{fmt_time(t)}: {p:.1%} of finishers"
        for t, p in zip(sorted_times, cdf)
    ]

    median = float(np.median(times))

    # X-axis ticks every 30 minutes
    tick_min = (times.min() // 30) * 30
    tick_max = (times.max() // 30 + 1) * 30
    tick_vals = np.arange(tick_min, tick_max + 1, 30).tolist()
    tick_text = [fmt_time(v) for v in tick_vals]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("Distribution (PDF)", "Cumulative (CDF)"),
        vertical_spacing=0.1,
    )

    # --- PDF ---
    fig.add_trace(go.Bar(
        x=bin_centers,
        y=counts,
        width=BIN_WIDTH,
        marker_color="steelblue",
        opacity=0.5,
        text=bin_hover,
        hoverinfo="text",
        showlegend=False,
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=kde_x,
        y=kde_y,
        mode="lines",
        name="KDE",
        line=dict(color="steelblue", width=2),
        hoverinfo="skip",
    ), row=1, col=1)

    # --- CDF ---
    fig.add_trace(go.Scatter(
        x=sorted_times,
        y=cdf,
        mode="lines",
        name="CDF",
        line=dict(color="steelblue", width=2),
        text=cdf_hover,
        hoverinfo="text",
        showlegend=False,
    ), row=2, col=1)

    # --- Median lines ---
    for row in (1, 2):
        fig.add_vline(
            x=median,
            line_dash="dot",
            line_color="black",
            line_width=1.5,
            row=row, col=1,
        )

    fig.add_annotation(
        x=median, y=1.0, xref="x1", yref="paper",
        text=f"Median: {fmt_time(median)}",
        showarrow=False, xanchor="left", xshift=6,
        font=dict(size=11),
        yanchor="top",
    )

    # --- Bib highlight ---
    bib = (bib or "").strip()
    if bib:
        matches = df[df["bib"].astype(str) == bib]
        if not matches.empty:
            r = matches.iloc[0]
            bib_ms = r.get("chiptime_ms")
            if pd.notna(bib_ms):
                bib_min = bib_ms / 60_000
                bib_name = f"{str(r.get('firstname', '')).strip()} {str(r.get('lastname', '')).strip()}".strip()
                bib_label = f"Bib {bib}" + (f": {bib_name}" if bib_name else "")

                # CDF position
                bib_cdf = float(np.searchsorted(sorted_times, bib_min, side="right") / len(sorted_times))

                for row in (1, 2):
                    fig.add_vline(
                        x=bib_min,
                        line_dash="dash",
                        line_color="orangered",
                        line_width=1.5,
                        row=row, col=1,
                    )

                # Dot on CDF
                fig.add_trace(go.Scatter(
                    x=[bib_min],
                    y=[bib_cdf],
                    mode="markers",
                    marker=dict(color="orangered", size=8, symbol="circle"),
                    text=[f"{bib_label}<br>{fmt_time(bib_min)}  ({bib_cdf:.1%})"],
                    hoverinfo="text",
                    showlegend=False,
                ), row=2, col=1)

                fig.add_annotation(
                    x=bib_min, y=1.0, xref="x1", yref="paper",
                    text=bib_label,
                    showarrow=False, xanchor="right", xshift=-6,
                    font=dict(size=11, color="orangered"),
                    yanchor="top",
                )

    # --- Layout ---
    axis_style = dict(
        tickvals=tick_vals,
        ticktext=tick_text,
        tickangle=45,
        showgrid=True,
        gridcolor="rgba(0,0,0,0.1)",
    )
    fig.update_xaxes(**axis_style)
    fig.update_xaxes(title_text="Finish time", row=1, col=1)
    fig.update_xaxes(title_text="Finish time", row=2, col=1)
    fig.update_yaxes(title_text="Runners", row=1, col=1)
    fig.update_yaxes(
        title_text="Cumulative % of finishers",
        tickformat=".0%",
        row=2, col=1,
    )

    n = len(fin)
    filter_parts = []
    if gender != "All":
        filter_parts.append(gender)
    if age_group != "All":
        filter_parts.append(age_group)
    if category_filter != "All":
        filter_parts.append(category_filter)
    subtitle = f" — {', '.join(filter_parts)}" if filter_parts else ""

    fig.update_layout(
        title_text=f"2026 LA Marathon — Finish Time Distribution{subtitle} (n={n:,})",
        title_font_size=16,
        hovermode="x unified",
        plot_bgcolor="white",
        showlegend=False,
        height=750,
    )

    return fig


# --- App ---

df = load_data()

genders = ["All"] + sorted(df["sex"].dropna().unique().tolist())
age_groups = ["All"] + AGE_GROUP_LABELS

app = dash.Dash(__name__)

app.layout = html.Div([
    html.Div([
        html.Div([
            html.Label("Gender", style={"fontWeight": "bold"}),
            dcc.Dropdown(
                id="gender-filter",
                options=[{"label": g, "value": g} for g in genders],
                value="All",
                clearable=False,
                style={"minWidth": "120px"},
            ),
        ], style={"marginRight": "24px"}),

        html.Div([
            html.Label("Age Group", style={"fontWeight": "bold"}),
            dcc.Dropdown(
                id="age-group-filter",
                options=[{"label": ag, "value": ag} for ag in age_groups],
                value="All",
                clearable=False,
                style={"minWidth": "140px"},
            ),
        ], style={"marginRight": "24px"}),

        html.Div([
            html.Label("Category", style={"fontWeight": "bold"}),
            dcc.RadioItems(
                id="category-filter",
                options=[
                    {"label": "Runners", "value": "Runners"},
                    {"label": "Adaptive", "value": "Adaptive"},
                    {"label": "All", "value": "All"},
                ],
                value="Runners",
                inline=True,
                inputStyle={"marginRight": "4px"},
                labelStyle={"marginRight": "16px"},
            ),
        ], style={"marginRight": "24px"}),

        html.Div([
            html.Label("Bib Number", style={"fontWeight": "bold"}),
            dcc.Input(
                id="bib-input",
                type="text",
                placeholder="e.g. 1234",
                debounce=True,
                style={"width": "100px"},
            ),
        ]),
    ], style={
        "display": "flex",
        "alignItems": "flex-end",
        "padding": "16px",
        "flexWrap": "wrap",
        "gap": "8px",
        "borderBottom": "1px solid #ddd",
    }),

    dcc.Graph(id="main-chart", config={"displayModeBar": True}),
], style={"fontFamily": "sans-serif"})


@app.callback(
    Output("main-chart", "figure"),
    Input("gender-filter", "value"),
    Input("age-group-filter", "value"),
    Input("category-filter", "value"),
    Input("bib-input", "value"),
)
def update_chart(gender, age_group, category_filter, bib):
    return build_figure(df, gender or "All", age_group or "All", category_filter or "Runners", bib or "")


if __name__ == "__main__":
    app.run(debug=True)
