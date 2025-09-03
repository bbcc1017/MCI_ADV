# MCI_Streamlit.py — Patched (upgrade-in-place, v4)
# 기존 대시보드 구조를 유지하면서, 요청 사항을 반영한 "추가/보강" 패치입니다.
# Python 3.9 / Streamlit 1.34+ / folium / streamlit-folium / altair / pandas / openpyxl /
# (선택) statsmodels, scipy
# -------------------------------------------------------------------------------------------------
# ✅ 이번 패치 반영 요약
# 1) Settings: 좌표 선택 시 사이드바 하단 미니맵(현재 좌표 위치 한눈 파악)
# 2) Scenarios: experiment_logs/<coord> 범위로 로그 선택 제한, Rule 블록 파서 복구
#    - (Unlabeled) 블록은 드롭다운에서 숨김 + 원인 코멘트 표기
#    - 환자 중심 요약표(구조시각/이송수단/병원/도착시각/치료완료/특이사항) + 전체 이벤트 표 유지
# 3) Maps: 멀티선택(앞 3자리 인덱스), 전체선택/해제 버튼, amb_info 환자수만큼 제한
#    - UAV 경로 표시 토글(단일 토글로 출동/이송 동시 제어)
#    - UAV 출동: 상급종합(종별코드=1)→사고지점(보라 점선) / UAV 이송: 사고→모든 병원(청록 점선)
#    - 동일 병원 출동·이송 겹침 시 이송선에 소폭 오프셋 적용(겹침 완화)
#    - 범례에 AMB 혼잡도 색/ UAV 점선 샘플 + (가능 시) YAML의 AMB/UAV 속도 표기
#    - 경로 요약(거리 km, 시간 분) 팝업에 삽입, duration(ms) → 분 보정
# 4) Analytics: 상단 원본 표 유지 + "정렬 기준" 선택(Reward↓, PDR↑(작을수록 좋음), Time↑(짧을수록 좋음))로 전체 표 재정렬
#    - 히트맵/막대 그래프 제거 → 대신 ANOVA 스위트 추가(Full Factorial, M1=Reward 기본)
#      · raw(results_{coord}.txt) 파싱 → Phase, RedPolicy, RedAction, YellowAction × Sample
#      · statsmodels 있으면 OLS+Type-II ANOVA, 잔차 정규성(Shapiro)·QQ 스캐터·잔차 히스토그램 제공
# 5) Data Tables: 편집 대상 셀렉터에 파일명만 노출(경로 숨김), "안전센터와 소방서.csv"는 편집 목록에서 제외
# -------------------------------------------------------------------------------------------------

import os, re, json, shutil, subprocess, math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple, Optional, Union

import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
import folium
from streamlit_folium import st_folium
from openpyxl import load_workbook  # dependency ensure
import yaml

# (선택) 통계 패키지
try:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    HAS_SM = True
except Exception:
    HAS_SM = False
try:
    from scipy import stats as scistats
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False

KST = timezone(timedelta(hours=9))

# ------------------------------
# Session defaults
# ------------------------------
if "base_path" not in st.session_state:
    st.session_state.base_path = ""
if "selected_exp" not in st.session_state:
    st.session_state.selected_exp = ""
if "selected_coord" not in st.session_state:
    st.session_state.selected_coord = ""
if "ps_running" not in st.session_state:
    st.session_state.ps_running = False
if "py_running" not in st.session_state:
    st.session_state.py_running = False

# ------------------------------
# Helpers: paths & IO
# ------------------------------

def norm(p: Union[str, Path]) -> str:
    return os.path.normpath(os.path.abspath(os.path.expanduser(str(p))))

def ts() -> str:
    return datetime.now(KST).strftime("%Y%m%d_%H%M%S")

def exists_dir(p: Union[str, Path]) -> bool:
    return os.path.isdir(str(p))

def exists_file(p: Union[str, Path]) -> bool:
    return os.path.isfile(str(p))

def base_ok(base_path: str) -> bool:
    s = Path(base_path)
    return s.is_dir() and (s / "scenarios").is_dir()

# --- NEW: scenarios + results 통합 실험 목록 (scenarios 우선) ---
def list_experiments_any(base_path: str) -> List[str]:
    res_root = Path(base_path) / "results"
    scn_root = Path(base_path) / "scenarios"
    names = set()
    if scn_root.is_dir():
        names |= {p.name for p in scn_root.iterdir() if p.is_dir()}
    if res_root.is_dir():
        names |= {p.name for p in res_root.iterdir() if p.is_dir()}
    items = list(names)

    # 최신 수정시각 기준 정렬 (scenarios와 results 중 더 최근 것을 반영)
    def mtime(name: str) -> float:
        t1 = (scn_root / name).stat().st_mtime if (scn_root / name).exists() else 0.0
        t2 = (res_root / name).stat().st_mtime if (res_root / name).exists() else 0.0
        return max(t1, t2)

    items.sort(key=mtime, reverse=True)
    return items

# --- NEW: 특정 실험의 좌표 목록 (scenarios 기준) ---
def list_coords_from_scenarios(base_path: str, exp_id: str) -> List[str]:
    root = Path(base_path) / "scenarios" / exp_id
    if not root.is_dir():
        return []
    items = [p.name for p in root.iterdir() if p.is_dir() and re.match(r"^\(.*\)$", p.name)]
    items.sort()
    return items




# results/exp_* 레이아웃

def list_experiments(base_path: str) -> List[str]:
    root = Path(base_path) / "results"
    if not root.is_dir():
        return []
    items = [p.name for p in root.iterdir() if p.is_dir()]
    items.sort(key=lambda name: (root / name).stat().st_mtime, reverse=True)
    return items


def list_coords(base_path: str, exp_id: str) -> List[str]:
    root = Path(base_path) / "results" / exp_id
    if not root.is_dir():
        return []
    items = [p.name for p in root.iterdir() if p.is_dir() and re.match(r"^\(.*\)$", p.name)]
    items.sort()
    return items


def find_yaml_in_coord(base_path: str, exp_id: str, coord: str) -> Optional[str]:
    folder = Path(base_path) / "scenarios" / exp_id / coord
    if not folder.is_dir():
        return None
    yamls = list(folder.glob("*.yaml"))
    return str(yamls[0]) if yamls else None


def coord_to_tuple(coord_name: str) -> Optional[Tuple[float,float]]:
    m = re.match(r"^\(([-\d\.]+),\s*([-\d\.]+)\)$", coord_name)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))  # (lat, lon)


def coord_center(coord_name: str) -> Tuple[float,float]:
    t = coord_to_tuple(coord_name)
    if not t:
        return (37.5665, 126.9780)  # Seoul fallback
    return t


def get_routes_dirs(base_path: str, exp_id: str, coord: str) -> Dict[str, Path]:
    r = Path(base_path) / "scenarios" / exp_id / coord / "routes"
    return {
        "center2site": r / "center2site",
        "hos2site": r / "hos2site",
    }


def load_json_files(folder: Path, limit: Optional[int]=None) -> List[dict]:
    if not folder.is_dir():
        return []
    files = sorted(folder.glob("*.json"))
    if limit is not None:
        files = files[:limit]
    out = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
            obj["_file"] = str(f)
            out.append(obj)
        except Exception as e:
            print(f"[WARN] JSON load failed: {f} ({e})")
    return out


def read_csv_smart(path: str) -> pd.DataFrame:
    if os.path.basename(path) == "안전센터와 소방서.csv":
        return pd.read_csv(path, encoding="cp949")
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.read_csv(path, encoding="utf-8", errors="ignore")


def write_csv_smart(df: pd.DataFrame, path: str):
    b = f"{os.path.splitext(path)[0]}_backup_{ts()}.csv"
    shutil.copy2(path, b) if exists_file(path) else None
    if os.path.basename(path) == "안전센터와 소방서.csv":
        df.to_csv(path, index=False, encoding="cp949")
    else:
        df.to_csv(path, index=False, encoding="utf-8-sig")

# 병원 엑셀: 우선순위 1) base_path/엑셀 결합 데이터.xlsx  2) base_path/scenarios/엑셀 결합 데이터.xlsx

def read_excel_hospital(base_path: str) -> Optional[pd.DataFrame]:
    cands = [
        Path(base_path) / "엑셀 결합 데이터.xlsx",
        Path(base_path) / "scenarios" / "엑셀 결합 데이터.xlsx",
    ]
    for excel_path in cands:
        if excel_path.is_file():
            try:
                df = pd.read_excel(excel_path, engine="openpyxl")
                return df
            except Exception as e:
                st.warning(f"엑셀 로드 실패: {excel_path} ({e})")
    return None

def read_experiment_summary_csv(base_path: str, exp_id: str) -> Optional[pd.DataFrame]:
    folder = Path(base_path) / "scenarios" / exp_id
    if not folder.is_dir():
        return None
    cand1 = folder / "summary.csv"
    if cand1.is_file():
        for enc in ("utf-8-sig","cp949","utf-8"):
            try:
                return pd.read_csv(cand1, encoding=enc)
            except Exception:
                pass
    picks = sorted(folder.glob("*_summary.csv"))
    for p in picks:
        for enc in ("utf-8-sig","cp949","utf-8"):
            try:
                return pd.read_csv(p, encoding=enc)
            except Exception:
                continue
    return None

def summarize_experiment(df: pd.DataFrame) -> Tuple[Dict[str,str], Optional[str]]:
    info, addr = {}, None
    if df is None or df.empty: return info, addr
    # 주소 후보
    addr_cols = [c for c in df.columns if any(k in str(c) for k in ["주소","address","site_addr","사고지점"])]
    if addr_cols:
        addr = str(df.iloc[0][addr_cols[0]])
    # 파라미터 후보
    keys = ["seed","patients","amb","uav","hospital","policy","rule","speed","radius","duration","start","api","grid"]
    for c in df.columns:
        if any(k in str(c).lower() for k in keys):
            v = df.iloc[0][c]
            if pd.notna(v): info[str(c)] = str(v)
    if len(df.columns)==2 and df.columns[0]!=df.columns[1]:
        for _,r in df.iterrows():
            k,v = str(r.iloc[0]), str(r.iloc[1])
            if any(t in k.lower() for t in keys) and v:
                info[k]=v
            if addr is None and ("주소" in k or "address" in k.lower()):
                addr = v
    return info, addr

def summarize_experiment_extended(df: Optional[pd.DataFrame]) -> Tuple[Dict[str,str], Dict[str,str]]:
    site_info = {"좌표":"","주소":"","도로명 주소":""}
    sim_info: Dict[str,str] = {}
    if df is None or df.empty: return site_info, sim_info
    addr_cols = [c for c in df.columns if ("주소" in str(c) and "도로" not in str(c)) or "address" in str(c).lower()]
    road_cols = [c for c in df.columns if "도로명" in str(c)]
    if addr_cols:
        v = df.iloc[0][addr_cols[0]]; site_info["주소"] = "" if pd.isna(v) else str(v)
    if road_cols:
        v = df.iloc[0][road_cols[0]]; site_info["도로명 주소"] = "" if pd.isna(v) else str(v)
    start_idx = None
    for i,c in enumerate(df.columns):
        if "시나리오생성_시작" in str(c):
            start_idx = i; break
    if start_idx is not None:
        row = df.iloc[0, start_idx:]
        for k,v in row.items():
            if pd.notna(v): sim_info[str(k)] = str(v)
    return site_info, sim_info


def list_coord_csvs(base_path: str, exp_id: str, coord: str) -> List[str]:
    folder = Path(base_path) / "scenarios" / exp_id / coord
    return [str(p) for p in folder.glob("*.csv")]


def results_stat_path(base_path: str, exp_id: str, coord: str) -> Optional[str]:
    s = Path(base_path) / "results" / exp_id / coord / f"results_{coord}_stat.txt"
    return str(s) if s.is_file() else None


def results_raw_path(base_path: str, exp_id: str, coord: str) -> Optional[str]:
    s = Path(base_path) / "results" / exp_id / coord / f"results_{coord}.txt"
    return str(s) if s.is_file() else None


def get_patient_count(base_path: str, exp_id: str, coord: str) -> Optional[int]:
    folder = Path(base_path) / "scenarios" / exp_id / coord
    for cand in ["amb_info.csv", "amb_info_road.csv", "patient_info.csv"]:
        fp = folder / cand
        if fp.is_file():
            try:
                df = read_csv_smart(str(fp))
                return len(df.index)
            except Exception:
                pass
    return None

# ------------------------------
# Logs (실행 로그 탐색 + 파싱)
# ------------------------------
PHASES = ["START", "ReSTART"]
RED_POLICY = ["RedOnly", "YellowHalf"]
ACTIONS = ["OnlyUAV","Both_UAVFirst","Both_AMBFirst","OnlyAMB"]

RULE_HEADER_RE = re.compile(r"^(START|ReSTART)\s*,\s*(.+?)\s*$")
TUPLE_LINE_RE = re.compile(r"^\(\s*([-\d\.]+)\s*,\s*(\d+)\s*,\s*'([A-Za-z_]+)'\s*,\s*\(([^)]*)\)\s*\)\s*$")
ACTION_RE = re.compile(r"^Action:\s*\[([^\]]+)\]")

# Iteration 라인 파싱 (예: "Iter : 3" 또는 "Iteration: 3")
ITER_RE = re.compile(r'^\s*(?:Iter(?:ation)?\s*[:=]\s*)(\d+)\b', re.I)


EV_ARG_PARSERS = {
    "p_rescue": lambda args: {"p": int(args[0])} if len(args)>=1 else {},
    "amb_arrival_site": lambda args: {"a": int(args[0])} if len(args)>=1 else {},
    "uav_arrival_site": lambda args: {"u": int(args[0])} if len(args)>=1 else {},
    "amb_arrival_hospital": lambda args: {"p": int(args[0]), "a": int(args[1]), "h": int(args[2])} if len(args)>=3 else {},
    "uav_arrival_hospital": lambda args: {"p": int(args[0]), "u": int(args[1]), "h": int(args[2])} if len(args)>=3 else {},
    "p_care_ready": lambda args: {"p": int(args[0]), "h": int(args[1])} if len(args)>=2 else {},
    "p_def_care": lambda args: {"p": int(args[0]), "h": int(args[1])} if len(args)>=2 else {},
}

ACTION_TOOLTIP_MD = (
    "**Action 인덱스 해석**\n"
    "- `action[0] = p_class` → 환자 중증도 (0=Red, 1=Yellow, 2=Green)\n"
    "- `action[1] = destination` → 0=현장대기, 1…N → 병원 index+1\n"
    "- `action[2] = mode` → 0=AMB(구급차), 1=UAV"
)


def _read_text_any(path: str) -> str:
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        with open(path, "r", encoding="cp949", errors="ignore") as f:
            return f.read()

# Rule 블록 파서 (v3 재도입)
def parse_log_blocks(log_text: str) -> List[Dict]:
    blocks = []
    cur_iter = None                         # ← [추가] 현재 Iter 저장
    cur = {"rule": "(Unlabeled)", "iter": cur_iter, "events": [], "actions": []}  # ← [변경]

    for raw in log_text.splitlines():
        s = raw.strip()
        if not s:
            continue

        # [추가] Iter 라인 먼저 체크
        miter = ITER_RE.match(s)
        if miter:
            cur_iter = int(miter.group(1))
            # 진행 중 블록에도 iter 주입(없으면/None이면 갱신)
            if "iter" not in cur or cur.get("iter") is None:
                cur["iter"] = cur_iter
            continue

        mhead = RULE_HEADER_RE.match(s)
        if mhead:
            if cur["events"] or cur["actions"] or cur["rule"] != "(Unlabeled)":
                blocks.append(cur)
            # [변경] 새 블록에도 현재 iter 동봉
            cur = {"rule": s, "iter": cur_iter, "events": [], "actions": []}
            continue

        ma = ACTION_RE.match(s)
        if ma:
            try:
                parts = [x.strip() for x in ma.group(1).split(',')]
                vec = [int(x) for x in parts if x != '']
                cur["actions"].append(vec)
            except Exception:
                pass
            continue

        mt = TUPLE_LINE_RE.match(s)
        if mt:
            t = float(mt.group(1)); eid = int(mt.group(2)); ev = mt.group(3)
            args = [x.strip() for x in mt.group(4).split(',') if x.strip() != '']
            try:
                args = [int(a) for a in args]
            except Exception:
                pass
            rec = {"t": t, "eid": eid, "ev": ev, "p": None, "a": None, "u": None, "h": None}
            if ev in EV_ARG_PARSERS:
                rec.update(EV_ARG_PARSERS[ev](args))
            cur["events"].append(rec)
            continue

    if cur["events"] or cur["actions"] or cur["rule"] != "(Unlabeled)":
        blocks.append(cur)
    return blocks


# 환자 중심 요약

def build_patient_summary(events: List[Dict]) -> pd.DataFrame:
    byp: Dict[int, Dict] = {}
    arrival_hist: Dict[int, List[Tuple[str,int,float]]] = {}
    for e in sorted(events, key=lambda r: r["t"]):
        ev = e.get("ev"); p = e.get("p"); h = e.get("h")
        if ev == "p_rescue" and p is not None:
            byp.setdefault(p, {}).setdefault("rescue_t", e["t"])
        elif ev in ("amb_arrival_hospital","uav_arrival_hospital") and p is not None:
            mode = "AMB" if ev.startswith("amb_") else "UAV"
            if p not in byp:
                byp[p] = {}
            if "arrive_t" not in byp[p]:
                byp[p]["arrive_t"] = e["t"]; byp[p]["mode"] = mode; byp[p]["hospital"] = h
            arrival_hist.setdefault(p, []).append((mode, h, e["t"]))
        elif ev == "p_care_ready" and p is not None:
            byp.setdefault(p, {}).setdefault("care_ready_t", e["t"])
        elif ev == "p_def_care" and p is not None:
            byp.setdefault(p, {}).setdefault("def_care_t", e["t"])
    rows = []
    for p, info in sorted(byp.items(), key=lambda kv: kv[0]):
        hist = arrival_hist.get(p, [])
        remark = "정상처리"
        if len(hist) >= 2:
            hosp_set = {h for (_,h,_) in hist}; mode_set = {m for (m,_,_) in hist}
            if len(hosp_set) > 1 or len(mode_set) > 1:
                remark = "divert"
        rows.append({
            "환자ID": p,
            "구조시각": info.get("rescue_t"),
            "이송수단": info.get("mode"),
            "도착 병원": info.get("hospital"),
            "병원도착시각": info.get("arrive_t"),
            "치료대기완료": info.get("care_ready_t"),
            "치료완료시각": info.get("def_care_t"),
            "특이사항": remark,
        })
    return pd.DataFrame(rows)

# experiment_logs 내 파일만 고르도록 제한

def _extract_ts(exp_id: str) -> str:
    m = re.search(r"(\d{8}_\d{6})", exp_id or "")
    return m.group(1) if m else ""


def experiment_log_candidates(base_path: str, exp_id: str, coord: str) -> List[str]:
    """experiment_logs 폴더에서 <coord>_*.log|.txt만 수집 (exp_id 타임스탬프 필터 제거)."""
    logs_folder = Path(base_path) / "experiment_logs"
    if not logs_folder.is_dir():
        return []
    cprefix = f"{coord}_"
    files = [p for p in logs_folder.iterdir()
             if p.is_file() and p.name.startswith(cprefix)
             and p.suffix.lower() in (".log", ".txt")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p) for p in files]


# ------------------------------
# 지도 보조 (혼잡도/범례/UAV/요약)
# ------------------------------
CONG_COLORS = {0:"#888888", 1:"#7CFC00", 2:"#FFD700", 3:"#FF0000"}
CONG_LABELS = {0:"값없음", 1:"원활", 2:"서행", 3:"혼잡"}
UAV_OUT_COLOR = "#8A2BE2"   # 출동(병원→사고)
UAV_BACK_COLOR = "#00CED1"  # 이송(사고→병원)

ROADTYPE_TO_KIND = {1:"고속도로", 2:"도시고속", 3:"국도"}
SPEED_THRESHOLDS = {
    "일반도로": {"원활":30, "서행_low":15, "서행_high":30, "혼잡":15},
    "국도":     {"원활":40, "서행_low":20, "서행_high":40, "혼잡":20},
    "도시고속": {"원활":60, "서행_low":30, "서행_high":60, "혼잡":30},
    "고속도로": {"원활":70, "서행_low":40, "서행_high":70, "혼잡":40},
}


def _classify_cong_by_speed(road_kind: str, speed_kmh: Optional[float]) -> Optional[int]:
    if speed_kmh is None:
        return None
    kind = road_kind if road_kind in SPEED_THRESHOLDS else "일반도로"
    th = SPEED_THRESHOLDS[kind]
    if speed_kmh >= th["원활"]:  # 원활
        return 1
    if th["서행_low"] <= speed_kmh < th["서행_high"]:  # 서행
        return 2
    if speed_kmh < th["혼잡"]:  # 혼잡
        return 3
    return None


def _haversine_km(lat1, lon1, lat2, lon2):
    R=6371.0
    from math import radians, sin, cos, sqrt, atan2
    phi1,phi2=radians(lat1),radians(lat2)
    dphi=radians(lat2-lat1); dl=radians(lon2-lon1)
    a=sin(dphi/2)**2+cos(phi1)*cos(phi2)*sin(dl/2)**2
    return 2*R*atan2(math.sqrt(a), math.sqrt(1-a))


def _extract_summary_meta(obj: dict) -> Tuple[Optional[float], Optional[float], list]:
    payload = (obj.get("payload") or {}).get("naver_response", {})
    route_list = payload.get("route", {}).get("trafast", [])
    if not route_list:
        return None, None, []
    r0 = route_list[0]
    summ = r0.get("summary", {})
    dist_km = (float(summ.get("distance", 0)) / 1000.0) if summ else None
    dur_min = (float(summ.get("duration", 0)) / 60000.0) if summ else None
    guide = r0.get("guide", []) or []
    return dist_km, dur_min, guide


def _guide_html(guide: list) -> str:
    if not guide:
        return ""
    rows = ["<details><summary>🧭 경로 안내(클릭)</summary><ol style='padding-left:16px;'>"]
    for g in guide[:200]:
        inst = str(g.get("instructions", "")).replace("<", "&lt;").replace(">", "&gt;")
        gd = float(g.get("distance", 0))/1000.0 if g.get("distance") is not None else None
        gm = float(g.get("duration", 0))/60000.0 if g.get("duration") is not None else None
        tail = []
        if gd is not None and gd>0: tail.append(f"{gd:.2f} km")
        if gm is not None and gm>0: tail.append(f"{gm:.1f} 분")
        rows.append(f"<li>{inst} {' · '.join(tail) if tail else ''}</li>")
    rows.append("</ol></details>")
    return "".join(rows)


def add_site_marker(m: folium.Map, site_latlon: Tuple[float,float]):
    
    folium.CircelMarker(
        location=[site_latlon[0], site_latlon[1]],
        icon=folium.Icon(color="purple", icon="map-pin", prefix="fa"),
        radius =  10,
        tooltip="사고지점",
        popup=f"사고지점<br>lat,lon={site_latlon[0]:.6f},{site_latlon[1]:.6f}"
    ).add_to(m)


def add_center_marker(m: folium.Map, name: str, latlon: Tuple[float,float], extra_lines: List[str]):
    body = [f"<b>{name}</b>"] + [x for x in extra_lines if x]
    folium.Marker(
        location=[latlon[0], latlon[1]],
        icon=folium.Icon(color="blue", icon="ambulance", prefix="fa"),
        tooltip=name,
        popup="<br>".join(body)
    ).add_to(m)


def add_hospital_marker(m: folium.Map, name: str, grade_code: Union[int, str], phone: Optional[str], addr: Optional[str],
                        latlon: Tuple[float,float], beds: Optional[Union[int,float]]=None, qcap: Optional[Union[int,float]]=None,
                        extra_lines: Optional[List[str]]=None):
    try:
        g = int(float(str(grade_code)))
    except:
        g = -1
    color = "red" if g == 1 else ("orange" if g == 11 else "green")
    body = [f"<b>{name}</b>"]
    body.append(f"등급코드={grade_code}")
    if beds is not None and not (isinstance(beds, float) and math.isnan(beds)):
        body.append(f"병상수={int(beds)}")
    if qcap is not None and not (isinstance(qcap, float) and math.isnan(qcap)):
        body.append(f"queue_capa={int(qcap)}")
    if phone:
        body.append(f"전화={phone}")
    if addr:
        body.append(f"주소={addr}")
    body.append(f"lat,lon={latlon[0]:.6f},{latlon[1]:.6f}")
    if extra_lines:
        body += [x for x in extra_lines if x]
    folium.Marker(
        location=[latlon[0], latlon[1]],
        icon=folium.Icon(color=color, icon="plus", prefix="fa"),
        tooltip=name,
        popup="<br>".join(body)
    ).add_to(m)


def draw_route_from_json(m: folium.Map, route_obj: dict, highlight: bool=False):
    payload = (route_obj.get("payload") or {}).get("naver_response", {})
    route_list = payload.get("route", {}).get("trafast", [])
    if not route_list:
        return
    r0 = route_list[0]
    path = r0.get("path", [])
    latlngs = [[p[1], p[0]] for p in path if isinstance(p, (list,tuple)) and len(p) >= 2]
    if not latlngs:
        return
    sections = r0.get("section", [])
    if sections:
        try:
            idx = 0
            for sec in sections:
                road_kind = ROADTYPE_TO_KIND.get(int(sec.get("roadType", -1)), "일반도로") if isinstance(sec.get("roadType"), (int,float)) else "일반도로"
                spd = float(sec.get("speed", np.nan)) if sec.get("speed") is not None else np.nan
                cong_by_speed = _classify_cong_by_speed(road_kind, (None if np.isnan(spd) else spd))
                cong = cong_by_speed if cong_by_speed is not None else int(sec.get("congestion", 0))
                cnt = int(sec.get("pointCount", 0))
                if cnt > 0 and idx + cnt <= len(latlngs):
                    seg = latlngs[idx:idx+cnt]
                    idx += cnt
                else:
                    seg = latlngs
                folium.PolyLine(
                    locations=seg,
                    color=CONG_COLORS.get(cong, "#888888"),
                    weight=8 if highlight else 5,
                    opacity=0.9 if highlight else 0.7,
                ).add_to(m)
        except Exception:
            folium.PolyLine(locations=latlngs, color="#3388ff", weight=8 if highlight else 5, opacity=0.7).add_to(m)
    else:
        folium.PolyLine(locations=latlngs, color="#3388ff", weight=8 if highlight else 5, opacity=0.7).add_to(m)


def _offset_line(start: Tuple[float,float], end: Tuple[float,float], meters: float=30.0) -> List[Tuple[float,float]]:
    # 단순한 위경도 오프셋(근사): 1deg lat≈111320m, 1deg lon≈111320*cos(lat)
    lat1, lon1 = start; lat2, lon2 = end
    latc = (lat1+lat2)/2
    import math as _m
    dx = lon2 - lon1; dy = lat2 - lat1
    # 수직 방향 단위벡터(좌측으로 회전)
    vx, vy = -dy, dx
    norm = _m.hypot(vx, vy) or 1.0
    vx/=norm; vy/=norm
    dlat = (meters/111320.0)*vy
    dlon = (meters/(111320.0*_m.cos(_m.radians(latc))))*vx
    return [(lat1+dlat, lon1+dlon), (lat2+dlat, lon2+dlon)]


def draw_uav_dash(m: folium.Map, start_latlon: Tuple[float,float], end_latlon: Tuple[float,float], color: str, tooltip: str, offset_m: float=0.0):
    pts = [start_latlon, end_latlon]
    if offset_m != 0.0:
        pts = _offset_line(start_latlon, end_latlon, meters=offset_m)
    folium.PolyLine(
        locations=pts,
        color=color,
        weight=3,
        opacity=0.95,
        dash_array="6,6",
        tooltip=tooltip
    ).add_to(m)

# YAML에서 속도 파싱 (범례용)

def get_speed_from_yaml(yaml_path: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    if not yaml_path or not exists_file(yaml_path):
        return None, None
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            y = yaml.safe_load(f)
        def _search(d, key):
            if isinstance(d, dict):
                for k,v in d.items():
                    if key.lower() in str(k).lower():
                        if isinstance(v, (int,float)):
                            return float(v)
                    res = _search(v, key)
                    if res is not None:
                        return res
            elif isinstance(d, list):
                for it in d:
                    res = _search(it, key)
                    if res is not None:
                        return res
            return None
        amb = _search(y, "amb_speed") or _search(y, "ambulance_speed") or _search(y, "amb_kmph")
        uav = _search(y, "uav_speed") or _search(y, "uav_kmph")
        return amb, uav
    except Exception:
        return None, None

# ------------------------------
# 실행/재실행
# ------------------------------

def run_powershell(ps_path: str, args: List[str] = None, env: Dict[str,str] = None, cwd: Optional[str]=None) -> Tuple[int,str,str]:
    args = args or []
    cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_path] + args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env, text=True, encoding="utf-8", errors="ignore")
    out, err = proc.communicate()
    return proc.returncode, out, err


def run_main_py(base_path: str, config_path: str) -> Tuple[int,str,str]:
    cmd = ["python", "-X", "utf8", "main.py", "--config_path", config_path]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=base_path, text=True, encoding="utf-8", errors="ignore")
    out, err = proc.communicate()
    return proc.returncode, out, err

# ------------------------------
# 페이지 공통 설정 + CSS(멀티셀렉트 ellipsis 완화)
# ------------------------------
st.set_page_config(page_title="MCI Dashboard", layout="wide")


with st.sidebar:
    st.header("⚙️ Settings")
    base_input = st.text_input("base_path", st.session_state.base_path, placeholder="예: C:\\Users\\사용자명\\MCI")
    if st.button("Set base_path"):
        st.session_state.base_path = norm(base_input)
    if st.session_state.base_path and not base_ok(st.session_state.base_path):
        st.warning("유효한 base_path가 아닙니다. (scenarios 폴더가 필요)")
    st.text("※ 위에 버튼 클릭해야 시작 가능")
    if base_ok(st.session_state.base_path):
        exps = list_experiments_any(st.session_state.base_path)
        st.session_state.selected_exp = st.selectbox(
            "Experiment ID",
            options=[""] + exps,
            index=0 if st.session_state.selected_exp not in exps else (exps.index(st.session_state.selected_exp) + 1),
        )
        coords = list_coords_from_scenarios(st.session_state.base_path, st.session_state.selected_exp) if st.session_state.selected_exp else []
        st.session_state.selected_coord = st.selectbox(
            "Coordinate folder",
            options=[""] + coords,
            index=0 if st.session_state.selected_coord not in coords else (coords.index(st.session_state.selected_coord) + 1),
        )

        # 1) 미니맵 (좌표 선택시)
        if st.session_state.selected_coord:
            lat, lon = coord_center(st.session_state.selected_coord)
            st.caption("현재 좌표 위치")

            # ── 베이스맵 선택(라이트 전용) + 테마 토글 ─────────────────
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                basemap_choice_ui = st.selectbox(
                    "Light 타일 선택",
                    ["OpenStreetMap","CartoDB Positron"],
                    index=0,
                    key="mini_basemap_light",
                )
            with col_m2:
                theme_choice = st.radio(
                    "테마",
                    ["Light", "Dark"],
                    index=0,
                    horizontal=True,
                    key="mini_theme",
                )

            # ── folium 기반 렌더(표출 로직 동일: 한 점만) ────────────────
            try:
                import folium
                from streamlit_folium import st_folium

                # UI 라벨 → folium 타일 이름 매핑
                tile_map_light = {
                    "CartoDB Positron": "CartoDB positron",
                    "OpenStreetMap": "OpenStreetMap",
                }
                # Dark는 고정
                tile_dark = "CartoDB dark_matter"

                chosen_tile = tile_dark if theme_choice == "Dark" else tile_map_light[basemap_choice_ui]

                m = folium.Map(location=(lat, lon), zoom_start=12, control_scale=True, tiles=chosen_tile)
                folium.CircleMarker(
                    location=(lat, lon), radius=5, weight=1, opacity=0.9,
                    fill=True, fill_opacity=0.8, tooltip=f"{lat:.6f}, {lon:.6f}"
                ).add_to(m)
                # ★ 라이센스 표출 크기 최소화! (저작권 위반?)
                from folium import Element
                m.get_root().html.add_child(Element("""
                <style>
                .leaflet-control-attribution {
                font-size: 1px !important;
                opacity: .55 !important;
                background: rgba(255,255,255,.6) !important;
                padding: 2px 6px !important;
                border-radius: 1px !important;
                }
                .leaflet-control-attribution a { color: inherit !important; text-decoration: none !important; }
                /* (선택) 아래 대신 위로 올리고 싶으면 활성화 */
                .leaflet-bottom.leaflet-right { bottom: auto !important; top: 6px !important; right: 8px !important; }
                </style>
                """))
                st_folium(m, use_container_width=True, height=260)

            except Exception:
                # (폴백) streamlit 기본 지도 (타일 커스텀 불가)
                st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), use_container_width=True)

        st.divider()



# CSS: 멀티셀렉트 폭 확장 → '...'(ellipsis) 최소화
st.markdown("""
<style>
.stMultiSelect [data-baseweb="select"]{max-width:100%!important}
</style>
""", unsafe_allow_html=True)

st.title("🚑 MCI 재난 시뮬레이션 대시보드")

tabs = st.tabs(["Maps", "Scenarios", "Analytics", "Data Tables", "Generate"])

# ------------------------------
# Scenarios 탭
# ------------------------------
with tabs[1]:
    st.subheader("📁 선택된 시나리오")
    bp = st.session_state.base_path; exp = st.session_state.selected_exp; coord = st.session_state.selected_coord
    if bp and exp and coord:
        yaml_path = find_yaml_in_coord(bp, exp, coord)
        st.write("**YAML**:", yaml_path or "(없음)")
        
        smdf = read_experiment_summary_csv(bp, exp)
        info, site_addr = summarize_experiment(smdf) if smdf is not None else ({}, None)
        lat, lon = coord_center(coord)

        site_info, sim_info = summarize_experiment_extended(smdf)
        site_info["좌표"] = f"{lat:.6f}, {lon:.6f}"

        with st.expander("📝 실험 요약 보기", expanded=True):
            left, right = st.columns([0.42, 0.58])
            with left:
                st.markdown("**사고지점**")
                st.dataframe(pd.DataFrame({"항목":list(site_info.keys()), "값":list(site_info.values())}), use_container_width=True, height=170)
            with right:
                st.markdown("**시뮬레이션 정보** (summary.csv: '시나리오생성_시작'→끝)")
                if sim_info:
                    st.dataframe(pd.DataFrame(sorted(sim_info.items(), key=lambda x: x[0]), columns=["항목","값"]), use_container_width=True, height=170)
                else:
                    st.caption("summary.csv에서 '시나리오생성_시작' 이후 열을 찾지 못했습니다.")


        st.markdown("### 🧾 실행 로그")
        logs = experiment_log_candidates(bp, exp, coord)
        if logs:
            log_sel = st.selectbox("로그 파일 선택 (experiment_logs/<coord>만)", logs)
            log_text = _read_text_any(log_sel)
            blocks = parse_log_blocks(log_text)
            # (Unlabeled) 블록 숨김
            rule_list = [b["rule"] for b in blocks if b.get("rule")!="(Unlabeled)"] if blocks else []
            if not rule_list:
                st.info("이벤트 패턴을 찾지 못했습니다. (로그 포맷 확인)")
            else:
                sel_rule = st.selectbox("Rule 선택", options=rule_list, index=0)

                # [추가] 선택한 Rule에서 사용 가능한 Iter 목록 수집
                rule_blocks = [b for b in blocks if b.get("rule") == sel_rule]
                iter_list = sorted({b.get("iter") for b in rule_blocks if b.get("iter") is not None})

                # [추가] Iter 셀렉터 (있을 때만 노출)
                sel_iter = None
                if iter_list:
                    sel_iter = st.selectbox("반복(Iter) 선택", iter_list, index=0, help="로그의 'Iter : n' 라인 기준")
                    # 선택된 Rule & Iter 조합으로 필터
                    cand_blocks = [b for b in rule_blocks if b.get("iter") == sel_iter]
                else:
                    # Iter 라인이 없으면 기존 방식 유지(첫 블록)
                    st.caption("Iter 라인이 없어 ‘단일 실행’으로 간주합니다.")
                    cand_blocks = rule_blocks

                # 선택 블록 최종 결정(복수면 첫 블록)
                blk = cand_blocks[0] if cand_blocks else None

                # (선택) 현재 선택 상태 안내
                st.caption(f"선택: Rule={sel_rule} / Iter={sel_iter if sel_iter is not None else '미표기'}")


                st.markdown("#### 👤 환자 스토리(요약)")
                psum = build_patient_summary(blk["events"]) if blk else pd.DataFrame()
                if psum.empty:
                    st.caption("환자 이벤트를 찾지 못했습니다.")
                else:
                    st.dataframe(psum, use_container_width=True, height=340)
                    _suffix = f"_iter{sel_iter}" if sel_iter is not None else ""
                    st.download_button(
                        "⬇️ 환자 타임라인(csv)",
                        psum.to_csv(index=False).encode('utf-8-sig'),
                        file_name=f"patient_timeline{_suffix}.csv"
                    )


                st.markdown("#### 🧰 전체 이벤트 표")
                ev_df = pd.DataFrame(blk["events"]).rename(columns={"t":"시각","eid":"이벤트ID","ev":"이벤트","p":"환자","a":"구급차","u":"UAV","h":"병원"}) if blk else pd.DataFrame()
                st.dataframe(ev_df, use_container_width=True, height=320)
                _suffix = f"_iter{sel_iter}" if sel_iter is not None else ""
                st.download_button("⬇️ 전체 이벤트(csv)", ev_df.to_csv(index=False).encode('utf-8-sig'), file_name=f"events_all{_suffix}.csv")

            st.markdown("#### 🗂 원본 로그 보기")
            with st.expander("원본 텍스트 펼치기", expanded=False):
                st.code(log_text[:30000] + ("\n... (생략)" if len(log_text) > 30000 else ""))
                st.download_button("원본 로그 다운로드", log_text, file_name=os.path.basename(log_sel))

            st.markdown("---")
            st.markdown("### 🛈 Action/Rule 설명")
            st.markdown(ACTION_TOOLTIP_MD)
        else:
            st.info("해당 조합의 로그 파일을 찾지 못했습니다.")


        st.markdown("### ▶️ 재실행 (main.py --config_path)")
        st.text("results 폴더의 txt 파일들만 갱신됩니다.")
        if yaml_path and st.button("main.py 재실행"):
            st.session_state.py_running = True
            with st.spinner("main.py 실행 중..."):
                code, out, err = run_main_py(bp, yaml_path)
            st.session_state.py_running = False
            st.success(f"종료 코드: {code}")
            st.expander("stdout").write(out or "")
            st.expander("stderr").write(err or "")

# ------------------------------
# Maps 탭 (복수선택 + UAV 출동/이송 토글 + 범례 강화)
# ------------------------------
with tabs[0]:
    st.subheader("🗺️ 지도 시각화")
    bp   = st.session_state.base_path
    exp  = st.session_state.selected_exp
    coord= st.session_state.selected_coord


    # ── 지도는 '최상단' 컨테이너에 그렸다가, 옵션을 아래에 배치 ─────────────
    map_holder = st.container()
    st.divider()

    # 좌표/기본값
    lat, lon = coord_center(coord)
    center = [lat, lon]
    site_addr = st.session_state.get("site_addr", "")

    # 경로/데이터 로드
    rdirs = get_routes_dirs(bp, exp, coord)
    patient_cnt = get_patient_count(bp, exp, coord)
    c2s_all = load_json_files(rdirs["center2site"])  # Center→Site
    h2s_all = load_json_files(rdirs["hos2site"])     # Site→Hospitals
    c2s = c2s_all[:patient_cnt] if patient_cnt is not None else c2s_all
    h2s = h2s_all[:patient_cnt] if patient_cnt is not None else h2s_all

    # 병원/센터 메타
    hosp_xl   = read_excel_hospital(bp)   # 엑셀(요양기관명, 종별코드, x/y좌표, 전화/주소 등)
    hinfo_csv = Path(bp) / "scenarios" / exp / coord / "hospital_info_road.csv"
    hinfo_df  = pd.read_csv(hinfo_csv) if hinfo_csv.is_file() else pd.DataFrame()
    center_csv= Path(bp) / "scenarios" / "안전센터와 소방서.csv"
    center_df = pd.read_csv(center_csv, encoding="cp949") if center_csv.is_file() else pd.DataFrame()

    # 엑셀 이름→좌표 매핑
    xl_coord = {}
    if hosp_xl is not None and "요양기관명" in hosp_xl.columns:
        for _, r in hosp_xl.iterrows():
            nm = str(r.get("요양기관명","")).strip()
            y  = r.get("y좌표", r.get("y", None)); x = r.get("x좌표", r.get("x", None))
            if pd.notna(y) and pd.notna(x) and nm:
                xl_coord[nm] = (float(y), float(x))

    # 종별코드 라벨링(요청: 1=상급종합병원, 11=종합병원, 그 외=일반병원)
    def code_to_grade(c):
        try:
            c = int(c)
        except Exception:
            return "일반병원"
        if c == 1:  return "상급종합병원"
        if c == 11: return "종합병원"
        return "일반병원"

    # ── 지도 테마(지도 바로 위) ─────────────────────────────────────────────
    theme = st.radio("지도 테마", ["Light","Dark"], horizontal=True, key="theme_radio_maps_bottom")
    if theme == "Light":
        tile_name = st.selectbox("Light 타일 선택", ["OpenStreetMap","CartoDB Positron"], index=0, key="light_tile_select")
    else:
        tile_name = "CartoDB Dark_Matter"

    if not (bp and exp and coord):
        st.info("좌측 사이드바에서 base_path / Experiment / Coord를 선택하세요.")
        st.stop()
    # ─────────────────────────────────────────────────────────────────────
    # ① AMB 경로 (C→S 표 / S→H 표)
    # ─────────────────────────────────────────────────────────────────────
    st.markdown("### AMB 경로")
    col_amb_c2s, col_amb_s2h = st.columns(2)

    # --- AMB: C→S(출동) 표 (표시, 인덱스, 안전센터/소방서, 거리) ---
    with col_amb_c2s:
        st.markdown("**안전센터/소방서→사고지점 (출동)**")

        c2s_rows = []
        for i, obj in enumerate(c2s):
            meta = obj.get("meta", {})
            cname = meta.get("name", "센터")
            c = meta.get("center") or meta.get("start")  # [lon, lat]
            dist, mins, _ = _extract_summary_meta(obj)
            if dist is None and isinstance(c, list) and len(c)==2:
                clatlon = (c[1], c[0])
                dist = _haversine_km(clatlon[0], clatlon[1], lat, lon)
            c2s_rows.append({
                "인덱스": i,
                "안전센터/소방서": cname,
                "거리(km)": round(float(dist),2) if dist is not None else None
            })

        c2s_df = pd.DataFrame(c2s_rows)

        if "amb_c2s_sel_idx" not in st.session_state:
            st.session_state.amb_c2s_sel_idx = set(c2s_df["인덱스"].tolist())

        b1, b2 = st.columns(2)
        if b1.button("전체선택(C→S)"):
            st.session_state.amb_c2s_sel_idx = set(c2s_df["인덱스"].tolist())
        if b2.button("전체해제(C→S)"):
            st.session_state.amb_c2s_sel_idx = set()

        c2s_df_show = c2s_df.copy()
        c2s_df_show["표시"] = c2s_df_show["인덱스"].apply(lambda i: i in st.session_state.amb_c2s_sel_idx)
        # ▶ 표시를 맨 앞으로
        c2s_df_show = c2s_df_show[["표시","인덱스","안전센터/소방서","거리(km)"]]

        edited_c2s = st.data_editor(
            c2s_df_show,
            use_container_width=True,
            num_rows="fixed",
            hide_index=True,
            column_config={
                "표시": st.column_config.CheckboxColumn("표시"),
                "인덱스": st.column_config.NumberColumn("인덱스", disabled=True),
                "안전센터/소방서": st.column_config.TextColumn("안전센터/소방서", disabled=True),
                "거리(km)": st.column_config.NumberColumn("거리(km)", disabled=True, format="%.2f"),
            },
            key="tbl_c2s"
        )
        st.session_state.amb_c2s_sel_idx = set(edited_c2s.loc[edited_c2s["표시"]==True, "인덱스"].tolist())

    # --- AMB: S→H(이송) 표 (표시, 인덱스, 병원, 종별코드, 병원등급, 거리) ---
    with col_amb_s2h:
        st.markdown("**사고지점→병원 (이송)**")

        # 이름→종별코드 매핑(road 우선, 없으면 엑셀)
        code_map = {}
        if not hinfo_df.empty and {"요양기관명","종별코드"}.issubset(hinfo_df.columns):
            for _, r in hinfo_df[["요양기관명","종별코드"]].dropna().iterrows():
                code_map[str(r["요양기관명"]).strip()] = r["종별코드"]
        if hosp_xl is not None and {"요양기관명","종별코드"}.issubset(hosp_xl.columns):
            for _, r in hosp_xl[["요양기관명","종별코드"]].dropna().iterrows():
                code_map.setdefault(str(r["요양기관명"]).strip(), r["종별코드"])

        # 거리 로드: distance_Hos2Site_road.csv (Index, distance)
        dist_csv = Path(bp) / "scenarios" / exp / coord / "distance_Hos2Site_road.csv"
        dist_map = {}
        if dist_csv.is_file():
            _dfd = pd.read_csv(dist_csv)
            if {"Index","distance"}.issubset(_dfd.columns):
                _dfd = _dfd.copy()
                _dfd["Index"] = pd.to_numeric(_dfd["Index"], errors="coerce").astype("Int64")
                _dfd["distance"] = pd.to_numeric(_dfd["distance"], errors="coerce")
                dist_map = {int(i): float(d) for i, d in _dfd.dropna(subset=["Index","distance"]).itertuples(index=False, name=None)}

        s2h_rows = []
        for i, obj in enumerate(h2s):
            nm = obj.get("meta", {}).get("name", "병원")
            code = code_map.get(nm, "")
            s2h_rows.append({
                "인덱스": i,
                "병원": nm,
                "종별코드": code,
                "병원등급": code_to_grade(code),
            })

        s2h_df = pd.DataFrame(s2h_rows)
        if s2h_df.shape[0] > 0:
            s2h_df["거리(km)"] = pd.to_numeric(s2h_df["인덱스"].map(dist_map), errors="coerce").round(2)

        if "amb_s2h_sel_idx" not in st.session_state:
            st.session_state.amb_s2h_sel_idx = set(s2h_df["인덱스"].tolist())

        e1, e2 = st.columns(2)
        if e1.button("전체선택(S→H)"):
            st.session_state.amb_s2h_sel_idx = set(s2h_df["인덱스"].tolist())
        if e2.button("전체해제(S→H)"):
            st.session_state.amb_s2h_sel_idx = set()

        s2h_df_show = s2h_df.copy()
        s2h_df_show["표시"] = s2h_df_show["인덱스"].apply(lambda i: i in st.session_state.amb_s2h_sel_idx)
        # ▶ 표시를 맨 앞으로
        cols_order = ["표시","인덱스","병원","종별코드","병원등급"]
        if "거리(km)" in s2h_df_show.columns:
            cols_order += ["거리(km)"]
        s2h_df_show = s2h_df_show[cols_order]

        edited_s2h = st.data_editor(
            s2h_df_show,
            use_container_width=True,
            num_rows="fixed",
            hide_index=True,
            column_config={
                "표시":     st.column_config.CheckboxColumn("표시"),
                "인덱스":   st.column_config.NumberColumn("인덱스", disabled=True),
                "병원":     st.column_config.TextColumn("병원", disabled=True),
                "종별코드": st.column_config.NumberColumn("종별코드", disabled=True),
                "병원등급": st.column_config.TextColumn("병원등급", disabled=True),
                **({"거리(km)": st.column_config.NumberColumn("거리(km)", disabled=True, format="%.2f")} if "거리(km)" in s2h_df_show.columns else {})
            },
            key="tbl_s2h"
        )
        st.session_state.amb_s2h_sel_idx = set(edited_s2h.loc[edited_s2h["표시"]==True, "인덱스"].tolist())

    # ─────────────────────────────────────────────────────────────────────
    # ② UAV 경로 (출동/이송 — AMB 이송과 동일 형식 + 직선거리 마지막 열 추가)
    # ─────────────────────────────────────────────────────────────────────
    st.markdown("### UAV 경로")
    col_uav_out, col_uav_back = st.columns(2)

    # 출동(병원→사고): 상급종합(종별코드=1)만 대상
    with col_uav_out:
        st.markdown("**상급종합병원→사고지점 (출동)**")

        tier1_latlons = []
        if not hinfo_df.empty and {"종별코드","요양기관명"}.issubset(hinfo_df.columns):
            tmp = hinfo_df.copy()
            tmp["종별코드"] = pd.to_numeric(tmp["종별코드"], errors="coerce")
            for _, rr in tmp[tmp["종별코드"]==1].iterrows():
                name = str(rr.get("요양기관명","Tier1")).strip()
                if name in xl_coord:
                    y, x = xl_coord[name]       # (lat, lon)
                    tier1_latlons.append((y, x, name, 1))

        uav_out_rows = []
        for i, (y, x, nm, code) in enumerate(tier1_latlons):
            dkm = _haversine_km(y, x, lat, lon)  # 직선거리
            uav_out_rows.append({
                "인덱스": i,
                "병원": nm,
                "종별코드": code,
                "병원등급": code_to_grade(code),
                "거리(km)": round(dkm, 2)
            })
        uav_out_df = pd.DataFrame(uav_out_rows)

        if "uav_c2s_sel_idx" not in st.session_state:
            st.session_state.uav_c2s_sel_idx = set(uav_out_df["인덱스"].tolist())

        f1, f2 = st.columns(2)
        if f1.button("UAV 출동 전체선택"):
            st.session_state.uav_c2s_sel_idx = set(uav_out_df["인덱스"].tolist())
        if f2.button("UAV 출동 전체해제"):
            st.session_state.uav_c2s_sel_idx = set()

        uav_out_df_show = uav_out_df.copy()
        uav_out_df_show["표시"] = uav_out_df_show["인덱스"].apply(lambda i: i in st.session_state.uav_c2s_sel_idx)
        # ▶ 표시를 맨 앞으로, 거리(km)는 마지막
        uav_out_df_show = uav_out_df_show[["표시","인덱스","병원","종별코드","병원등급","거리(km)"]]

        edited_uav_out = st.data_editor(
            uav_out_df_show,
            use_container_width=True,
            num_rows="fixed",
            hide_index=True,
            column_config={
                "표시":     st.column_config.CheckboxColumn("표시"),
                "인덱스":   st.column_config.NumberColumn("인덱스", disabled=True),
                "병원":     st.column_config.TextColumn("병원", disabled=True),
                "종별코드": st.column_config.NumberColumn("종별코드", disabled=True),
                "병원등급": st.column_config.TextColumn("병원등급", disabled=True),
                "거리(km)": st.column_config.NumberColumn("거리(km)", disabled=True, format="%.2f"),
            },
            key="tbl_uav_out"
        )
        st.session_state.uav_c2s_sel_idx = set(edited_uav_out.loc[edited_uav_out["표시"]==True, "인덱스"].tolist())

    # 이송(사고→병원): 전체 병원 대상
    with col_uav_back:
        st.markdown("**사고지점→병원 (이송)**")

        all_hosp_latlons = []
        if not hinfo_df.empty and "요양기관명" in hinfo_df.columns:
            for _, rr in hinfo_df.iterrows():
                name = str(rr.get("요양기관명","")).strip()
                if name and name in xl_coord:
                    y, x = xl_coord[name]       # (lat, lon)
                    code = rr.get("종별코드", "")
                    all_hosp_latlons.append((y, x, name, code))

        uav_back_rows = []
        for i, (y, x, nm, code) in enumerate(all_hosp_latlons):
            dkm = _haversine_km(lat, lon, y, x)  # 직선거리
            uav_back_rows.append({
                "인덱스": i,
                "병원": nm,
                "종별코드": code,
                "병원등급": code_to_grade(code),
                "거리(km)": round(dkm, 2)
            })
        uav_back_df = pd.DataFrame(uav_back_rows)

        if "uav_s2h_sel_idx" not in st.session_state:
            st.session_state.uav_s2h_sel_idx = set(uav_back_df["인덱스"].tolist())

        g1, g2 = st.columns(2)
        if g1.button("UAV 이송 전체선택"):
            st.session_state.uav_s2h_sel_idx = set(uav_back_df["인덱스"].tolist())
        if g2.button("UAV 이송 전체해제"):
            st.session_state.uav_s2h_sel_idx = set()

        uav_back_df_show = uav_back_df.copy()
        uav_back_df_show["표시"] = uav_back_df_show["인덱스"].apply(lambda i: i in st.session_state.uav_s2h_sel_idx)
        # ▶ 표시를 맨 앞으로, 거리(km)는 마지막
        uav_back_df_show = uav_back_df_show[["표시","인덱스","병원","종별코드","병원등급","거리(km)"]]

        edited_uav_back = st.data_editor(
            uav_back_df_show,
            use_container_width=True,
            num_rows="fixed",
            hide_index=True,
            column_config={
                "표시":     st.column_config.CheckboxColumn("표시"),
                "인덱스":   st.column_config.NumberColumn("인덱스", disabled=True),
                "병원":     st.column_config.TextColumn("병원", disabled=True),
                "종별코드": st.column_config.NumberColumn("종별코드", disabled=True),
                "병원등급": st.column_config.TextColumn("병원등급", disabled=True),
                "거리(km)": st.column_config.NumberColumn("거리(km)", disabled=True, format="%.2f"),
            },
            key="tbl_uav_back"
        )
        st.session_state.uav_s2h_sel_idx = set(edited_uav_back.loc[edited_uav_back["표시"]==True, "인덱스"].tolist())

    # ─────────────────────────────────────────────────────────────────────
    # ③ 지도 생성 및 출력(최상단 map_holder에 표출)
    # ─────────────────────────────────────────────────────────────────────
    m = folium.Map(location=center, zoom_start=12, control_scale=True, tiles=tile_name)

    # 사고지점 마커
    site_popup = f"사고지점<br>lat,lon={lat:.6f},{lon:.6f}"
    if site_addr: site_popup += f"<br>주소: {site_addr}"
    folium.Marker(
        [lat,lon],
        icon=folium.Icon(color="purple", icon="map-pin", prefix="fa"),
        tooltip="사고지점", popup=site_popup
    ).add_to(m)

    # ─ AMB C→S 라인/마커 ─
    for i, obj in enumerate(c2s):
        if i not in st.session_state.amb_c2s_sel_idx:
            continue
        meta = obj.get("meta", {})
        c = meta.get("center") or meta.get("start")  # [lon,lat]
        cname = meta.get("name", "센터")
        clatlon = (c[1], c[0]) if (isinstance(c,list) and len(c)==2) else None

        addr = tel = ""
        if not center_df.empty and "기관명" in center_df.columns:
            msk = (center_df["기관명"].astype(str) == str(cname))
            if msk.any():
                row = center_df[msk].iloc[0]
                addr = str(row.get("주소","")); tel = str(row.get("전화번호",""))

        dist, mins, guide = _extract_summary_meta(obj)
        extra = []
        if clatlon and dist is None:
            d_lin = _haversine_km(clatlon[0], clatlon[1], lat, lon)
            extra.append(f"직선거리: {d_lin:.2f} km")
        if dist is not None and mins is not None:
            extra.append(f"🚑 Center→Site: {float(dist):.2f} km · {mins:.1f}분")
        elif dist is not None:
            extra.append(f"🚑 Center→Site: {float(dist):.2f} km")
        if addr: extra.append(f"주소: {addr}")
        if tel:  extra.append(f"전화: {tel}")
        extra.append(_guide_html(guide))
        if clatlon: add_center_marker(m, cname, clatlon, extra)
        draw_route_from_json(m, obj, highlight=False)

    # ─ AMB S→H 라인/마커 ─
    for i, obj in enumerate(h2s):
        if i not in st.session_state.amb_s2h_sel_idx:
            continue
        meta = obj.get("meta", {})
        h = meta.get("hospital") or meta.get("goal")  # [lon,lat]
        name = meta.get("name", "병원")
        latlon = (h[1], h[0]) if (isinstance(h,list) and len(h)==2) else None

        beds=qcap=code=phone=addr=None
        if not hinfo_df.empty and "요양기관명" in hinfo_df.columns:
            r = hinfo_df[hinfo_df["요양기관명"]==name]
            if not r.empty:
                beds = r.iloc[0].get("병상수", None)
                qcap = r.iloc[0].get("queue_capa", None)
                code = r.iloc[0].get("종별코드", None)
                if latlon is None:
                    y = r.iloc[0].get("y좌표", r.iloc[0].get("y", None))
                    x = r.iloc[0].get("x좌표", r.iloc[0].get("x", None))
                    if pd.notna(y) and pd.notna(x):
                        latlon = (float(y), float(x))
        if hosp_xl is not None and "요양기관명" in hosp_xl.columns:
            rx = hosp_xl[hosp_xl["요양기관명"]==name]
            if not rx.empty:
                phone = rx.iloc[0].get("전화번호", phone)
                addr  = rx.iloc[0].get("주소", addr)
                code  = rx.iloc[0].get("종별코드", code)
                if latlon is None:
                    y = rx.iloc[0].get("y좌표", rx.iloc[0].get("y", None))
                    x = rx.iloc[0].get("x좌표", rx.iloc[0].get("x", None))
                    if pd.notna(y) and pd.notna(x):
                        latlon = (float(y), float(x))

        if latlon:
            dist, mins, guide = _extract_summary_meta(obj)
            extra = []
            if dist is not None and mins is not None:
                extra.append(f"🏥 Site→Hospital: {float(dist):.2f} km · {mins:.1f}분")
            elif dist is not None:
                extra.append(f"🏥 Site→Hospital: {float(dist):.2f} km")
            grade_label = code_to_grade(code)
            add_hospital_marker(
                m, name, code, phone, addr, latlon,
                beds=beds, qcap=qcap,
                extra_lines=[f"병원등급: {grade_label}"] + extra + [ _guide_html(guide) ]
            )
        draw_route_from_json(m, obj, highlight=False)

    # ─ UAV 출동(병원→사고) ─
    for i, (y, x, name, code) in enumerate(tier1_latlons):
        if i not in st.session_state.uav_c2s_sel_idx: 
            continue
        dkm = _haversine_km(y, x, lat, lon)
        draw_uav_dash(
            m, (y,x), (lat,lon),
            UAV_OUT_COLOR,
            f"🛩️ 출동 {name}→Site · {dkm:.2f} km"
        )

    # ─ UAV 이송(사고→병원) ─
    t1_set = {(y,x) for (y,x,_,_) in tier1_latlons}
    for i, (y, x, name, code) in enumerate(all_hosp_latlons):
        if i not in st.session_state.uav_s2h_sel_idx:
            continue
        dkm = _haversine_km(lat, lon, y, x)
        is_tier1 = (y, x) in t1_set
        off = 30.0 if is_tier1 else 0.0
        draw_uav_dash(
            m, (lat,lon), (y,x),
            UAV_BACK_COLOR,
            f"🛩️ 이송 Site→{name} · {dkm:.2f} km",
            offset_m=off
        )

    # ─ 범례/속도 ─
    amb_speed, uav_speed = get_speed_from_yaml(find_yaml_in_coord(bp, exp, coord))
    legend_html = [
        '<div style="position: fixed; bottom: 18px; left: 12px; z-index: 9999; background: rgba(255,255,255,0.94); padding: 10px 12px; border-radius: 10px; font-size: 12px; line-height: 1.35; box-shadow: 0 2px 6px rgba(0,0,0,.15);">',
        '<b>범례</b><br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:5px solid {CONG_COLORS[0]};margin:2px 6px 2px 0;"></span>정보없음(0)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:5px solid {CONG_COLORS[1]};margin:2px 6px 2px 0;"></span>원활(1)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:5px solid {CONG_COLORS[2]};margin:2px 6px 2px 0;"></span>서행(2)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:5px solid {CONG_COLORS[3]};margin:2px 6px 2px 0;"></span>혼잡(3)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:3px dashed {UAV_OUT_COLOR};margin:6px 6px 2px 0;"></span>UAV 출동(병원→사고)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:3px dashed {UAV_BACK_COLOR};margin:2px 6px 0 0;"></span>UAV 이송(사고→병원)<br>',
    ]
    if amb_speed or uav_speed:
        sp = []
        if amb_speed: sp.append(f"🚑 AMB≈{amb_speed} km/h")
        if uav_speed: sp.append(f"🛩️ UAV≈{uav_speed} km/h")
        legend_html.append(" · ".join(sp) + '<br>')
    legend_html.append('<span style="opacity:.8;">* 경로 상세 안내는 마커 팝업 ▶ 클릭</span>')
    legend_html.append('</div>')
    m.get_root().html.add_child(folium.Element("".join(legend_html)))
    
    # 저작권 표기 축소(옵션)
    from folium import Element
    m.get_root().html.add_child(Element("""
    <style>
    .leaflet-control-attribution {
      font-size: 1px !important;
      opacity: .55 !important;
      background: rgba(255,255,255,.6) !important;
      padding: 2px 6px !important;
      border-radius: 1px !important;
    }
    .leaflet-control-attribution a { color: inherit !important; text-decoration: none !important; }
    .leaflet-bottom.leaflet-right { bottom: auto !important; top: 6px !important; right: 8px !important; }
    </style>
    """))

    # 지도는 '최상단' 컨테이너에 출력
    with map_holder:
        st_folium(m, width=None, height=690)

# ------------------------------
# Analytics 탭 (정렬 테이블 + ANOVA 스위트)
# ------------------------------

def gen_scenario_keys() -> pd.DataFrame:
    rows = []
    for ph in PHASES:
        for rp in RED_POLICY:
            for ra in ACTIONS:
                for ya in ACTIONS:
                    rows.append((ph, rp, ra, ya))
    df = pd.DataFrame(rows, columns=["Phase","RedPolicy","RedAction","YellowAction"])
    df["ScenarioIdx"] = np.arange(len(df))
    return df


def parse_stat_file(stat_path: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    with open(stat_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    triples = []
    for ln in lines:
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", ln)
        if len(nums) >= 3:
            triples.append(tuple(float(x) for x in nums[:3]))
    if len(triples) % 64 != 0:
        st.warning(f"Stat 라인 수가 64의 배수가 아님: {len(triples)}")
    n_blocks = len(triples) // 64
    if n_blocks < 1:
        return pd.DataFrame(), pd.DataFrame()
    keys = gen_scenario_keys()
    wide = keys.copy()
    long_rows = []
    for b in range(min(5, n_blocks)):
        metric = f"M{b+1}"
        block = triples[b*64:(b+1)*64]
        means = [t[0] for t in block]; stds  = [t[1] for t in block]; cis   = [t[2] for t in block]
        wide[f"{metric}_mean"] = means; wide[f"{metric}_std"]  = stds; wide[f"{metric}_ci"]   = cis
        for i in range(len(block)):
            long_rows.append({
                "ScenarioIdx": i,
                "Metric": metric,
                "mean": means[i],
                "std": stds[i],
                "ci": cis[i],
                "Phase": keys.iloc[i]["Phase"],
                "RedPolicy": keys.iloc[i]["RedPolicy"],
                "RedAction": keys.iloc[i]["RedAction"],
                "YellowAction": keys.iloc[i]["YellowAction"],
            })
    long_df = pd.DataFrame(long_rows)
    return wide, long_df

# Raw 결과 파싱 (Rule×Sample 스택)
RAW_RE = re.compile(r'^(START|ReSTART),\s*(RedOnly|YellowHalf),\s*Red\s+([A-Za-z_]+),\s*Yellow\s+([A-Za-z_]+)')


def parse_raw_results(raw_path: str) -> pd.DataFrame:
    if not raw_path or not exists_file(raw_path):
        return pd.DataFrame()
    rows = []
    keys = gen_scenario_keys()
    keymap = {(r.Phase, r.RedPolicy, r.RedAction, r.YellowAction): int(r.ScenarioIdx) for _, r in keys.iterrows()}
    sample_count_map = {}
    with open(raw_path, 'r', encoding='utf-8') as f:
        for ln in f:
            s = ln.strip()
            if not s:
                continue
            m = RAW_RE.match(s)
            if not m:
                continue
            phase, rp, ra, ya = m.groups()
            nums = re.findall(r"[-+]?\d*\.\d+|\d+", s)
            vals = [float(x) for x in nums]
            # 라인 끝 5개: Reward, Time, PDR, Reward_woG, PDR_woG (가정)
            if len(vals) < 5:
                continue
            reward, timev, pdr, reward_g0, pdr_g0 = vals[-5:]
            rule = (phase, rp, ra, ya)
            ridx = keymap.get(rule)
            if ridx is None:
                continue
            sample_count_map[ridx] = sample_count_map.get(ridx, 0) + 1
            rows.append({
                "ScenarioIdx": ridx,
                "Phase": phase,
                "RedPolicy": rp,
                "RedAction": ra,
                "YellowAction": ya,
                "Sample": sample_count_map[ridx],
                "Reward": reward,
                "Time": timev,
                "PDR": pdr,
                "Reward_woG": reward_g0,
                "PDR_woG": pdr_g0,
            })
    return pd.DataFrame(rows)

# ------------------------------
# Analytics 탭 (ANOVA 분석)
# ------------------------------

with tabs[2]:
    st.subheader("📊 결과 분석 (results_*_stat.txt / raw)")
    bp = st.session_state.base_path
    exp = st.session_state.selected_exp
    coord = st.session_state.selected_coord
    if not (bp and exp and coord):
        st.info("좌측에서 시나리오를 먼저 선택하세요.")
    else:
        st.info("📂 results/exp_YYYYMMDD_HHMMSS/(lat,lon)/results_{coord}.txt (Raw), results_{coord}_stat.txt (통계)\n\n- **Reward**: 생존확률 합\n- **Time**: 소요시간\n- **PDR**\n- **w.o.G**: Green 제외 지표")
        spath = results_stat_path(bp, exp, coord)
        rpath = results_raw_path(bp, exp, coord)
        wide, long_df = (pd.DataFrame(), pd.DataFrame())
        if spath:
            wide, long_df = parse_stat_file(spath)
        if not wide.empty:
            # ── 기본 표시 테이블
            display = wide.rename(columns={
                "M1_mean":"Reward(생존) 평균","M1_std":"Reward 표준편차","M1_ci":"Reward 95%CI",
                "M2_mean":"Time 평균","M2_std":"Time 표준편차","M2_ci":"Time 95%CI",
                "M3_mean":"PDR 평균","M3_std":"PDR 표준편차","M3_ci":"PDR 95%CI",
                "M4_mean":"Reward w.o.G 평균","M4_std":"Reward w.o.G 표준편차","M4_ci":"Reward w.o.G 95%CI",
                "M5_mean":"PDR w.o.G 평균","M5_std":"PDR w.o.G 표준편차","M5_ci":"PDR w.o.G 95%CI",
            })
            st.dataframe(display, use_container_width=True)

            # ── 추천 랭킹(전체 정렬)
            st.markdown("#### 🏆 시나리오 추천(정렬 기준)")
            crit = st.selectbox("정렬 기준", ["Reward 큰 순","PDR 작은 순","Time 짧은 순"], index=0)
            if crit == "Reward 큰 순":
                df_sorted = wide.sort_values("M1_mean", ascending=False)
                cols = ["ScenarioIdx","Phase","RedPolicy","RedAction","YellowAction","M1_mean","M1_ci"]
            elif crit == "PDR 작은 순":
                df_sorted = wide.sort_values("M3_mean", ascending=True)
                cols = ["ScenarioIdx","Phase","RedPolicy","RedAction","YellowAction","M3_mean","M3_ci"]
            else:  # Time 짧은 순
                df_sorted = wide.sort_values("M2_mean", ascending=True)
                cols = ["ScenarioIdx","Phase","RedPolicy","RedAction","YellowAction","M2_mean","M2_ci"]
            st.dataframe(df_sorted[cols], use_container_width=True)

        # ── ANOVA 스위트 (raw가 있을 때)
        st.markdown("#### 🧪 ANOVA (Full Factorial)")
        if not rpath:
            st.caption("raw 파일(results_{coord}.txt)을 찾지 못해 ANOVA를 수행하지 않습니다.")
        else:
            dfraw = parse_raw_results(rpath)
            if dfraw.empty:
                st.caption("raw 파싱 결과가 비어 있습니다. 파일 형식을 확인해 주세요.")
            else:
                metric = st.selectbox("Metric", ["Reward","Time","PDR","Reward_woG","PDR_woG"], index=0)
                st.caption("모형: value ~ Phase + RedPolicy + RedAction + YellowAction + 모든 교호작용")
                if not HAS_SM:
                    st.warning("statsmodels 미설치로 ANOVA를 실행할 수 없습니다. `pip install statsmodels` 후 재시도하세요.")
                else:
                    # OLS 적합 (Full factorial: * 는 주효과+교호작용 모두)
                    import scipy.stats as sps
                    formula = f"{metric} ~ Phase*RedPolicy*RedAction*YellowAction"
                    try:
                        model = smf.ols(formula, data=dfraw).fit()
                        anova_tbl = sm.stats.anova_lm(model, typ=2)
                        ss_total = float(((dfraw[metric] - dfraw[metric].mean())**2).sum())
                        eta2 = (anova_tbl["sum_sq"] / ss_total).rename("eta_sq").to_frame()
                        out = pd.concat([anova_tbl, eta2], axis=1)
                        st.dataframe(out, use_container_width=True)

                        alpha = st.slider("유의수준(alpha)", 0.001, 0.1, 0.05, 0.001)
                        sig = out[out["PR(>F)"] < alpha].sort_values("PR(>F)")
                        if not sig.empty:
                            st.markdown("##### 📌 해석 요약")
                            st.markdown("\n".join([f"- **{idx}**: p={r['PR(>F)']:.3g}, η²={r['eta_sq']:.3f}" for idx,r in sig.iterrows()]))
                        else:
                            st.caption("유의한 효과가 발견되지 않았습니다.")
                        st.caption(f"모형 적합도: R²={model.rsquared:.3f}, Adj.R²={model.rsquared_adj:.3f}")

                        resid = model.resid
                        st.markdown("##### 잔차 진단")
                        if len(resid) >= 3:
                            try:
                                W,p = sps.shapiro(resid.sample(min(len(resid), 500), random_state=0)) if len(resid)>500 else sps.shapiro(resid)
                                st.write(f"Shapiro-Wilk: W={W:.4f}, p={p:.3g}")
                            except Exception as e:
                                st.caption(f"Shapiro-Wilk 계산 실패: {e}")
                        # QQ-Plot
                        qq = sps.probplot(resid, dist="norm")
                        qq_df = pd.DataFrame({"Theoretical": qq[0][0], "Residual": np.sort(resid)})
                        st.altair_chart(alt.Chart(qq_df).mark_point().encode(x="Theoretical:Q", y="Residual:Q").properties(height=280), use_container_width=True)
                        # Hist
                        st.altair_chart(alt.Chart(pd.DataFrame({"resid": resid})).mark_bar().encode(x=alt.X("resid:Q", bin=alt.Bin(maxbins=40)), y="count()").properties(height=200), use_container_width=True)
                    except Exception as e:
                        st.error(f"ANOVA 실패: {e}")

# ------------------------------
# Data Tables 탭 (편집/읽기 분리 + 파일명 라벨)
# ------------------------------
with tabs[3]:
    st.subheader("🧾 CSV 테이블(편집/저장)")
    bp = st.session_state.base_path
    exp = st.session_state.selected_exp
    coord = st.session_state.selected_coord
    if not (bp and exp and coord):
        st.info("좌측에서 시나리오를 먼저 선택하세요.")
    else:
        coord_folder = Path(bp) / "scenarios" / exp / coord
        st.caption(str(coord_folder))
        csvs = list_coord_csvs(bp, exp, coord)
        # 편집 대상에서 안전센터/소방서 원본 제외
        csvs_editable = [p for p in csvs if os.path.basename(p) != "안전센터와 소방서.csv"]
        if not csvs_editable:
            st.info("편집할 CSV가 없습니다.")
        else:
            labels = {p: os.path.basename(p) for p in csvs_editable}
            target = st.selectbox("편집할 CSV", options=list(labels.keys()), format_func=lambda p: labels[p])
            df = read_csv_smart(target)
            edit = st.data_editor(df, use_container_width=True, num_rows="dynamic", height=400)
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("💾 저장(백업 자동)"):
                    write_csv_smart(edit, target)
                    st.success("저장 완료")
            with c2:
                if st.button("🔄 새로고침"):
                    st.experimental_rerun()
            with c3:
                yaml_path = find_yaml_in_coord(bp, exp, coord)
                if yaml_path and st.button("▶️ 수정값으로 재실행 (main.py)"):
                    code, out, err = run_main_py(bp, yaml_path)
                    st.success(f"종료 코드: {code}")
                    st.expander("stdout").write(out or "")
                    st.expander("stderr").write(err or "")

        st.markdown("#### 병원 마스터(엑셀, 읽기전용)")
        hdf = read_excel_hospital(bp)
        if hdf is not None and not hdf.empty:
            st.dataframe(hdf.head(200), use_container_width=True, height=280)
        else:
            st.caption("엑셀 결합 데이터.xlsx 미존재 또는 로드 실패")

        st.markdown("#### 안전센터·소방서 마스터(읽기전용)")
        global_center_csv = Path(bp) / "scenarios" / "안전센터와 소방서.csv"
        if global_center_csv.is_file():
            cdf = read_csv_smart(str(global_center_csv))
            st.dataframe(cdf.head(200), use_container_width=True, height=260)
        else:
            st.caption("안전센터와 소방서.csv 미존재")

# ------------------------------
# Generate 탭 
# ------------------------------
def parse_env_kv(text: str):
    env = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env

if "gen_state" not in st.session_state:
    st.session_state.gen_state = {}
if "env_txt" not in st.session_state:
    st.session_state.env_txt = ""
if "env_txt2" not in st.session_state:
    st.session_state.env_txt2 = ""

with tabs[4]:
    st.subheader("🧪 시나리오 생성 · 실행")

    bp = st.session_state.base_path
    if not base_ok(bp):
        st.info("좌측에서 base_path를 먼저 설정하세요.")
        st.stop()

    # ─────────────────────────────────────────────────────────────────
    # Orchestrator 로드
    # ─────────────────────────────────────────────────────────────────
    try:
        from orchestrator import Orchestrator
    except Exception as e:
        st.error("orchestrator.py를 프로젝트 루트에 두세요.")
        st.exception(e)
        st.stop()

    # 유틸
    def parse_env_kv(text: str):
        env = {}
        for line in (text or "").splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
        return env

    if "gen_state" not in st.session_state:
        st.session_state.gen_state = {}
    if "env_txt" not in st.session_state:
        st.session_state.env_txt = ""
    if "env_txt2" not in st.session_state:
        st.session_state.env_txt2 = ""

    # ─────────────────────────────────────────────────────────────────
    # 1) 시나리오 생성
    # ─────────────────────────────────────────────────────────────────
    st.markdown("### 1) 시나리오 생성")
    colA, colB, colC = st.columns(3)
    with colA:
        latitude  = st.number_input("위도 (latitude)", value=37.465833, format="%.6f")
        incident_size = st.number_input("환자수 (incident_size)", value=30, min_value=1, step=1)
        amb_velocity  = st.number_input("구급차 속도 (km/h)", value=40, min_value=1, step=1)
        total_samples = st.number_input("시뮬레이션 반복 (totalSamples)", value=10, min_value=1, step=1)
    with colB:
        longitude = st.number_input("경도 (longitude)", value=126.443333, format="%.6f")
        amb_size  = st.number_input("구급차 수 (amb_size)", value=30, min_value=1, step=1)
        uav_velocity = st.number_input("UAV 속도 (km/h)", value=80, min_value=1, step=1)
        random_seed  = st.number_input("랜덤시드", value=0, min_value=0, step=1)
    with colC:
        uav_size = st.number_input("UAV 수 (uav_size)", value=3, min_value=0, step=1)
        exp_id   = st.text_input("실험ID(선택, 미입력시 자동: exp_타임스탬프)", value="")
        hospital_max_send_coeff = st.text_input("max_send_coeff (예: 1.05,1)", value="1,1")
        buffer_ratio = st.number_input("buffer_ratio", value=1.5, min_value=1.0, step=0.1)


    if st.button("📦 시나리오 생성"):
        try:
            env = parse_env_kv(st.session_state.env_txt)
            extra_args = {
                "buffer_ratio": buffer_ratio,
                "hospital_max_send_coeff": hospital_max_send_coeff.strip()
            }
            orc = Orchestrator(base_path=bp)
            res = orc.generate_scenario(
                latitude=latitude, longitude=longitude,
                incident_size=int(incident_size),
                amb_size=int(amb_size), uav_size=int(uav_size),
                amb_velocity=int(amb_velocity), uav_velocity=int(uav_velocity),
                total_samples=int(total_samples), random_seed=int(random_seed),
                exp_id=(exp_id.strip() or None),
                extra_env=env, extra_args=extra_args
            )

            # 최신 상태 보관
            st.session_state.gen_state = {
                "exp_id": res["exp_id"],
                "coord": res["coord"],
                "config_path": res["config_path"],
                "summary_csv_path": res["summary_csv_path"],
                "summary_csv_path_legacy": res["summary_csv_path_legacy"],
                "log_file": res["log_file"]
            }

            st.success("시나리오 생성 완료!")
            st.write(f"• 실험ID: `{res['exp_id']}`")
            st.write(f"• 좌표: `{res['coord']}`")
            st.write(f"• CONFIG_PATH: `{res['config_path']}`")
            st.write(f"• 요약 CSV(신규): `{res['summary_csv_path']}`")
            st.write(f"• 로그 파일: `{res['log_file']}`")

        except Exception as e:
            st.error("시나리오 생성 중 오류")
            st.exception(e)

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────────
    # 2) 시뮬레이션 실행 (CONFIG_PATH 자동)
    # ─────────────────────────────────────────────────────────────────
    st.markdown("### 2) 시뮬레이션 실행 (실험·좌표 선택)")
    # 실험/좌표 목록 만들기
    exps = list_experiments_any(bp)
    # 기본 선택: 방금 생성한 실험이 있으면 우선 사용
    default_exp = st.session_state.gen_state.get("exp_id") if st.session_state.gen_state else ""
    if default_exp not in exps:
        default_exp = st.session_state.selected_exp if "selected_exp" in st.session_state else ""
    exp_idx = (exps.index(default_exp) if default_exp in exps else 0)
    sel_exp = st.selectbox("실험 선택", options=exps, index=exp_idx)

    coords = list_coords_from_scenarios(bp, sel_exp) if sel_exp else []
    default_coord = st.session_state.gen_state.get("coord") if st.session_state.gen_state and st.session_state.gen_state.get("exp_id")==sel_exp else ""
    if default_coord not in coords:
        default_coord = st.session_state.selected_coord if "selected_coord" in st.session_state and st.session_state.selected_exp==sel_exp else ""
    coord_idx = (coords.index(default_coord) if default_coord in coords else 0) if coords else 0
    sel_coord = st.selectbox("좌표 선택", options=coords or [""], index=coord_idx)


    # 실행 버튼
    if st.button("▶️ 시뮬레이션 실행"):
        try:
            if not sel_exp or not sel_coord:
                st.warning("실험과 좌표를 먼저 선택하세요.")
                st.stop()
            # CONFIG_PATH 자동 조립
            cfg_path = os.path.join(bp, "scenarios", sel_exp, sel_coord, f"config_{sel_coord}.yaml")
            if not os.path.exists(cfg_path):
                st.error(f"CONFIG 파일을 찾을 수 없습니다: {cfg_path}")
                st.stop()

            env2 = parse_env_kv(st.session_state.env_txt2)
            orc = Orchestrator(base_path=bp)
            res2 = orc.run_simulation(config_path=cfg_path, extra_env=env2)

            # 최신 상태 업데이트
            st.session_state.gen_state.update({
                "exp_id": res2["exp_id"],
                "coord": res2["coord"],
                "config_path": res2["config_path"],
                "summary_csv_path": res2["summary_csv_path"],
                "summary_csv_path_legacy": res2["summary_csv_path_legacy"],
                "log_file": res2["log_file"]
            })

            st.success("시뮬레이션 완료!")
            st.write(f"• 실험ID: `{res2['exp_id']}`")
            st.write(f"• 좌표: `{res2['coord']}`")
            st.write(f"• 요약 CSV(신규): `{res2['summary_csv_path']}`")
            st.write(f"• 로그 파일: `{res2['log_file']}`")
            st.caption("Scenarios/Maps 탭에서 바로 확인해 보세요.")

        except Exception as e:
            st.error("시뮬레이션 실행 중 오류")
            st.exception(e)

