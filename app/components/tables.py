"""
Readable tables: proper column names and number formats instead of raw database columns.

Pass a dict of {database column: (label, kind)}. Only those columns are shown,
in that order.
"""

import pandas as pd
import streamlit as st

FORMATS = {
    "int": "%d",
    "dec1": "%.1f",
    "dec2": "%.2f",
    "dec3": "%.3f",
    "signed1": "%+.1f",
    "signed2": "%+.2f",
}


def show_table(frame: pd.DataFrame, columns: dict[str, tuple[str, str]], height: int | None = None,
               help_text: dict[str, str] | None = None) -> None:
    help_text = help_text or {}
    view = frame[list(columns)].copy()
    config = {}
    for column, (label, kind) in columns.items():
        tip = help_text.get(column)
        if kind == "text":
            # Short values like "H" or "2-1" don't need a wide column.
            longest = view[column].astype(str).str.len().max() if len(view) else 0
            width = "small" if longest <= 8 else "medium"
            config[column] = st.column_config.TextColumn(label, help=tip, width=width)
        elif kind == "pct":
            # Stored as 0-1; show as a percentage.
            view[column] = view[column].astype(float) * 100
            config[column] = st.column_config.NumberColumn(label, format="%.1f%%", help=tip)
        elif kind == "prob":
            view[column] = view[column].astype(float) * 100
            config[column] = st.column_config.ProgressColumn(label, format="%.0f%%", min_value=0, max_value=100,
                                                             help=tip, width="small")
        elif kind == "date":
            config[column] = st.column_config.DateColumn(label, format="D MMM YYYY", help=tip)
        else:
            view[column] = pd.to_numeric(view[column], errors="coerce")
            # Short labels like "GF" only need a narrow column.
            width = "small" if len(label) <= 4 else None
            config[column] = st.column_config.NumberColumn(label, format=FORMATS[kind], help=tip, width=width)

    kwargs = {"height": height} if height else {}
    st.dataframe(view, column_config=config, hide_index=True, width="stretch", **kwargs)
