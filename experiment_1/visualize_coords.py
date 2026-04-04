"""
visualize_coords.py
Batch experiment results map visualization - single HTML, Reward / Time / PDR button toggle

stat.txt structure:
  320 rows = 64 rules × 5 blocks order: Reward → Time → PDR → RewardWOG → PDRWOG
  Each row: rule_name  mean  std  95%CI_half  (2+ space delimited)
  Visualization value = mean of 64 means per block (mean of means)

Metric direction: Reward higher is better / Time·PDR lower is better
Coordinates with failed scenario generation are shown as black markers.

Usage:
    python experiment_1/visualize_coords.py
    python experiment_1/visualize_coords.py --out my_map.html
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Batch experiment results map visualization")
    p.add_argument("--progress",    default="experiment_1/progress.json")
    p.add_argument("--coords",      default="experiment_1/coords_korea.csv")
    p.add_argument("--results-dir", default=None)
    p.add_argument("--out",         default="",
                   help="Output HTML path (default: experiment_1/coords_map.html)")
    p.add_argument("--clip-pct",    type=float, default=5.0,
                   help="Colormap clipping percentile (default: 5 → 5th~95th percentile range, 0 to disable)")
    p.add_argument("--outlier-n",   type=int,   default=3,
                   help="Number of outliers on each side (default: 3 → highlight top/bottom 3, 0 to disable)")
    p.add_argument("--hist-format", choices=["png", "pdf"], default="pdf",
                   help="Histogram output format (default: pdf — vector, ideal for papers)")
    return p.parse_args()


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else _PROJECT_ROOT / p


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

def load_coords(path: Path) -> dict:
    coords = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = str(int(row["coord_id"]))
            coords[cid] = (float(row["latitude"]), float(row["longitude"]))
    return coords


def load_progress(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_results_dir(progress: dict) -> Path | None:
    for v in progress.get("statuses", {}).values():
        if v.get("status") == "done" and v.get("config_path"):
            cp = Path(v["config_path"])
            parts = cp.parts
            try:
                sce_idx = next(i for i, p in enumerate(parts) if p == "scenarios")
                exp_id  = parts[sce_idx + 1]
                rd = Path(*parts[:sce_idx]) / "results" / exp_id
                if rd.exists():
                    return rd
            except (StopIteration, IndexError):
                continue
    return None


# ---------------------------------------------------------------------------
# stat 파일 파싱
# ---------------------------------------------------------------------------

def parse_stat_means(stat_path: Path) -> dict | None:
    """
    stat.txt -> {"reward": mean, "time": mean, "pdr": mean}

    행 구조: rule_name  mean  std  95%CI_half  (2칸 이상 공백 구분)
    320행 = 64룰 × 5블록 (Reward, Time, PDR, RewardWOG, PDRWOG)
    → 블록당 64개 mean값 평균, 첫 3블록만 사용
    """
    rows = []
    with open(stat_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = re.split(r'\s{2,}', line)
            if len(parts) >= 4:
                try:
                    rows.append(float(parts[1]))
                except ValueError:
                    continue

    n = len(rows)
    if n < 3:
        return None

    # 블록 크기: 전체 행수 / 5 (소수점 반올림)
    n_rules = round(n / 5)
    if n_rules < 1:
        return None

    def block_mean(start):
        vals = rows[start: start + n_rules]
        return sum(vals) / len(vals) if vals else None

    rew = block_mean(0)
    tim = block_mean(n_rules)
    pdr = block_mean(2 * n_rules)

    if rew is None or tim is None or pdr is None:
        return None

    return {"reward": rew, "time": tim, "pdr": pdr}


# ---------------------------------------------------------------------------
# 데이터 수집
# ---------------------------------------------------------------------------

def collect_data(coords: dict, progress: dict, results_dir: Path) -> dict:
    statuses = progress.get("statuses", {})
    data = {}

    for cid, (lat, lon) in coords.items():
        entry = {"lat": lat, "lon": lon, "reward": None, "time": None, "pdr": None}
        status_info = statuses.get(cid, {})

        if status_info.get("status") != "done":
            data[cid] = entry
            continue

        config_path = status_info.get("config_path", "")
        coord_str = None
        if config_path:
            m = re.search(r'\([\d.]+,[\d.]+\)', config_path)
            if m:
                coord_str = m.group(0)
        if coord_str is None:
            coord_str = f"({lat},{lon})"

        stat_path = results_dir / coord_str / f"results_{coord_str}_stat.txt"
        if not stat_path.exists():
            data[cid] = entry
            continue

        means = parse_stat_means(stat_path)
        if means:
            entry.update(means)
        data[cid] = entry

    return data


# ---------------------------------------------------------------------------
# 컬러맵 범위 계산 (백분위수 클리핑)
# ---------------------------------------------------------------------------

def compute_ranges(data: dict, clip_pct: float) -> dict:
    """
    각 지표별 컬러맵 vmin/vmax 반환.
    clip_pct > 0이면 P(clip_pct) ~ P(100-clip_pct) 범위 사용.
    범위 밖 값은 양 극단 색상으로 고정(clamp).
    """
    import numpy as np
    ranges = {}
    for metric, label, _ in MODES:
        vals = np.array([v[metric] for v in data.values() if v[metric] is not None])
        if len(vals) == 0:
            ranges[metric] = (0.0, 1.0, 0.0, 1.0)
            continue
        true_min, true_max = float(vals.min()), float(vals.max())
        if clip_pct > 0:
            vmin = float(np.percentile(vals, clip_pct))
            vmax = float(np.percentile(vals, 100 - clip_pct))
            clip_str = f"P{clip_pct:.0f}~P{100-clip_pct:.0f}"
        else:
            vmin, vmax = true_min, true_max
            clip_str = "min~max"
        ranges[metric] = (vmin, vmax, true_min, true_max)
        print(f"  {label}: color range {clip_str} = [{vmin:.4f}, {vmax:.4f}]  "
              f"(full [{true_min:.4f}, {true_max:.4f}])")
    return ranges


# ---------------------------------------------------------------------------
# 이상치 ID 계산
# ---------------------------------------------------------------------------

def get_outlier_ids(data: dict, metric: str, outlier_n: int, high_is_good: bool):
    """
    metric 값 기준 상위 N개 / 하위 N개 coord_id 반환.
    high_is_good=True : 상위 N → 우수, 하위 N → 열악
    high_is_good=False: 하위 N → 우수, 상위 N → 열악
    반환: (good_ids: set, bad_ids: set)
    """
    if outlier_n <= 0:
        return set(), set()
    val_cid = sorted(
        ((v[metric], cid) for cid, v in data.items() if v[metric] is not None),
        key=lambda x: x[0]
    )
    if len(val_cid) == 0:
        return set(), set()
    n = min(outlier_n, len(val_cid) // 2)
    bottom_ids = {cid for _, cid in val_cid[:n]}
    top_ids    = {cid for _, cid in val_cid[-n:]}
    if high_is_good:
        return top_ids, bottom_ids    # 높음=좋음
    else:
        return bottom_ids, top_ids    # 낮음=좋음


# ---------------------------------------------------------------------------
# 색상 계산
# ---------------------------------------------------------------------------

def compute_color(val: float, vmin: float, vmax: float, high_is_good: bool) -> str:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("[ERROR] matplotlib required: pip install matplotlib")
        sys.exit(1)

    t = 0.5 if vmax == vmin else (val - vmin) / (vmax - vmin)
    if not high_is_good:
        t = 1.0 - t
    t = max(0.0, min(1.0, t))
    r, g, b, _ = plt.get_cmap("RdYlGn")(t)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


# ---------------------------------------------------------------------------
# 히스토그램 생성
# ---------------------------------------------------------------------------

HIST_CONFIG = [
    ("reward", "Reward",     True,  "RdYlGn",   "Higher is better"),
    ("time",   "Time (min)", False, "RdYlGn_r",  "Lower is better"),
    ("pdr",    "PDR",        False, "RdYlGn_r",  "Lower is better"),
]


def build_histograms(data: dict, out_path: Path, ranges: dict, clip_pct: float,
                     outlier_n: int, hist_fmt: str = "pdf"):
    """Generate histogram subplot image for each metric."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        import numpy as np
    except ImportError:
        print("[ERROR] matplotlib / numpy required: pip install matplotlib numpy")
        sys.exit(1)

    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(1, 3, figsize=(17, 5.5))
    fig.suptitle("MCI Simulation - Metric Distributions across Coordinates",
                 fontsize=13, fontweight="bold")

    for ax, (metric, label, high_is_good, cmap_name, direction) in zip(axes, HIST_CONFIG):
        vals = [v[metric] for v in data.values() if v[metric] is not None]
        if not vals:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes)
            ax.set_title(label)
            continue

        vals = np.array(vals)
        cmap_vmin, cmap_vmax, true_min, true_max = ranges[metric]
        mean_val = vals.mean()
        std_val  = vals.std()
        n = len(vals)

        # 이상치 실제 값 목록
        good_ids, bad_ids = get_outlier_ids(data, metric, outlier_n, high_is_good)
        good_vals = sorted([v[metric] for cid, v in data.items()
                            if cid in good_ids and v[metric] is not None])
        bad_vals  = sorted([v[metric] for cid, v in data.items()
                            if cid in bad_ids  and v[metric] is not None])
        outlier_vals = set(good_vals + bad_vals)

        # bin 수: 이상치가 독립 bin에 들어오도록 충분히 잘게
        # Freedman-Diaconis IQR 기반 + 최소 60
        iqr = float(np.percentile(vals, 75) - np.percentile(vals, 25))
        if iqr > 0:
            fd_width = 2 * iqr / (n ** (1/3))
            n_bins = max(60, int(np.ceil((true_max - true_min) / fd_width)))
        else:
            n_bins = 60
        n_bins = min(n_bins, 120)  # 상한

        # bar 색상: 이상치 값을 포함하는 bin → 이상치 색, 나머지 → 컬러맵
        counts, bin_edges = np.histogram(vals, bins=n_bins)
        cmap = plt.get_cmap(cmap_name)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        if cmap_vmax > cmap_vmin:
            norm_centers = np.clip(
                (bin_centers - cmap_vmin) / (cmap_vmax - cmap_vmin), 0.0, 1.0)
        else:
            norm_centers = np.full_like(bin_centers, 0.5)

        for count, left, right, nc in zip(
                counts, bin_edges[:-1], bin_edges[1:], norm_centers):
            # 이 bin 안에 이상치 값이 있는지 확인
            has_good = any(left <= v <= right for v in good_vals)
            has_bad  = any(left <= v <= right for v in bad_vals)
            if has_good:
                bar_color = OUTLIER_GOOD
            elif has_bad:
                bar_color = OUTLIER_BAD
            else:
                bar_color = cmap(nc)
            ax.bar(left, count, width=(right - left),
                   color=bar_color, edgecolor="white", linewidth=0.4, align="edge")

        # 평균 수직선 + ±1 std 음영
        ax.axvspan(mean_val - std_val, mean_val + std_val,
                   alpha=0.13, color="gray")
        ax.axvline(mean_val, color="#222222", linewidth=1.8, linestyle="--")

        # 클리핑 경계선
        if clip_pct > 0:
            for xval in (cmap_vmin, cmap_vmax):
                ax.axvline(xval, color="#555555", linewidth=1.1,
                           linestyle=":", alpha=0.8)

        # 이상치 rug plot: x축 바로 위에 개별 틱 표시
        ymax = counts.max()
        if good_vals:
            ax.plot(good_vals, [-ymax * 0.04] * len(good_vals),
                    marker='|', color=OUTLIER_GOOD, markersize=10,
                    linewidth=2, clip_on=False, zorder=5)
        if bad_vals:
            ax.plot(bad_vals, [-ymax * 0.04] * len(bad_vals),
                    marker='|', color=OUTLIER_BAD, markersize=10,
                    linewidth=2, clip_on=False, zorder=5)

        # 제목: label + 방향 안내
        ax.set_title(f"{label}  ({direction})", fontsize=11, fontweight="bold", pad=8)
        ax.set_xlabel("Value", fontsize=9)
        ax.set_ylabel("Frequency", fontsize=9)

        ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
        ax.spines[["top", "right"]].set_visible(False)

        # 통계 요약 박스 (항상 우상단)
        if clip_pct > 0:
            clip_str = (f"P{clip_pct:.0f} = {cmap_vmin:.3f}\n"
                        f"P{100-clip_pct:.0f} = {cmap_vmax:.3f}\n")
        else:
            clip_str = ""
        stats_text = (f"n = {n}\n"
                      f"min = {true_min:.3f}\n"
                      f"max = {true_max:.3f}\n"
                      f"mean = {mean_val:.3f}\n"
                      f"std  = {std_val:.3f}\n"
                      + clip_str.rstrip())
        ax.text(0.98, 0.97, stats_text,
                transform=ax.transAxes, fontsize=8, va="top", ha="right",
                bbox=dict(boxstyle="round,pad=0.45", facecolor="white",
                          edgecolor="#bbb", alpha=0.9))

        # 범례 핸들 직접 구성
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch as MPatch
        legend_handles = [
            Line2D([], [], color="#222222", linewidth=1.8, linestyle="--",
                   label=f"mean = {mean_val:.3f}"),
            MPatch(facecolor="gray", alpha=0.3, label=f"±1 std ({std_val:.3f})"),
        ]
        if clip_pct > 0:
            legend_handles.append(
                Line2D([], [], color="#555555", linewidth=1.1, linestyle=":",
                       label=f"P{clip_pct:.0f}/P{100-clip_pct:.0f} clipping"))
        if outlier_n > 0:
            legend_handles += [
                Line2D([], [], color=OUTLIER_GOOD, linewidth=1.5, linestyle="--",
                       label=f"★ Top Outliers (top {outlier_n})"),
                Line2D([], [], color=OUTLIER_BAD,  linewidth=1.5, linestyle="--",
                       label=f"▼ Bottom Outliers (bottom {outlier_n})"),
            ]
        ax.legend(handles=legend_handles, fontsize=8, loc="lower center",
                  bbox_to_anchor=(0.5, -0.30), ncol=3, frameon=True)

    fig.tight_layout(rect=[0, 0.08, 1, 0.95])
    hist_path = out_path.with_name(out_path.stem + f"_hist.{hist_fmt}")
    if hist_fmt == "pdf":
        fig.savefig(str(hist_path), bbox_inches="tight")
    else:
        fig.savefig(str(hist_path), dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  Histogram saved: {hist_path}")


# ---------------------------------------------------------------------------
# 지도 생성
# ---------------------------------------------------------------------------

MODES = [
    ("reward", "Reward",     True),   # True  = 높을수록 좋음
    ("time",   "Time (min)", False),  # False = 낮을수록 좋음
    ("pdr",    "PDR",        False),
]

GRAD_HIGH = "linear-gradient(to right, #d7191c, #fdae61, #ffffbf, #a6d96a, #1a9641)"
GRAD_LOW  = "linear-gradient(to right, #1a9641, #a6d96a, #ffffbf, #fdae61, #d7191c)"

# 이상치 전용 색상 (상/하위 N개)
OUTLIER_GOOD = "#1565C0"   # 짙은 파랑 - 우수 이상치 (상위 N개 good)
OUTLIER_BAD  = "#7B1FA2"   # 짙은 보라 - 열악 이상치 (하위 N개 bad)


def build_map(data: dict, out_path: Path, ranges: dict, clip_pct: float, outlier_n: int):
    try:
        import folium
    except ImportError:
        print("[ERROR] folium required: pip install folium")
        sys.exit(1)

    # 지도 중심
    all_lats = [v["lat"] for v in data.values()]
    all_lons = [v["lon"] for v in data.values()]
    center = [sum(all_lats) / len(all_lats), sum(all_lons) / len(all_lons)]
    m = folium.Map(location=center, zoom_start=7, tiles="OpenStreetMap")

    clip_note = f"" if clip_pct > 0 else ""

    # -----------------------------------------------------------------------
    # 모드별 마커 데이터 + 컬러바 정보 사전 계산
    # -----------------------------------------------------------------------
    js_data = {}

    for metric, label, high_is_good in MODES:
        vmin, vmax, _, _ = ranges[metric]
        valid_vals = [v[metric] for v in data.values() if v[metric] is not None]
        good_ids, bad_ids = get_outlier_ids(data, metric, outlier_n, high_is_good)

        markers = []
        good_list, bad_list = [], []   # 이상치 상세 목록 (범례용)
        for cid, v in sorted(data.items(), key=lambda x: int(x[0])):
            val = v[metric]
            if val is None:
                markers.append({
                    "lat": v["lat"], "lon": v["lon"],
                    "color": "#222222",
                    "radius": 5, "opacity": 0.7, "weight": 1,
                    "popup": f"coord_id={cid}<br>({v['lat']:.6f}, {v['lon']:.6f})<br>No data",
                    "tooltip": f"ID:{cid} | No data",
                })
            else:
                if cid in good_ids:
                    color, tag = OUTLIER_GOOD, " ★Top"
                    good_list.append({"cid": cid, "lat": v["lat"],
                                      "lon": v["lon"], "val": val})
                elif cid in bad_ids:
                    color, tag = OUTLIER_BAD, " ▼Bottom"
                    bad_list.append({"cid": cid, "lat": v["lat"],
                                     "lon": v["lon"], "val": val})
                else:
                    color, tag = compute_color(val, vmin, vmax, high_is_good), ""

                markers.append({
                    "lat": v["lat"], "lon": v["lon"],
                    "color": color,
                    "radius": 5, "opacity": 0.9, "weight": 1,
                    "popup": (f"coord_id={cid}<br>"
                              f"({v['lat']:.6f}, {v['lon']:.6f})<br>"
                              f"{label}: {val:.4f}{tag}"),
                    "tooltip": f"ID:{cid} | {label}: {val:.4f}{tag}",
                })

        # 이상치 목록: 우수는 내림차순, 열악은 오름차순 (극단 순)
        good_list.sort(key=lambda x: x["val"],
                       reverse=high_is_good)
        bad_list.sort(key=lambda x: x["val"],
                      reverse=not high_is_good)

        no_data = sum(1 for mk in markers if mk["color"] == "#222222")
        print(f"  {label}: valid={len(valid_vals)}, no_data={no_data}, "
              f"top_outliers={len(good_ids)}, bottom_outliers={len(bad_ids)}")

        if high_is_good:
            gradient    = GRAD_HIGH
            left_label  = f"{vmin:.3f} (Bad)"
            right_label = f"{vmax:.3f} (Good)"
        else:
            gradient    = GRAD_LOW
            left_label  = f"{vmin:.3f} (Good)"
            right_label = f"{vmax:.3f} (Bad)"

        js_data[metric] = {
            "markers":      markers,
            "label":        label,
            "gradient":     gradient,
            "left_label":   left_label,
            "right_label":  right_label,
            "good_outlier": len(good_ids),
            "bad_outlier":  len(bad_ids),
            "good_list":    good_list,
            "bad_list":     bad_list,
            "outlier_good_color": OUTLIER_GOOD,
            "outlier_bad_color":  OUTLIER_BAD,
        }

    # -----------------------------------------------------------------------
    # 커스텀 HTML/JS 삽입 (LayerControl 미사용)
    # -----------------------------------------------------------------------
    map_var   = m.get_name()
    data_json = json.dumps(js_data, ensure_ascii=False)

    custom_html = f"""
<!-- ===== MCI Custom Visualization UI ===== -->
<style>
  #mci-buttons {{
    position: fixed; top: 80px; right: 10px; z-index: 9999;
    background: white; padding: 10px 14px; border-radius: 8px;
    border: 2px solid #aaa; font-family: sans-serif; font-size: 13px;
    box-shadow: 2px 2px 6px rgba(0,0,0,.3);
  }}
  #mci-buttons b {{ display:block; margin-bottom:6px; }}
  .mci-btn {{
    margin: 2px; padding: 5px 14px; cursor: pointer;
    border: none; border-radius: 4px; font-size: 13px;
    background: #ddd; color: #333; transition: background .2s;
  }}
  .mci-btn.active {{ background: #2c7bb6; color: white; }}

  #mci-colorbar {{
    position: fixed; bottom: 30px; left: 50px; z-index: 9999;
    background: white; padding: 8px 12px; border-radius: 6px;
    border: 2px solid #aaa; font-family: sans-serif; font-size: 12px;
    box-shadow: 2px 2px 6px rgba(0,0,0,.3); width: 240px;
    max-height: 80vh; overflow-y: auto;
  }}
  #mci-colorbar b {{ display:block; margin-bottom:4px; }}
  #cb-gradient {{ height: 14px; border-radius: 3px; margin-bottom: 3px; }}
  #cb-labels {{ display:flex; justify-content:space-between; font-size:11px; }}
  #cb-outliers {{ margin-top: 7px; }}
  .cb-dot {{
    display: inline-block; width: 10px; height: 10px;
    border-radius: 50%; margin-right: 4px;
    border: 1.5px solid rgba(0,0,0,0.25); vertical-align: middle;
  }}
  .cb-details {{
    margin-top: 4px; border-radius: 4px; overflow: hidden;
    border: 1px solid #ddd;
  }}
  .cb-details summary {{
    cursor: pointer; padding: 4px 7px;
    font-size: 11.5px; font-weight: bold;
    list-style: none; user-select: none;
    display: flex; align-items: center; gap: 4px;
  }}
  .cb-details summary::-webkit-details-marker {{ display:none; }}
  .cb-details summary::before {{
    content: '▶'; font-size: 9px; transition: transform .2s;
  }}
  .cb-details[open] summary::before {{ transform: rotate(90deg); }}
  .cb-detail-body {{
    padding: 4px 6px 6px 6px;
    font-size: 10.5px; line-height: 1.85;
    border-top: 1px solid #eee;
    max-height: 160px; overflow-y: auto;
    background: #fafafa;
  }}
  .cb-detail-row {{
    display: flex; justify-content: space-between;
    padding: 1px 0; border-bottom: 1px solid #eee;
  }}
  .cb-detail-row:last-child {{ border-bottom: none; }}
  .cb-idx {{ color: #555; min-width: 30px; }}
  .cb-coord {{ color: #333; flex:1; text-align:center; font-size:10px; }}
  .cb-val {{ font-weight: bold; min-width: 52px; text-align:right; }}
  .cb-nodata {{
    margin-top: 5px; font-size: 11px;
    display: flex; align-items: center; gap: 4px;
  }}
</style>

<div id="mci-buttons">
  <b>Visualization Mode</b>
  <button class="mci-btn active" id="btn-reward" onclick="mciSwitch('reward')">Reward</button>
  <button class="mci-btn"        id="btn-time"   onclick="mciSwitch('time')">Time</button>
  <button class="mci-btn"        id="btn-pdr"    onclick="mciSwitch('pdr')">PDR</button>
</div>

<div id="mci-colorbar">
  <b id="cb-title">Reward</b>
  <div id="cb-gradient"></div>
  <div id="cb-labels">
    <span id="cb-left"></span>
    <span id="cb-right"></span>
  </div>
  <div id="cb-outliers">
    <details class="cb-details" id="details-good">
      <summary id="sum-good">
        <span class="cb-dot" id="dot-good"></span>
        <span id="cb-good-label"></span>
      </summary>
      <div class="cb-detail-body" id="list-good"></div>
    </details>
    <details class="cb-details" id="details-bad" style="margin-top:4px;">
      <summary id="sum-bad">
        <span class="cb-dot" id="dot-bad"></span>
        <span id="cb-bad-label"></span>
      </summary>
      <div class="cb-detail-body" id="list-bad"></div>
    </details>
    <div class="cb-nodata" id="cb-nodata-row">
      <label style="display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;">
        <input type="checkbox" id="nodata-toggle" checked onchange="mciToggleNoData()">
        <span class="cb-dot" style="background:#222222;"></span>No Data
      </label>
    </div>
  </div>
</div>

<script>
(function() {{
  var modesData = {data_json};
  var currentLayer = null;
  var currentMode  = 'reward';

  function getMap() {{
    return window["{map_var}"];
  }}

  function buildRows(items, valLabel) {{
    if (!items || items.length === 0)
      return '<div style="color:#999;padding:2px 0;">None</div>';
    return items.map(function(it) {{
      return '<div class="cb-detail-row">'
        + '<span class="cb-idx">#' + it.cid + '</span>'
        + '<span class="cb-coord">(' + it.lat.toFixed(4) + ', ' + it.lon.toFixed(4) + ')</span>'
        + '<span class="cb-val">' + it.val.toFixed(4) + '</span>'
        + '</div>';
    }}).join('');
  }}

  window.mciSwitch = function(mode) {{
    var mapObj = getMap();
    if (!mapObj) return;

    currentMode = mode;

    if (currentLayer) {{
      mapObj.removeLayer(currentLayer);
      currentLayer = null;
    }}

    var d = modesData[mode];
    var showNoData = document.getElementById('nodata-toggle').checked;
    var lg = L.layerGroup();
    d.markers.forEach(function(mk) {{
      if (!showNoData && mk.color === '#222222') return;
      L.circleMarker([mk.lat, mk.lon], {{
        radius:      mk.radius,
        color:       mk.color,
        fillColor:   mk.color,
        fillOpacity: mk.opacity,
        weight:      mk.weight || 1,
      }}).bindPopup(mk.popup).bindTooltip(mk.tooltip).addTo(lg);
    }});
    lg.addTo(mapObj);
    currentLayer = lg;

    // colorbar
    document.getElementById('cb-title').textContent = d.label;
    document.getElementById('cb-gradient').style.background = d.gradient;
    document.getElementById('cb-left').textContent  = d.left_label;
    document.getElementById('cb-right').textContent = d.right_label;

    // outlier legend + collapsible list
    document.getElementById('dot-good').style.background = d.outlier_good_color;
    document.getElementById('dot-bad').style.background  = d.outlier_bad_color;
    document.getElementById('cb-good-label').textContent =
      '★ Top Outliers (' + d.good_outlier + ')';
    document.getElementById('cb-bad-label').textContent =
      '▼ Bottom Outliers (' + d.bad_outlier + ')';
    document.getElementById('list-good').innerHTML = buildRows(d.good_list, d.label);
    document.getElementById('list-bad').innerHTML  = buildRows(d.bad_list,  d.label);

    // button style
    ['reward','time','pdr'].forEach(function(m) {{
      document.getElementById('btn-' + m).className =
        'mci-btn' + (m === mode ? ' active' : '');
    }});
  }};

  window.mciToggleNoData = function() {{
    window.mciSwitch(currentMode);
  }};

  function init() {{
    if (window["{map_var}"]) {{
      window.mciSwitch('reward');
    }} else {{
      setTimeout(init, 100);
    }}
  }}
  init();
}})();
</script>
"""

    m.get_root().html.add_child(folium.Element(custom_html))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_path))
    print(f"\n  Saved: {out_path}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print(f"\n{'='*50}")
    print(f"  MCI Results Map Visualization (single HTML)")
    print(f"{'='*50}")

    coords_path   = resolve(args.coords)
    progress_path = resolve(args.progress)

    coords   = load_coords(coords_path)
    progress = load_progress(progress_path)

    if args.results_dir:
        results_dir = resolve(args.results_dir)
    else:
        results_dir = find_results_dir(progress)
        if results_dir is None:
            print("[ERROR] Auto-detection of results folder failed. Use --results-dir option.")
            sys.exit(1)
    print(f"  results dir: {results_dir}")

    out_path = resolve(args.out) if args.out else _SCRIPT_DIR / "coords_map.html"

    print("  Collecting data...")
    data = collect_data(coords, progress, results_dir)

    print("  Computing colormap ranges...")
    ranges = compute_ranges(data, args.clip_pct)

    print("  Building map...")
    build_map(data, out_path, ranges, args.clip_pct, args.outlier_n)

    print("  Building histograms...")
    build_histograms(data, out_path, ranges, args.clip_pct, args.outlier_n,
                     hist_fmt=args.hist_format)

    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
