from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


STYLE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&family=Geist+Mono:wght@500;600&display=swap');

:root {
  --rab-bg: #f5f4ef;
  --rab-panel: #ffffff;
  --rab-ink: #1f2528;
  --rab-muted: #657074;
  --rab-line: #dedbd2;
  --rab-accent: #2d7f73;
  --rab-accent-soft: #e5f2ee;
  --rab-warn: #b8792b;
  --rab-danger: #b45151;
  --rab-good: #42775d;
}

html, body, [class*="css"] {
  font-family: "Geist", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.stApp {
  background:
    linear-gradient(135deg, rgba(45, 127, 115, 0.05), transparent 34rem),
    var(--rab-bg);
  color: var(--rab-ink);
}

.main .block-container {
  max-width: 1360px;
  padding: 2rem 2rem 4rem;
}

header[data-testid="stHeader"] {
  background: rgba(245, 244, 239, 0.84);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid rgba(31, 37, 40, 0.08);
}

div[data-testid="stBaseButton-primary"] button,
.stButton > button[kind="primary"],
.stDownloadButton > button[kind="primary"] {
  background: var(--rab-accent) !important;
  border-color: var(--rab-accent) !important;
  color: #ffffff !important;
}

.stButton > button,
.stDownloadButton > button {
  border-radius: 12px !important;
  min-height: 2.8rem;
  font-weight: 700;
  border-color: var(--rab-line);
  transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
}

.stButton > button:active,
.stDownloadButton > button:active {
  transform: translateY(1px) scale(0.99);
}

.stTextInput input,
.stTextArea textarea,
.stSelectbox [data-baseweb="select"],
.stMultiSelect [data-baseweb="select"] {
  border-radius: 12px;
}

.app-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, 0.9fr);
  gap: 28px;
  align-items: stretch;
  margin: 8px 0 22px;
}

.hero-copy {
  padding: 24px 0 12px;
}

.version-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border: 1px solid var(--rab-line);
  border-radius: 999px;
  color: var(--rab-muted);
  background: rgba(255, 255, 255, 0.58);
  font-size: 12px;
  font-weight: 700;
}

.app-hero h1 {
  margin: 16px 0 14px;
  color: var(--rab-ink);
  font-size: clamp(34px, 5vw, 58px);
  line-height: 0.98;
  letter-spacing: 0;
  font-weight: 800;
  max-width: 820px;
}

.hero-copy p {
  margin: 0;
  color: var(--rab-muted);
  max-width: 70ch;
  font-size: 16px;
  line-height: 1.7;
}

.hero-panel {
  border: 1px solid rgba(31, 37, 40, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 24px 60px rgba(31, 37, 40, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.8);
  padding: 18px;
}

.hero-panel-title {
  font-size: 12px;
  color: var(--rab-muted);
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: .08em;
}

.hero-panel-number {
  margin-top: 16px;
  font-family: "Geist Mono", ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 42px;
  line-height: 1;
  color: var(--rab-ink);
}

.hero-panel-line {
  height: 1px;
  background: var(--rab-line);
  margin: 16px 0;
}

.hero-panel-copy {
  color: var(--rab-muted);
  font-size: 13px;
  line-height: 1.6;
}

.section-label {
  margin: 18px 0 8px;
  color: var(--rab-muted);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 14px 0 20px;
}

.metric-card {
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid var(--rab-line);
  border-radius: 8px;
  padding: 16px;
}

.metric-number {
  font-family: "Geist Mono", ui-monospace, SFMono-Regular, Consolas, monospace;
  color: var(--rab-ink);
  font-size: 28px;
  line-height: 1.1;
  font-weight: 700;
}

.metric-label {
  margin-top: 8px;
  color: var(--rab-muted);
  font-size: 12px;
  font-weight: 700;
}

.insight-strip {
  border-top: 1px solid var(--rab-line);
  border-bottom: 1px solid var(--rab-line);
  padding: 14px 0;
  color: var(--rab-muted);
  line-height: 1.65;
}

.confidence-pill {
  display: inline-flex;
  width: fit-content;
  padding: 4px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  border: 1px solid var(--rab-line);
  background: #ffffff;
}

.level-sangat-rendah,
.level-rendah { color: var(--rab-muted); background: #f7f5ef; }
.level-sedang { color: var(--rab-warn); background: #fbf0dd; border-color: #ead7ba; }
.level-tinggi,
.level-sangat-tinggi { color: var(--rab-danger); background: #f8e8e8; border-color: #edc9c9; }

.status-note {
  border-left: 3px solid var(--rab-accent);
  background: rgba(255, 255, 255, 0.66);
  color: var(--rab-muted);
  padding: 12px 14px;
  border-radius: 0 8px 8px 0;
  line-height: 1.6;
}

.empty-state {
  border: 1px dashed var(--rab-line);
  border-radius: 8px;
  padding: 28px;
  background: rgba(255, 255, 255, 0.58);
  color: var(--rab-muted);
}

@media (max-width: 820px) {
  .main .block-container {
    padding: 1.25rem 1rem 3rem;
  }
  .app-hero,
  .metric-grid {
    grid-template-columns: 1fr;
  }
  .app-hero h1 {
    font-size: 34px;
  }
}
</style>
"""


def apply_page_config() -> None:
    st.set_page_config(
        page_title="RAB NAC Reviewer",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="collapsed",
    )


def inject_css() -> None:
    st.markdown(STYLE_CSS, unsafe_allow_html=True)


def hero(version: str, title: str, notes: str, metrics: dict[str, Any] | None = None) -> None:
    metrics = metrics or {}
    reviewed = metrics.get("total", 0)
    potential = metrics.get("potential", 0)
    top_confidence = metrics.get("top_confidence", 0)
    st.markdown(
        f"""
<section class="app-hero">
  <div class="hero-copy">
    <div class="version-pill">Versi {html.escape(version)}</div>
    <h1>RAB NAC Reviewer</h1>
    <p>{html.escape(notes)}</p>
  </div>
  <aside class="hero-panel">
    <div class="hero-panel-title">Workspace review finance</div>
    <div class="hero-panel-number">{int(reviewed)}</div>
    <div class="hero-panel-copy">Item terakhir yang masuk sesi review.</div>
    <div class="hero-panel-line"></div>
    <div class="hero-panel-copy">Potensi NAC sesi ini: <strong>{int(potential)}</strong>. Confidence tertinggi: <strong>{float(top_confidence):.1f}%</strong>.</div>
  </aside>
</section>
""",
        unsafe_allow_html=True,
    )


def metric_grid(items: list[tuple[str, str]]) -> None:
    cells = []
    for label, value in items:
        cells.append(
            "<div class='metric-card'>"
            f"<div class='metric-number'>{html.escape(str(value))}</div>"
            f"<div class='metric-label'>{html.escape(str(label))}</div>"
            "</div>"
        )
    st.markdown(f"<div class='metric-grid'>{''.join(cells)}</div>", unsafe_allow_html=True)


def section_label(label: str) -> None:
    st.markdown(f"<div class='section-label'>{html.escape(label)}</div>", unsafe_allow_html=True)


def status_note(message: str) -> None:
    st.markdown(f"<div class='status-note'>{html.escape(message)}</div>", unsafe_allow_html=True)


def empty_state(message: str) -> None:
    st.markdown(f"<div class='empty-state'>{html.escape(message)}</div>", unsafe_allow_html=True)


def confidence_pill(label: str) -> str:
    css = str(label or "").lower().replace(" ", "-")
    return f"<span class='confidence-pill level-{html.escape(css)}'>{html.escape(str(label or '-'))}</span>"


def dataframe_height(frame: pd.DataFrame, minimum: int = 220, maximum: int = 560) -> int:
    if frame is None or frame.empty:
        return minimum
    return max(minimum, min(maximum, 42 + (len(frame) + 1) * 35))


def file_download(path: str | Path) -> tuple[bytes, str]:
    path = Path(path)
    return path.read_bytes(), path.name
