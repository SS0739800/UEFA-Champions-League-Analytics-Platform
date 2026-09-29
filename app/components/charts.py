"""
Shared chart styling so every page looks the same.

The app uses a dark navy theme. Series colours are the dark-mode steps of a
palette checked for colour-blind separation against this exact navy (run with
the dataviz validator: all eight pass on adjacent pairs, the first three on
all pairs). Colours are handed out in a fixed order and follow the entity, so
a club keeps its colour when filters change. Scatter plots use at most the
first three.
"""

import plotly.graph_objects as go
import plotly.io as pio

# Page and panel colours, kept in sync with .streamlit/config.toml.
SURFACE = "#0a0f2e"
PANEL = "#111a45"

ACCENT = "#3987e5"
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
# Grey marks for "everything else" when one thing is highlighted.
MUTED_MARK = "#4a5485"
INK = "#f3f5ff"
INK_SECONDARY = "#c2c8ea"
INK_MUTED = "#8b93c2"
GRID = "#1d2657"
AXIS = "#343f78"

# One-hue scale for counts (confusion matrix): from just above the panel colour to bright blue.
SEQUENTIAL = [[0.0, "#16204f"], [1.0, "#3987e5"]]

# Diverging scale for z-scores: blue above average, red below, a dark neutral in the middle.
DIVERGING = [[0.0, "#e66767"], [0.25, "#8a3f4f"], [0.5, "#1d2657"], [0.75, "#2c5ea3"], [1.0, "#5598e7"]]

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
HEADING_FONT = "'Barlow Condensed', system-ui, sans-serif"

pio.templates["ucl"] = go.layout.Template(
    layout=dict(
        font=dict(family=FONT, size=13, color=INK_SECONDARY),
        title=dict(font=dict(family=HEADING_FONT, size=18, color=INK), x=0, xanchor="left", pad=dict(b=8)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=SERIES,
        xaxis=dict(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, ticks="", showline=True, automargin=True,
                   title=dict(font=dict(size=12, color=INK_MUTED))),
        yaxis=dict(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, ticks="", showline=False, automargin=True,
                   title=dict(font=dict(size=12, color=INK_MUTED))),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title_text="",
                    font=dict(size=12, color=INK_SECONDARY)),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=AXIS, font=dict(family=FONT, size=12, color=INK)),
        margin=dict(l=8, r=8, t=56, b=8),
        bargap=0.25,
    )
)
# Streamlit swaps in its own default template when it loads, so style() sets ours on each figure too.
pio.templates.default = "ucl"

# Scatter markers get a ring in the page colour, so overlapping points stay separate.
MARKER_RING = dict(color=SURFACE, width=2)


def style(fig: go.Figure, title: str, x_title: str | None = None, y_title: str | None = None,
          height: int = 380) -> go.Figure:
    fig.update_layout(template="ucl", title_text=title, height=height)
    if x_title is not None:
        fig.update_xaxes(title_text=x_title)
    if y_title is not None:
        fig.update_yaxes(title_text=y_title)
    return fig


def show(streamlit, fig: go.Figure) -> None:
    streamlit.plotly_chart(fig, width="stretch", theme=None, config={"displaylogo": False, "modeBarButtonsToRemove": [
        "lasso2d", "select2d", "autoScale2d", "toggleSpikelines"]})


def club_colors(club_names: list[str]) -> dict[str, str]:
    """
    Give each club a fixed colour by its position in the list. Colours are never
    reused, so anything past the eighth club is drawn in grey.
    """
    return {name: SERIES[i] if i < len(SERIES) else MUTED_MARK for i, name in enumerate(club_names)}
