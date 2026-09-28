"""
Shared chart styling so every page looks the same.

Colours come from a palette that has been checked for colour-blind separation.
Series colours are handed out in a fixed order and follow the entity, so a
club keeps its colour when filters change. Scatter plots use at most the first
three colours.
"""

import plotly.graph_objects as go
import plotly.io as pio

ACCENT = "#2a78d6"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
MUTED_MARK = "#c3c2b7"
INK = "#1d1d1b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"

# Diverging scale for z-scores: blue for above average, red for below, grey in the middle.
DIVERGING = [[0.0, "#b3312f"], [0.25, "#e89a93"], [0.5, "#f0efec"], [0.75, "#86b6ef"], [1.0, "#1c5cab"]]

FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"

pio.templates["ucl"] = go.layout.Template(
    layout=dict(
        font=dict(family=FONT, size=13, color=INK_SECONDARY),
        title=dict(font=dict(size=15, color=INK), x=0, xanchor="left", pad=dict(b=8)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=SERIES,
        xaxis=dict(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, ticks="", showline=True,
                   title=dict(font=dict(size=12, color=INK_MUTED))),
        yaxis=dict(gridcolor=GRID, linecolor=AXIS, zerolinecolor=AXIS, ticks="", showline=False,
                   title=dict(font=dict(size=12, color=INK_MUTED))),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title_text="",
                    font=dict(size=12, color=INK_SECONDARY)),
        hoverlabel=dict(bgcolor="white", bordercolor=GRID, font=dict(family=FONT, size=12, color=INK)),
        margin=dict(l=8, r=8, t=56, b=8),
        bargap=0.25,
    )
)
pio.templates.default = "ucl"


def style(fig: go.Figure, title: str, x_title: str | None = None, y_title: str | None = None,
          height: int = 380) -> go.Figure:
    fig.update_layout(title_text=title, height=height)
    if x_title is not None:
        fig.update_xaxes(title_text=x_title)
    if y_title is not None:
        fig.update_yaxes(title_text=y_title)
    return fig


def show(streamlit, fig: go.Figure) -> None:
    streamlit.plotly_chart(fig, width="stretch", config={"displaylogo": False, "modeBarButtonsToRemove": [
        "lasso2d", "select2d", "autoScale2d", "toggleSpikelines"]})


def club_colors(club_names: list[str]) -> dict[str, str]:
    """
    Give each club a fixed colour by its position in the list. Colours are never
    reused, so anything past the eighth club is drawn in grey.
    """
    return {name: SERIES[i] if i < len(SERIES) else MUTED_MARK for i, name in enumerate(club_names)}
