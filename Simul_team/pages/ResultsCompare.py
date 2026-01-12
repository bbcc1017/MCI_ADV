"""
결과 비교 전용 페이지.
- 여러 실험/좌표 결과(results_*.txt)를 불러와 다차원 시각화를 제공.
- 배치 생성 기능은 Generate 탭으로 이동.
"""
from pathlib import Path
from datetime import timedelta, timezone
import math
import re

import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
import plotly.graph_objects as go
import plotly.colors as pc

KST = timezone(timedelta(hours=9))
CLOUD_BASE_PATH = "/mount/src/mci_adv/Simul_team"
IS_CLOUD = Path(CLOUD_BASE_PATH).exists()

RAW_BLOCK_NAMES = ["Reward", "Time", "PDR", "Reward_woG", "PDR_woG"]
RAW_FLOAT = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"


def load_label_map_file(base_path: str) -> tuple[dict, dict]:
    """
    scenarios/label_map.csv -> {(exp_id, coord): label}, {coord: label}
    """
    path = Path(base_path) / "scenarios" / "label_map.csv"
    legacy_path = Path(base_path) / "results" / "label_map.csv"
    frames = []
    if path.exists():
        try:
            frames.append(pd.read_csv(path, encoding="utf-8"))
        except Exception:
            pass
    if legacy_path.exists():
        try:
            frames.append(pd.read_csv(legacy_path, encoding="utf-8"))
        except Exception:
            pass
    if not frames:
        return {}, {}
    df = pd.concat(frames, ignore_index=True)
    if {"exp_id", "coord"}.issubset(df.columns):
        df = df.drop_duplicates(subset=["exp_id", "coord"], keep="first")
    exp_coord = {}
    coord_only = {}
    for _, row in df.iterrows():
        coord = str(row.get("coord", "")).strip()
        label = str(row.get("label", "")).strip()
        exp_id = str(row.get("exp_id", "")).strip()
        if coord and label:
            if exp_id:
                exp_coord[(exp_id, coord)] = label
            coord_only[coord] = label
    if legacy_path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path, index=False, encoding="utf-8-sig")
        except Exception:
            pass
    return exp_coord, coord_only


def _split_key_vals(line: str):
    m = re.search(RAW_FLOAT, line)
    if not m:
        return line.strip(), []
    key = line[: m.start()].strip().rstrip(",")
    vals = [float(x) for x in re.findall(RAW_FLOAT, line[m.start() :])]
    return key, vals


def _split_factors(rule_label: str):
    parts = [p.strip() for p in rule_label.split(",")]
    phase = parts[0] if len(parts) > 0 else ""
    red_policy = parts[1] if len(parts) > 1 else ""

    def pick_mode(p: str, color: str):
        if not p:
            return ""
        for k in ("OnlyUAV", "OnlyAMB", "Both_UAVFirst", "Both_AMBFirst"):
            if k in p:
                return k
        toks = p.replace(",", " ").split()
        try:
            cidx = toks.index(color)
            return "_".join(toks[cidx + 1 :]) if cidx < len(toks) - 1 else ""
        except ValueError:
            return "_".join(toks[1:]) if len(toks) > 1 else ""

    red_action = pick_mode(parts[2] if len(parts) > 2 else "", "Red")
    yellow_action = pick_mode(parts[3] if len(parts) > 3 else "", "Yellow")
    return phase, red_policy, red_action, yellow_action


def _cuboid_mesh(x0: float, y0: float, z0: float, dx: float, dy: float, dz: float):
    x1 = x0 + dx
    y1 = y0 + dy
    z1 = z0 + dz
    x = [x0, x1, x1, x0, x0, x1, x1, x0]
    y = [y0, y0, y1, y1, y0, y0, y1, y1]
    z = [z0, z0, z0, z0, z1, z1, z1, z1]
    i = [0, 0, 0, 1, 1, 2, 4, 4, 5, 6, 3, 7]
    j = [1, 2, 3, 2, 5, 3, 5, 6, 6, 7, 7, 4]
    k = [2, 3, 1, 5, 6, 7, 6, 7, 4, 4, 0, 0]
    return x, y, z, i, j, k


@st.cache_data(ttl=600, show_spinner=False)
def parse_raw_results(raw_path: str) -> pd.DataFrame:
    """
    results_(lat,lon).txt -> long DF
    columns: ['exp_id','coord','rule','Phase','RedPolicy','RedAction','YellowAction','run','metric','value']
    """
    if not (raw_path and Path(raw_path).is_file()):
        return pd.DataFrame(columns=["rule","Phase","RedPolicy","RedAction","YellowAction","run","metric","value"])

    rows = []
    with open(raw_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            key, vals = _split_key_vals(raw)
            if not vals:
                continue
            rows.append((key, vals))
    if not rows:
        return pd.DataFrame(columns=["rule","Phase","RedPolicy","RedAction","YellowAction","run","metric","value"])

    first_key = rows[0][0]
    L = None
    for i in range(1, len(rows)):
        if rows[i][0] == first_key:
            L = i
            break
    if L is None:
        L = len(rows)

    n_blocks = int(math.ceil(len(rows) / L))
    out_recs = []
    for b in range(n_blocks):
        block = rows[b * L : (b + 1) * L]
        if not block:
            continue
        metric_name = RAW_BLOCK_NAMES[b] if b < len(RAW_BLOCK_NAMES) else f"Metric_{b+1}"
        R = len(block[0][1])
        for (label, vals) in block:
            Phase, RedPolicy, RedAction, YellowAction = _split_factors(label)
            rule = f"{Phase}, {RedPolicy}, Red {RedAction}, Yellow {YellowAction}".strip().replace("  ", " ")
            for r_idx, v in enumerate(vals, start=1):
                out_recs.append(
                    {
                        "rule": rule,
                        "Phase": Phase,
                        "RedPolicy": RedPolicy,
                        "RedAction": RedAction,
                        "YellowAction": YellowAction,
                        "run": r_idx,
                        "metric": metric_name,
                        "value": v,
                    }
                )
    df = pd.DataFrame.from_records(out_recs)
    if not df.empty:
        df["run"] = df["run"].astype(int)
    return df


@st.cache_data(ttl=600, show_spinner=False)
def collect_results(base_path: str, selected_exps: list[str]) -> pd.DataFrame:
    root = Path(base_path) / "results"
    if not root.exists():
        return pd.DataFrame()
    frames = []
    for exp in selected_exps:
        exp_dir = root / exp
        if not exp_dir.is_dir():
            continue
        for coord_dir in exp_dir.iterdir():
            if not coord_dir.is_dir():
                continue
            raw_path = coord_dir / f"results_{coord_dir.name}.txt"
            if not raw_path.exists():
                continue
            df = parse_raw_results(str(raw_path))
            if df.empty:
                continue
            df["exp_id"] = exp
            df["coord"] = coord_dir.name
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def list_results_experiments(base_path: str) -> list[str]:
    root = Path(base_path) / "results"
    if not root.is_dir():
        return []
    items = [p.name for p in root.iterdir() if p.is_dir()]
    items.sort(key=lambda n: (root / n).stat().st_mtime, reverse=True)
    return items


# ------------------------------
# UI
# ------------------------------
st.set_page_config(page_title="결과 비교", page_icon="📊", layout="wide")
st.title("시뮬레이션 결과 비교")
st.caption("PDR is shown as percent; PDR/Time axes are reversed so lower is better.")

# base_path
if "base_path_compare" not in st.session_state:
    st.session_state.base_path_compare = CLOUD_BASE_PATH if IS_CLOUD else ""

col_bp, = st.columns(1)
with col_bp:
    bp_input = st.text_input(
        "base_path (Simul_team 루트)",
        value=st.session_state.base_path_compare,
        placeholder="예: C:\\Users\\USER\\MCI_ADV\\Simul_team",
        disabled=IS_CLOUD,
    )
    if st.button("적용", key="btn_set_bp"):
        st.session_state.base_path_compare = bp_input.strip()
    if IS_CLOUD:
        st.info(f"Cloud 모드 감지: `{CLOUD_BASE_PATH}` 고정")
bp = st.session_state.base_path_compare
if not bp or not Path(bp).is_dir():
    st.stop()

saved_label_exp, saved_label_coord = load_label_map_file(bp)
if saved_label_coord:
    st.caption(f"label_map.csv loaded: {len(saved_label_coord)} labels")

# 저장된 라벨 매핑 파일 로드

# 라벨 매핑 입력

# 실험 선택
experiments = list_results_experiments(bp)
sel_exps = st.multiselect("결과 폴더 선택 (results/<exp_id>)", options=experiments, default=experiments[:5])

if not sel_exps:
    st.info("왼쪽에서 base_path를 설정하고 결과 폴더를 선택하세요.")
    st.stop()

metric_choices = ["Reward", "PDR", "Time", "Reward_woG", "PDR_woG"]
metric_sel = st.selectbox("주요 메트릭", metric_choices, index=0)

if st.button("결과 불러오기", type="primary"):
    df_raw = collect_results(bp, sel_exps)
    st.session_state.df_compare_raw = df_raw

df_raw = st.session_state.get("df_compare_raw", pd.DataFrame())
if df_raw.empty:
    st.warning("불러온 결과가 없습니다.")
    st.stop()

# 라벨 적용
def _resolve_label(row):
    coord = row["coord"]
    exp_id = row["exp_id"]
    if (exp_id, coord) in saved_label_exp:
        return saved_label_exp[(exp_id, coord)]
    if coord in saved_label_coord:
        return saved_label_coord[coord]
    return coord

df_raw["label"] = df_raw.apply(_resolve_label, axis=1)

df_m = df_raw[df_raw["metric"] == metric_sel].copy()
if df_m.empty:
    st.warning(f"{metric_sel} 데이터가 없습니다.")
    st.stop()

agg = (
    df_m.groupby(["label", "coord", "exp_id", "rule"])
    .agg(mean=("value", "mean"), std=("value", "std"), n=("value", "count"))
    .reset_index()
)
st.success(f"{len(agg)}개 rule 요약 로드 (행 개수 기준)")

st.markdown("#### 메트릭 요약 (표)")
st.dataframe(agg, width='stretch', hide_index=True)

st.download_button(
    "요약 CSV 다운로드",
    agg.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"results_compare_{metric_sel}.csv",
    mime="text/csv",
)

# Top-N 바
st.markdown("#### Top-N 바 차트 (평균)")
topN = st.slider("Top N", min_value=5, max_value=50, value=15, step=1)
lower_better = metric_sel in ("PDR", "Time", "PDR_woG")
top_rules = agg.sort_values("mean", ascending=lower_better).head(topN)
chart_bar = (
    alt.Chart(top_rules)
    .mark_bar()
    .encode(
        x=alt.X("mean:Q", title=f"{metric_sel} (mean)"),
        y=alt.Y("rule:N", sort="-x"),
        color="label:N",
        tooltip=["exp_id", "label", "coord", "rule", "mean", "std", "n"],
    )
    .properties(height=400)
)
st.altair_chart(chart_bar, use_container_width=True)

# Reward vs Time 산점도
st.markdown("#### Reward vs Time (평균) 산점도")
if {"Reward", "Time"}.issubset(set(df_raw["metric"].unique())):
    pivot_rt = (
        df_raw[df_raw["metric"].isin(["Reward", "Time"])]
        .groupby(["exp_id", "coord", "label", "rule", "metric"])
        .agg(mean=("value", "mean"))
        .reset_index()
        .pivot_table(index=["exp_id", "coord", "label", "rule"], columns="metric", values="mean")
        .reset_index()
    )
    scat = (
        alt.Chart(pivot_rt)
        .mark_circle(size=80, opacity=0.7)
        .encode(
            x=alt.X("Time:Q", title="Time (mean)"),
            y=alt.Y("Reward:Q", title="Reward (mean)"),
            color="label:N",
            shape="exp_id:N",
            tooltip=["exp_id", "label", "coord", "rule", "Reward", "Time"],
        )
        .properties(height=420)
        .interactive()
    )
    st.altair_chart(scat, use_container_width=True)
else:
    st.info("Reward/Time 동시 데이터가 없어 산점도를 건너뜁니다.")

# 히트맵 (rule × 라벨)
st.markdown("#### 라벨 × Rule 히트맵")
hm_base = agg.copy()
hm_base["rule_short"] = hm_base["rule"].str.slice(0, 40)
heat = (
    alt.Chart(hm_base)
    .mark_rect()
    .encode(
        x=alt.X("rule_short:N", title="Rule", sort=None),
        y=alt.Y("label:N", title="라벨"),
        color=alt.Color("mean:Q", title=f"{metric_sel} (mean)", scale=alt.Scale(scheme="blueorange")),
        tooltip=["label", "rule", "mean", "std", "n", "exp_id", "coord"],
    )
    .properties(height=400)
)
st.altair_chart(heat, use_container_width=True)

# 라벨별 박스플롯
st.markdown("#### 라벨별 분포 (박스플롯)")
box = (
    alt.Chart(df_m)
    .mark_boxplot()
    .encode(
        x=alt.X("label:N", title="라벨"),
        y=alt.Y("value:Q", title=metric_sel),
        color="label:N",
        tooltip=["label", "value", "rule", "exp_id", "coord", "run"],
    )
    .properties(height=420)
)
st.altair_chart(box, use_container_width=True)
# 3D compare (mean over all rules; x=PDR, y=Time, z=Reward)
st.markdown("#### Label 3D comparison (PDR/Time/Reward)")
metric_3d = ["PDR", "Time", "Reward"]
base_3d = df_raw[df_raw["metric"].isin(metric_3d)].copy()
if base_3d.empty:
    st.info("PDR/Time/Reward data not found; 3D comparison is unavailable.")
else:
    agg_rule = (
        base_3d.groupby(["label", "rule", "metric"]).agg(mean=("value", "mean")).reset_index()
    )
    pv_rule = (
        agg_rule.pivot_table(index=["label", "rule"], columns="metric", values="mean")
        .reindex(columns=metric_3d)
        .reset_index()
    )
    pv_rule = pv_rule.dropna(subset=metric_3d)
    if pv_rule.empty:
        st.info("PDR/Time/Reward data not found; 3D comparison is unavailable.")
    else:
        st.caption("Each label is split into rule-level cuboids. PDR is shown as percent; PDR/Time axes are reversed so lower is better.")
        label_ranges = (
            pv_rule.groupby("label")
            .agg(pdr_min=("PDR", "min"), pdr_max=("PDR", "max"),
                 time_min=("Time", "min"), time_max=("Time", "max"))
            .reset_index()
        )
        range_map = {
            r["label"]: {
                "pdr_min": float(r["pdr_min"]),
                "pdr_max": float(r["pdr_max"]),
                "time_min": float(r["time_min"]),
                "time_max": float(r["time_max"]),
            }
            for _, r in label_ranges.iterrows()
        }

        colors = pc.qualitative.Set3
        labels = list(pv_rule["label"].unique())
        color_map = {lbl: colors[i % len(colors)] for i, lbl in enumerate(labels)}
        fig = go.Figure()
        seen_labels = set()
        for idx, row in pv_rule.iterrows():
            label = row["label"]
            rule = row["rule"]
            raw_pdr = float(row["PDR"])
            raw_time = float(row["Time"])
            raw_reward = float(row["Reward"])

            lr = range_map.get(label)
            pdr_range = (lr["pdr_max"] - lr["pdr_min"]) * 100.0 if lr else 0.0
            time_range = (lr["time_max"] - lr["time_min"]) if lr else 0.0
            dx = max(pdr_range * 0.06, 0.4)
            dy = max(time_range * 0.05, 1.0)

            x_center = raw_pdr * 100.0
            y_center = raw_time
            z_val = raw_reward
            z0 = 0.0 if z_val >= 0 else z_val
            dz = abs(z_val)
            x0 = x_center - dx / 2
            y0 = y_center - dy / 2
            x, y, z, i, j, k = _cuboid_mesh(x0, y0, z0, dx, dy, dz)
            color = color_map.get(label, colors[0])
            show_legend = label not in seen_labels
            if show_legend:
                seen_labels.add(label)

            fig.add_trace(
                go.Mesh3d(
                    x=x,
                    y=y,
                    z=z,
                    i=i,
                    j=j,
                    k=k,
                    color=color,
                    opacity=0.85,
                    name=label,
                    showlegend=show_legend,
                    hovertext=(
                        f"label={label}<br>rule={rule}"
                        f"<br>PDR={raw_pdr:.4f} ({x_center:.1f}%)"
                        f"<br>Time={raw_time:.3f}<br>Reward={raw_reward:.3f}"
                    ),
                    hoverinfo="text",
                )
            )

        fig.update_layout(
            height=650,
            legend_title_text="label",
            scene=dict(
                xaxis_title="PDR (%) (lower is better)",
                yaxis_title="Time (mean, lower is better)",
                zaxis_title="Reward (mean, higher is better)",
                xaxis=dict(autorange="reversed"),
                yaxis=dict(autorange="reversed"),
                aspectmode="cube",
            ),
            margin=dict(l=0, r=0, t=30, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)
