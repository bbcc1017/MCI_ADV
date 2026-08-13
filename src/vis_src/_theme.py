"""Dispatch Console — shared visual theme for every page under ``src/vis_src``.

Single source of truth. ``MCI_Streamlit.py`` and each script in ``pages/`` used to
carry its own near-duplicate ``<style>`` block; they drifted apart and only the
main dashboard was ever fully skinned. All four now call :func:`inject_theme`.

Design notes
------------
* Instrument, not document: square corners, shared hairline rules, high density.
* Every figure is monospaced with fixed-width digits so columns never shift.
* Cyan is the only interaction colour. Red / Yellow / Green / Black are reserved
  for START triage data and are never used as decoration — see :data:`TRIAGE`.
* Nothing here hides a Streamlit control that does something. The main menu,
  the sidebar collapse/expand buttons and the page navigation all stay; only the
  deploy button and the decorative top gradient are removed.
"""

from __future__ import annotations

import streamlit as st

__all__ = ["PALETTE", "TRIAGE", "inject_theme", "page_header"]


#: Console palette. Exported so charts drawn in Python (altair / plotly / folium)
#: can be matched to the CSS without hard-coding hexes at each call site.
PALETTE = {
    "ground": "#0D1418",   # app background
    "sidebar": "#0A1013",  # sidebar, one step deeper than ground
    "panel": "#111B21",    # raised surface: metrics, expanders, table shells
    "input": "#0A1215",    # sunken surface: text fields, selects
    "rule": "#20303A",     # hairline borders
    "rule_hi": "#2C4552",  # borders that need to read as interactive
    "text": "#C9D8DF",     # primary text
    "muted": "#6B808C",    # labels, captions, axis text
    "accent": "#3BB3C4",   # interaction / selection — the only accent
    "accent_alt": "#5FD1A4",  # secondary series, "live" status
    "ok": "#3FA96B",
    "bad": "#E24B45",
}

#: START triage colours. Data only — never used for chrome, buttons or accents.
TRIAGE = {
    "red": "#E23B3B",
    "yellow": "#DFA22B",
    "green": "#2FA84F",
    "black": "#7C8894",
}


_FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=IBM+Plex+Mono:wght@400;500;600;700&"
    "family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap');"
)

# NOTE: @import must be the first thing in the stylesheet or the browser drops
# it. The previous blocks placed it after a rule, so the webfonts silently never
# loaded and everything fell back to the system sans.
_CSS = f"""<style>
{_FONT_IMPORT}

:root {{
  --dc-ground:   {PALETTE["ground"]};
  --dc-sidebar:  {PALETTE["sidebar"]};
  --dc-panel:    {PALETTE["panel"]};
  --dc-input:    {PALETTE["input"]};
  --dc-rule:     {PALETTE["rule"]};
  --dc-rule-hi:  {PALETTE["rule_hi"]};
  --dc-text:     {PALETTE["text"]};
  --dc-muted:    {PALETTE["muted"]};
  --dc-accent:   {PALETTE["accent"]};
  --dc-accent-2: {PALETTE["accent_alt"]};
  --dc-ok:       {PALETTE["ok"]};
  --dc-bad:      {PALETTE["bad"]};

  --dc-triage-red:    {TRIAGE["red"]};
  --dc-triage-yellow: {TRIAGE["yellow"]};
  --dc-triage-green:  {TRIAGE["green"]};
  --dc-triage-black:  {TRIAGE["black"]};

  --dc-sans: 'IBM Plex Sans KR', 'IBM Plex Sans', -apple-system, BlinkMacSystemFont,
             'Segoe UI', Roboto, 'Malgun Gothic', sans-serif;
  --dc-mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
}}

/* ══ preserved from the original block ══════════════════════════
   Multiselect must be allowed to fill its column; without this the
   rule-picker chips wrap into an unusable narrow strip.            */
.stMultiSelect [data-baseweb="select"] {{ max-width: 100% !important; }}

/* ══ 1. ground ══════════════════════════════════════════════════ */
html, body, .stApp,
[data-testid="stAppViewContainer"] {{
  background: var(--dc-ground);
  font-family: var(--dc-sans);
  color: var(--dc-text);
}}
.stApp {{ background: var(--dc-ground); }}

/* The header keeps both its place and its height: when the sidebar is
   collapsed, its re-open control (stExpandSidebarButton) is rendered inside
   this header. Hiding or shrinking it strands the sidebar shut. It only
   loses the deploy button and takes the ground colour so that content
   scrolling underneath the sticky toolbar stays covered. */
header[data-testid="stHeader"] {{ background: var(--dc-ground) !important; }}
[data-testid="stAppDeployButton"] {{ display: none !important; }}
footer {{ display: none !important; }}

/* The main menu is kept — it carries Rerun / Clear cache / Settings —
   but toned down so it stops reading as the loudest thing on screen. */
#MainMenu, [data-testid="stMainMenu"] {{ opacity: .45; transition: opacity .15s; }}
#MainMenu:hover, [data-testid="stMainMenu"]:hover {{ opacity: 1; }}

/* The 3.75rem header is sticky with a -40px bottom margin, so it only
   contributes ~20px of flow. Anything under ~2.5rem here puts the page
   title behind the toolbar. 3rem tightens the default and still clears. */
.block-container, [data-testid="stMainBlockContainer"] {{
  padding-top: 3rem !important;
  padding-bottom: 3rem !important;
}}

/* ══ 2. type ════════════════════════════════════════════════════ */
h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {{
  font-family: var(--dc-sans);
  color: var(--dc-text) !important;
  -webkit-text-fill-color: var(--dc-text);
  letter-spacing: -.015em;
  font-weight: 600;
}}
h1 {{
  font-family: var(--dc-mono);
  font-size: 1.6rem !important;
  font-weight: 700;
  letter-spacing: -.03em;
  text-transform: uppercase;
  border-bottom: 1px solid var(--dc-rule);
  padding-bottom: .55rem;
  margin-bottom: .2rem !important;
}}
h2, h3 {{
  border-bottom: 1px solid var(--dc-rule);
  padding-bottom: .4rem;
  margin-bottom: .9rem !important;
}}
h2::before, h3::before {{
  content: "";
  display: inline-block;
  width: 3px; height: .78em;
  background: var(--dc-accent);
  margin-right: .55em;
  vertical-align: -.04em;
}}

/* Console eyebrow used by page_header(). */
.dc-sub {{
  font-family: var(--dc-mono);
  font-size: .72rem;
  letter-spacing: .13em;
  text-transform: uppercase;
  color: var(--dc-muted);
  font-variant-numeric: tabular-nums;
  margin: .45rem 0 1.1rem;
}}
.dc-sub b {{ color: var(--dc-accent); font-weight: 500; }}

/* ══ 3. sidebar ═════════════════════════════════════════════════ */
[data-testid="stSidebar"] {{
  background: var(--dc-sidebar) !important;
  border-right: 1px solid var(--dc-rule) !important;
}}
[data-testid="stSidebar"] > div {{ padding-top: .7rem; }}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] .stMarkdown h1,
[data-testid="stSidebar"] .stMarkdown h2,
[data-testid="stSidebar"] .stMarkdown h3 {{
  font-family: var(--dc-mono) !important;
  font-size: .8rem !important;
  letter-spacing: .13em;
  text-transform: uppercase;
  color: var(--dc-muted) !important;
  -webkit-text-fill-color: var(--dc-muted);
  border-bottom: 1px solid var(--dc-rule);
  padding-bottom: .5rem;
  font-weight: 500;
}}
[data-testid="stSidebar"] h1::before,
[data-testid="stSidebar"] h2::before,
[data-testid="stSidebar"] h3::before {{ display: none; }}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {{
  font-family: var(--dc-mono) !important;
  font-size: .68rem !important;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--dc-muted) !important;
}}

/* Page navigation — this is the app's real nav, so it gets treated as one. */
[data-testid="stSidebarNav"] {{
  border-bottom: 1px solid var(--dc-rule);
  padding-bottom: .5rem;
  margin-bottom: .3rem;
}}
[data-testid="stSidebarNavLink"] {{
  border-radius: 0 !important;
  border-left: 2px solid transparent;
  padding-left: .8rem !important;
}}
[data-testid="stSidebarNavLink"] span {{
  font-family: var(--dc-mono) !important;
  font-size: .74rem !important;
  letter-spacing: .06em;
}}
[data-testid="stSidebarNavLink"]:hover {{
  background: rgba(59, 179, 196, .07) !important;
  border-left-color: var(--dc-rule-hi);
}}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: rgba(59, 179, 196, .12) !important;
  border-left-color: var(--dc-accent);
}}
[data-testid="stSidebarNavLink"][aria-current="page"] span {{
  color: var(--dc-accent) !important;
  font-weight: 600;
}}

/* ══ 4. tabs — square segmented control ═════════════════════════ */
.stTabs [data-baseweb="tab-list"] {{
  background: transparent;
  border: 1px solid var(--dc-rule);
  border-radius: 0;
  padding: 0;
  gap: 0;
  overflow-x: auto;
}}
.stTabs [data-baseweb="tab"] {{
  font-family: var(--dc-mono) !important;
  font-size: .72rem !important;
  letter-spacing: .1em;
  text-transform: uppercase;
  font-weight: 500;
  color: var(--dc-muted) !important;
  border-radius: 0 !important;
  border-right: 1px solid var(--dc-rule);
  padding: .58rem 1.25rem !important;
  transition: background .12s, color .12s;
}}
.stTabs [data-baseweb="tab"]:hover {{
  background: rgba(59, 179, 196, .08);
  color: var(--dc-text) !important;
}}
.stTabs [aria-selected="true"] {{
  background: var(--dc-accent) !important;
  color: #04171B !important;
  font-weight: 600;
}}
.stTabs [aria-selected="true"] p {{ color: #04171B !important; }}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] {{ display: none !important; }}

/* ══ 5. buttons ═════════════════════════════════════════════════ */
.stButton > button,
.stDownloadButton > button,
[data-testid="stFormSubmitButton"] > button,
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-primary"] {{
  font-family: var(--dc-mono) !important;
  font-size: .74rem !important;
  letter-spacing: .08em;
  text-transform: uppercase;
  font-weight: 500 !important;
  border-radius: 0 !important;
  border: 1px solid var(--dc-rule-hi) !important;
  background: var(--dc-panel) !important;
  color: var(--dc-text) !important;
  padding: .48rem 1.1rem !important;
  transition: background .12s, border-color .12s, color .12s;
}}
.stButton > button:hover,
.stDownloadButton > button:hover,
[data-testid="stFormSubmitButton"] > button:hover {{
  border-color: var(--dc-accent) !important;
  color: var(--dc-accent) !important;
  background: rgba(59, 179, 196, .1) !important;
}}
.stButton > button[kind="primary"],
[data-testid="stBaseButton-primary"] {{
  background: var(--dc-accent) !important;
  border-color: var(--dc-accent) !important;
  color: #04171B !important;
  font-weight: 600 !important;
}}
.stButton > button[kind="primary"]:hover,
[data-testid="stBaseButton-primary"]:hover {{
  background: #4AC6D7 !important;
  color: #04171B !important;
}}
.stButton > button:focus-visible,
[data-testid="stFormSubmitButton"] > button:focus-visible {{
  outline: 2px solid var(--dc-accent) !important;
  outline-offset: 1px;
}}

/* ══ 6. inputs ══════════════════════════════════════════════════ */
[data-baseweb="input"],
[data-baseweb="textarea"],
[data-baseweb="select"] > div,
.stTextInput > div > div,
.stNumberInput > div > div,
.stDateInput > div > div {{
  background: var(--dc-input) !important;
  border: 1px solid var(--dc-rule) !important;
  border-radius: 0 !important;
  transition: border-color .12s;
}}
[data-baseweb="input"] input,
[data-baseweb="textarea"] textarea,
[data-baseweb="select"] input {{
  font-family: var(--dc-mono) !important;
  font-size: .82rem !important;
  color: var(--dc-text) !important;
}}
[data-baseweb="input"]:focus-within,
[data-baseweb="textarea"]:focus-within,
[data-baseweb="select"] > div:focus-within {{
  border-color: var(--dc-accent) !important;
  box-shadow: none !important;
}}
[data-baseweb="popover"], [data-baseweb="menu"] {{
  border-radius: 0 !important;
  background: var(--dc-panel) !important;
  border: 1px solid var(--dc-rule-hi) !important;
}}
[data-baseweb="menu"] li {{ font-family: var(--dc-mono) !important; font-size: .8rem !important; }}
/* Multiselect chips read as callsigns, not pills. */
[data-baseweb="tag"] {{
  border-radius: 0 !important;
  background: rgba(59, 179, 196, .13) !important;
  border: 1px solid var(--dc-accent) !important;
  color: var(--dc-accent) !important;
  font-family: var(--dc-mono) !important;
  font-size: .72rem !important;
}}
[data-baseweb="tag"] span {{ color: var(--dc-accent) !important; }}

/* Widget labels outside the sidebar stay sentence case but pick up the
   mono/uppercase treatment for the label line only. */
[data-testid="stWidgetLabel"] p {{
  font-family: var(--dc-mono);
  font-size: .72rem;
  letter-spacing: .07em;
  color: var(--dc-muted);
}}

/* ══ 7. metrics — cells in a shared grid, not floating cards ════ */
[data-testid="stMetric"] {{
  background: var(--dc-panel);
  border: 1px solid var(--dc-rule);
  border-radius: 0;
  padding: .8rem .95rem .75rem;
}}
[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] p {{
  font-family: var(--dc-mono) !important;
  font-size: .66rem !important;
  letter-spacing: .13em;
  text-transform: uppercase;
  color: var(--dc-muted) !important;
}}
[data-testid="stMetricValue"] {{
  font-family: var(--dc-mono) !important;
  font-weight: 700 !important;
  letter-spacing: -.035em;
  font-variant-numeric: tabular-nums;
  color: var(--dc-text) !important;
}}
[data-testid="stMetricDelta"] {{
  font-family: var(--dc-mono) !important;
  font-size: .72rem !important;
  font-variant-numeric: tabular-nums;
}}
/* Collapse the gap so a metric row reads as one bordered strip. Guarded by
   :has(), so browsers without it simply keep the default spacing. */
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {{ gap: 0 !important; }}
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"])
  [data-testid="stColumn"] + [data-testid="stColumn"] [data-testid="stMetric"] {{
  margin-left: -1px;
}}

/* ══ 8. tables ══════════════════════════════════════════════════ */
[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"],
[data-testid="stTable"], .stDataFrame {{
  border: 1px solid var(--dc-rule) !important;
  border-radius: 0 !important;
}}
/* Markdown tables are plain DOM, so these get the full treatment. */
[data-testid="stMarkdownContainer"] table {{
  border-collapse: collapse;
  font-family: var(--dc-mono);
  font-size: .8rem;
  font-variant-numeric: tabular-nums;
  width: 100%;
}}
[data-testid="stMarkdownContainer"] th {{
  font-size: .68rem;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--dc-muted);
  font-weight: 500;
  border-bottom: 1px solid var(--dc-rule-hi);
  padding: .45rem .7rem;
  text-align: left;
}}
[data-testid="stMarkdownContainer"] td {{
  border-top: 1px solid var(--dc-rule);
  padding: .4rem .7rem;
}}

/* ══ 9. containers ══════════════════════════════════════════════ */
[data-testid="stExpander"] {{
  background: var(--dc-panel);
  border: 1px solid var(--dc-rule) !important;
  border-radius: 0 !important;
}}
[data-testid="stExpanderDetails"] {{ background: var(--dc-panel); }}
[data-testid="stExpander"] summary {{
  font-family: var(--dc-mono) !important;
  font-size: .76rem !important;
  letter-spacing: .06em;
}}
[data-testid="stExpander"]:hover {{ border-color: var(--dc-rule-hi) !important; }}
[data-testid="stVerticalBlockBorderWrapper"] > div[style*="border"] {{ border-radius: 0 !important; }}

hr {{
  border-color: var(--dc-rule) !important;
  margin: 1.3rem 0 !important;
}}

/* ══ 10. status ═════════════════════════════════════════════════ */
.stAlert, [data-testid="stAlert"], [data-baseweb="notification"] {{
  border-radius: 0 !important;
  border: 1px solid var(--dc-rule-hi);
  border-left-width: 3px;
}}

.stProgress > div > div {{ border-radius: 0 !important; }}
.stProgress > div > div > div {{ background: var(--dc-accent) !important; border-radius: 0 !important; }}

[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] small {{
  color: #93A5AF !important;
  font-family: var(--dc-mono);
  font-size: .72rem;
}}

code, pre, [data-testid="stCode"], [data-testid="stMarkdownPre"] {{
  font-family: var(--dc-mono) !important;
  border-radius: 0 !important;
}}
pre, [data-testid="stCode"], [data-testid="stMarkdownPre"] {{
  background: var(--dc-input) !important;
  border: 1px solid var(--dc-rule) !important;
}}
code {{ color: var(--dc-accent-2) !important; }}

/* ══ 11. controls ═══════════════════════════════════════════════ */
.stCheckbox label:hover, .stRadio label:hover {{ color: var(--dc-accent) !important; }}
[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {{ border-radius: 0 !important; }}
[data-testid="stFileUploader"] section {{
  border-radius: 0 !important;
  border: 1px dashed var(--dc-rule-hi) !important;
  background: var(--dc-input) !important;
}}
[data-testid="stFileUploaderDropzoneInstructions"] span {{ font-family: var(--dc-mono); font-size: .76rem; }}

/* ══ 12. embedded frames ════════════════════════════════════════
   folium / plotly render into iframes; only the shell is ours.    */
iframe[title="streamlit_folium.st_folium"],
[data-testid="stIFrame"], iframe {{ border: 1px solid var(--dc-rule); }}

::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: var(--dc-ground); }}
::-webkit-scrollbar-thumb {{ background: var(--dc-rule-hi); border-radius: 0; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--dc-accent); }}

@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}
</style>"""


def inject_theme() -> None:
    """Apply the Dispatch Console stylesheet. Call once, right after
    ``st.set_page_config``, on every page."""
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None) -> None:
    """Render the console title block.

    ``subtitle`` is rendered as the monospaced status line under the rule and
    may contain ``<b>`` to pick out a value in the accent colour.
    """
    st.markdown(f"<h1>{title}</h1>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="dc-sub">{subtitle}</div>', unsafe_allow_html=True)
