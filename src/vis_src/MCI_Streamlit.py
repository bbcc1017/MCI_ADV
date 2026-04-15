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
# 4) Analytics: 상단 원본 표 유지 + "Sort by" 선택(Reward↓, PDR↑(작을수록 좋음), Time↑(짧을수록 좋음))로 전체 표 재정렬
#    - 히트맵/막대 그래프 제거 → 대신 ANOVA 스위트 추가(Full Factorial, M1=Reward 기본)
#      · raw(results_{coord}.txt) 파싱 → Phase, RedPolicy, RedAction, YellowAction × Sample
#      · statsmodels 있으면 OLS+Type-II ANOVA, 잔차 정규성(Shapiro)·QQ 스캐터·잔차 히스토그램 제공
# 5) Data Tables: 편집 대상 셀렉터에 파일명만 노출(경로 숨김), "안전센터와 소방서.csv"는 편집 목록에서 제외
# -------------------------------------------------------------------------------------------------
import os, re, json, shutil, subprocess, math, ast, sys
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

# Tukey HSD 수렴 속도 경고 무시
import warnings
from scipy.integrate import IntegrationWarning
warnings.filterwarnings("ignore", category=IntegrationWarning)


def _detect_repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / "src" / "sce_src" / "orchestrator.py").is_file():
            return parent
    return here


def _detect_cloud_base_path() -> str:
    for cand in ("/mount/src/mci_adv", "/mount/src/mci_adv/Simul_team"):
        p = Path(cand)
        if p.is_dir() and (p / "scenarios").is_dir():
            return cand
    return ""


REPO_ROOT = _detect_repo_root()
ORCHESTRATOR_DIR = REPO_ROOT / "src" / "sce_src"
if ORCHESTRATOR_DIR.is_dir():
    orch_path = str(ORCHESTRATOR_DIR)
    if orch_path not in sys.path:
        sys.path.insert(0, orch_path)

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
# Session defaults
# ------------------------------
CLOUD_BASE_PATH = _detect_cloud_base_path()
IS_CLOUD = bool(CLOUD_BASE_PATH)
DEFAULT_LOCAL_BASE_PATH = str(REPO_ROOT) if (REPO_ROOT / "scenarios").is_dir() else ""

if "base_path" not in st.session_state:
    st.session_state.base_path = CLOUD_BASE_PATH if IS_CLOUD else DEFAULT_LOCAL_BASE_PATH
else:
    # Cloud에서는 항상 고정 (사용자가 바꿔도 즉시 원복)
    if IS_CLOUD and st.session_state.base_path != CLOUD_BASE_PATH:
        st.session_state.base_path = CLOUD_BASE_PATH

if "selected_exp" not in st.session_state:
    st.session_state.selected_exp = ""
if "selected_coord" not in st.session_state:
    st.session_state.selected_coord = ""
if "ps_running" not in st.session_state:
    st.session_state.ps_running = False
if "py_running" not in st.session_state:
    st.session_state.py_running = False

# ==== RAW results utils (results_{coord}.txt) ====
import os, re
import numpy as np
import pandas as pd

# RAW 라인의 숫자 탐지용
_RAW_FLOAT = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"

# RAW 파일에 저장된 메트릭 블록 순서 (코드 저장 순서와 동일)
RAW_METRIC_NAMES = ["Reward", "Time", "PDR", "Reward w.o.G", "PDR w.o.G"]

def _split_key_and_vals(line: str):
    """
    한 줄을 '키 문자열'과 '실수 리스트'로 분리.
    - 키와 값 사이는 콤마가 아니어도 됨. '첫 번째 숫자의 시작 위치'로 분리.
    """
    m = re.search(_RAW_FLOAT, line)
    if not m:
        return line.strip(), []
    key = line[:m.start()].strip().rstrip(",")
    vals = [float(x) for x in re.findall(_RAW_FLOAT, line[m.start():])]
    return key, vals

def _split_factors(rule_label: str):
    """
    'ReSTART, YellowHalf, Red Both_UAVFirst, Yellow OnlyUAV'
      -> (Phase, RedPolicy, RedAction, YellowAction)
    """
    parts = [p.strip() for p in rule_label.split(",")]
    phase = parts[0] if len(parts) > 0 else ""
    red_policy = parts[1] if len(parts) > 1 else ""

    def pick_mode(p: str, color: str):
        if not p:
            return ""
        for key in ("OnlyUAV", "OnlyAMB", "Both_UAVFirst", "Both_AMBFirst"):
            if key in p:
                return key
        toks = p.replace(",", " ").split()
        try:
            cidx = toks.index(color)
            return "_".join(toks[cidx+1:]) if cidx < len(toks)-1 else ""
        except ValueError:
            return "_".join(toks[1:]) if len(toks) > 1 else ""

    red_action = pick_mode(parts[2] if len(parts) > 2 else "", "Red")
    yellow_action = pick_mode(parts[3] if len(parts) > 3 else "", "Yellow")
    return phase, red_policy, red_action, yellow_action

def parse_raw_all_metrics(raw_path: str) -> dict:
    """
    results_{coord}.txt 전체를 읽어 메트릭별 wide 테이블을 반환.
    반환: {metric_name: DataFrame(64행 × [ScenarioIdx, Phase, RedPolicy, RedAction, YellowAction, metric 1회..R회])}
    - 블록 경계: '룰 키의 1사이클' 단위로 구분
    - 반복수(run) 열 개수는 파일에서 자동 감지
    """
    out = {}
    if not (raw_path and os.path.exists(raw_path)):
        return out

    # 1) 모든 줄을 (키, 값들)로 파싱
    rows = []
    with open(raw_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            key, vals = _split_key_and_vals(raw)
            if not vals:
                continue
            rows.append((key, vals))
    if not rows:
        return out

    # 2) 1사이클 길이(=룰 수) 탐지: 첫 키가 다시 등장하는 위치
    first_key = rows[0][0]
    L = None
    for i in range(1, len(rows)):
        if rows[i][0] == first_key:
            L = i
            break
    if L is None:
        L = len(rows)

    # 3) 블록(메트릭) 단위로 분할
    n_blocks = int(np.ceil(len(rows) / L))
    for b in range(n_blocks):
        block = rows[b*L : (b+1)*L]
        if not block:
            continue
        metric_name = RAW_METRIC_NAMES[b] if b < len(RAW_METRIC_NAMES) else f"Metric {b+1}"

        # run 수
        R = len(block[0][1])

        # 레코드 생성
        recs = []
        for idx, (label, vals) in enumerate(block):
            phase, red_policy, red_action, yellow_action = _split_factors(label)
            rec = {
                "ScenarioIdx": idx,
                "Phase": phase,
                "RedPolicy": red_policy,
                "RedAction": red_action,
                "YellowAction": yellow_action,
            }
            for r in range(R):
                rec[f"{metric_name} {r+1}회"] = vals[r] if r < len(vals) else np.nan
            recs.append(rec)

        out[metric_name] = pd.DataFrame.from_records(recs)

    return out

# ==== RAW → long parser for ANOVA ====
import os, re
import numpy as np
import pandas as pd

_RAW_FLOAT = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"

# RAW 파일 내 블록(지표) 이름 매핑 (파일 순서와 일치)
# ANOVA UI에서 쓰는 키와 일치하도록 언더스코어 버전으로 맞춤
RAW_BLOCK_NAMES = ["Reward", "Time", "PDR", "Reward_woG", "PDR_woG"]

def _split_key_vals(line: str):
    m = re.search(_RAW_FLOAT, line)
    if not m:  # 숫자 없음
        return line.strip(), []
    key = line[:m.start()].strip().rstrip(",")
    vals = [float(x) for x in re.findall(_RAW_FLOAT, line[m.start():])]
    return key, vals

def _split_factors(rule_label: str):
    parts = [p.strip() for p in rule_label.split(",")]
    phase = parts[0] if len(parts) > 0 else ""
    red_policy = parts[1] if len(parts) > 1 else ""
    def pick_mode(p: str, color: str):
        if not p: return ""
        for k in ("OnlyUAV","OnlyAMB","Both_UAVFirst","Both_AMBFirst"):
            if k in p: return k
        toks = p.replace(",", " ").split()
        try:
            cidx = toks.index(color)
            return "_".join(toks[cidx+1:]) if cidx < len(toks)-1 else ""
        except ValueError:
            return "_".join(toks[1:]) if len(toks) > 1 else ""
    red_action = pick_mode(parts[2] if len(parts)>2 else "", "Red")
    yellow_action = pick_mode(parts[3] if len(parts)>3 else "", "Yellow")
    return phase, red_policy, red_action, yellow_action

@st.cache_data(ttl=600)
def parse_raw_results(raw_path: str) -> pd.DataFrame:
    """
    results_(lat,lon).txt → long DF
    columns: ['rule','Phase','RedPolicy','RedAction','YellowAction','run','metric','value']
    """
    if not (raw_path and os.path.exists(raw_path)):
        return pd.DataFrame(columns=["rule","Phase","RedPolicy","RedAction","YellowAction","run","metric","value"])

    # 모든 줄을 (키, 값들)로 파싱
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

    # 1사이클 길이(=룰 수) 탐지: 첫 키 재등장 위치
    first_key = rows[0][0]
    L = None
    for i in range(1, len(rows)):
        if rows[i][0] == first_key:
            L = i
            break
    if L is None:
        L = len(rows)

    n_blocks = int(np.ceil(len(rows) / L))
    out_recs = []
    for b in range(n_blocks):
        block = rows[b*L:(b+1)*L]
        if not block:
            continue
        metric_name = RAW_BLOCK_NAMES[b] if b < len(RAW_BLOCK_NAMES) else f"Metric_{b+1}"
        # run 수 (값 개수로 자동 결정)
        R = len(block[0][1])
        for (label, vals) in block:
            Phase, RedPolicy, RedAction, YellowAction = _split_factors(label)
            rule = f"{Phase}, {RedPolicy}, Red {RedAction}, Yellow {YellowAction}".strip().replace("  "," ")
            for r_idx, v in enumerate(vals, start=1):
                out_recs.append({
                    "rule": rule,
                    "Phase": Phase,
                    "RedPolicy": RedPolicy,
                    "RedAction": RedAction,
                    "YellowAction": YellowAction,
                    "run": r_idx,           # 1..R
                    "metric": metric_name,  # 'Reward' / 'Time' / 'PDR' / 'Reward_woG' / 'PDR_woG'
                    "value": v
                })
    df = pd.DataFrame.from_records(out_recs)
    # 카테고리 정렬(선택)
    if not df.empty:
        # rule 순서를 첫 블록 순서로 고정
        first_block_rules = [rows[i][0] for i in range(L)]
        # 위의 first_block_rules는 라벨 원문. 우리가 만든 'rule' 문자열과 다를 수 있어서 패스.
        # 필요 시 Phase/RedPolicy/RedAction/YellowAction 조합으로 정렬키 생성 가능.
        df["run"] = df["run"].astype(int)
    return df

def _means_series(df: pd.DataFrame, group_col: str, value_col: str) -> pd.Series:
    """
    그룹 평균을 항상 Series로 반환(판다스 버전/상황과 무관하게 안전).
    반환: index=group_col, values=평균(value_col)
    """
    tmp = df.groupby(group_col, as_index=False).agg({value_col: "mean"})
    s = tmp.set_index(group_col)[value_col]
    # 혹시 숫자형이 아니면 숫자로 강제
    return pd.to_numeric(s, errors="coerce")




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
@st.cache_data(ttl=60)
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
@st.cache_data(ttl=60)
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


@st.cache_data(ttl=300)
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

@st.cache_data(ttl=600)
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
                st.warning(f"Excel load failed: {excel_path} ({e})")
    return None

@st.cache_data(ttl=300)
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
    site_info = {"Coordinate":"","Address":"","Road Address":""}
    sim_info: Dict[str,str] = {}
    if df is None or df.empty: return site_info, sim_info

    # 최신 차수 데이터 사용 (마지막 행)
    latest_row_idx = -1

    addr_cols = [c for c in df.columns if ("주소" in str(c) and "도로" not in str(c)) or "address" in str(c).lower()]
    road_cols = [c for c in df.columns if "도로명" in str(c)]
    if addr_cols:
        v = df.iloc[latest_row_idx][addr_cols[0]]; site_info["Address"] = "" if pd.isna(v) else str(v)
    if road_cols:
        v = df.iloc[latest_row_idx][road_cols[0]]; site_info["Road Address"] = "" if pd.isna(v) else str(v)
    start_idx = None
    for i,c in enumerate(df.columns):
        if "시나리오생성_시작" in str(c):
            start_idx = i; break
    if start_idx is not None:
        row = df.iloc[latest_row_idx, start_idx:]
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


@st.cache_data(ttl=300)
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


@st.cache_data(ttl=600, show_spinner=False)
def _load_scenario_csvs(bp: str, exp: str, coord: str):
    """Load & rename scenario CSVs (cached at top level)."""
    base = Path(bp) / "scenarios" / exp / coord
    _KR_HOSP = {"종별코드":"Grade Code","요양기관명":"Hospital Name","수술실수":"ORs","병상수":"Beds","헬기장 여부":"Helipad"}
    _KR_AMB  = {"안전센터/소방서이름":"Fire Station","보유대수":"Fleet Size"}

    def _read(p, enc=None):
        if not p.is_file(): return pd.DataFrame()
        return pd.read_csv(p, encoding=enc) if enc else pd.read_csv(p)

    h = _read(base / "hospital_info_road.csv").rename(columns=_KR_HOSP)
    c = _read(Path(bp) / "scenarios" / "안전센터와 소방서.csv", "cp949")
    a = _read(base / "amb_info_road.csv").rename(columns=_KR_AMB)
    dr = _read(base / "distance_Hos2Site_road.csv")
    he = _read(base / "hospital_info_euc.csv").rename(columns=_KR_HOSP)
    de = _read(base / "distance_Hos2Site_euc.csv")
    return h, c, a, dr, he, de


# ------------------------------
# Logs (실행 로그 탐색 + 파싱)
# ------------------------------
PHASES = ["START", "ReSTART"]
RED_POLICY = ["RedOnly", "YellowNearest"]
ACTIONS = ["OnlyUAV","Both_UAVFirst","Both_AMBFirst","OnlyAMB"]

RULE_HEADER_RE = re.compile(r"^(START|ReSTART)\s*,\s*(.+?)\s*$")
TUPLE_LINE_RE = re.compile(r"^\(\s*([^,]+)\s*,\s*(\d+)\s*,\s*'([A-Za-z_]+)'\s*,\s*\(([^)]*)\)\s*\)\s*$")
ACTION_RE = re.compile(r"^Action:\s*\[([^\]]+)\]")

# Iteration 라인 파싱 (예: "Iter : 3" 또는 "Iteration: 3")
ITER_RE = re.compile(r'^\s*(?:Iter(?:ation)?\s*[:=]\s*)(\d+)\b', re.I)
NP_SCALAR_RE = re.compile(r"^np\.(?:float|int)\d+\((.+)\)$")
NP_WRAP_RE = re.compile(r"np\.(?:float|int)\d+\(\s*([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*\)")


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
    "**Action Index Reference**\n"
    "- `action[0] = p_class` → Patient severity (0=Red, 1=Yellow, 2=Green)\n"
    "- `action[1] = destination` → 0=On-site wait, 1…N → Hospital index+1\n"
    "- `action[2] = mode` → 0=AMB(Ambulance), 1=UAV"
)

def _strip_np_scalar(token: str) -> str:
    s = token.strip()
    m = NP_SCALAR_RE.match(s)
    return m.group(1).strip() if m else s

def _coerce_float(token: str) -> Optional[float]:
    if token is None:
        return None
    s = _strip_np_scalar(token)
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None

def _coerce_int(token: str) -> Optional[int]:
    if token is None:
        return None
    s = _strip_np_scalar(token)
    if not s:
        return None
    try:
        v = float(s)
    except Exception:
        return None
    return int(v) if v.is_integer() else None

def _parse_event_tuple_line(line: str) -> Optional[Tuple[float, int, str, List[Union[int, float]]]]:
    if not line or line[0] != "(" or line[-1] != ")":
        return None
    clean = NP_WRAP_RE.sub(r"\1", line)
    try:
        t, eid, ev, args = ast.literal_eval(clean)
    except Exception:
        return None
    if not isinstance(ev, str):
        return None
    try:
        t_val = float(t)
        eid_val = int(eid)
    except Exception:
        return None
    if isinstance(args, (list, tuple)):
        args_list = list(args)
    else:
        args_list = [args] if args is not None else []
    parsed_args: List[Union[int, float]] = []
    for a in args_list:
        ival = _coerce_int(str(a))
        if ival is None:
            fval = _coerce_float(str(a))
            if fval is None:
                continue
            parsed_args.append(fval)
        else:
            parsed_args.append(ival)
    return t_val, eid_val, ev, parsed_args


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
                vec = []
                for part in parts:
                    if not part:
                        continue
                    ival = _coerce_int(part)
                    if ival is None:
                        fval = _coerce_float(part)
                        if fval is None:
                            continue
                        vec.append(fval)
                    else:
                        vec.append(ival)
                if vec:
                    cur["actions"].append(vec)
            except Exception:
                pass
            continue

        parsed = _parse_event_tuple_line(s)
        if parsed:
            t, eid, ev, args = parsed
            rec = {"t": t, "eid": eid, "ev": ev, "p": None, "a": None, "u": None, "h": None}
            if ev in EV_ARG_PARSERS:
                try:
                    rec.update(EV_ARG_PARSERS[ev](args))
                except Exception:
                    pass
            cur["events"].append(rec)
            continue

        mt = TUPLE_LINE_RE.match(s)
        if mt:
            t = _coerce_float(mt.group(1))
            if t is None:
                continue
            eid = int(mt.group(2))
            ev = mt.group(3)
            args_raw = [x.strip() for x in mt.group(4).split(',') if x.strip() != '']
            args = []
            for a in args_raw:
                ival = _coerce_int(a)
                if ival is None:
                    fval = _coerce_float(a)
                    if fval is None:
                        continue
                    args.append(fval)
                else:
                    args.append(ival)
            rec = {"t": t, "eid": eid, "ev": ev, "p": None, "a": None, "u": None, "h": None}
            if ev in EV_ARG_PARSERS:
                try:
                    rec.update(EV_ARG_PARSERS[ev](args))
                except Exception:
                    pass
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
        remark = "Normal"
        if len(hist) >= 2:
            hosp_set = {h for (_,h,_) in hist}; mode_set = {m for (m,_,_) in hist}
            if len(hosp_set) > 1 or len(mode_set) > 1:
                remark = "divert"
        rows.append({
            "PatientID": p,
            "Rescue Time": info.get("rescue_t"),
            "Transport Mode": info.get("mode"),
            "Dest. Hospital": info.get("hospital"),
            "Hospital Arrival": info.get("arrive_t"),
            "Care Ready": info.get("care_ready_t"),
            "Care Complete": info.get("def_care_t"),
            "Remarks": remark,
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
# 지도 보조 (혼잡도/범례/UAV/요약) - 카카오 API 기준
# ------------------------------
# Kakao traffic_state: 0=정보없음, 1=정체, 2=지체, 3=서행, 4=원활, 6=교통사고
CONG_COLORS = {0:"#888888", 1:"#FF0000", 2:"#FF6347", 3:"#FFD700", 4:"#7CFC00", 6:"#000000"}
CONG_LABELS = {0:"Unknown", 1:"Congested", 2:"Slow", 3:"Moderate", 4:"Clear", 6:"Accident"}
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
    meta = obj.get("meta", {})
    api_provider = meta.get("api_provider", "naver")

    if api_provider == "kakao":
        # Kakao API: Use meta fields directly (already extracted)
        dist_km = meta.get("distance_km")
        dur_min = meta.get("duration_min")
        # Kakao doesn't have guide in the same format as Naver
        return dist_km, dur_min, []
    else:
        # Naver API: Extract from payload
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
        # Handle both Naver "instructions" and Kakao "guidance" fields
        inst = str(g.get("instructions") or g.get("guidance", "")).replace("<", "&lt;").replace(">", "&gt;")
        gd = float(g.get("distance", 0))/1000.0 if g.get("distance") is not None else None

        # Handle different duration formats
        # Naver API: duration in milliseconds
        # Kakao API: duration in seconds
        dur_val = g.get("duration", 0)
        if dur_val and dur_val > 1000:
            # Likely Naver (milliseconds)
            gm = float(dur_val) / 60000.0
        else:
            # Likely Kakao (seconds) or zero
            gm = float(dur_val or 0) / 60.0

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
        tooltip="Incident Site",
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


# 기존 add_hospital_marker(...)를 아래처럼 정리
def add_hospital_marker(
    m: folium.Map,
    name: str,
    grade_code: Union[int, str],
    latlon: Tuple[float, float],
    op_rooms: Optional[Union[int, float]] = None,  # 수술실수
    beds: Optional[Union[int, float]] = None,      # 병상수
    extra_lines: Optional[List[str]] = None,
):
    try:
        g = int(float(str(grade_code)))
    except:
        g = -1
    color = "red" if g == 1 else ("orange" if g == 11 else "green")

    body = [f"<b>{name}</b>"]                    # 제목
    body.append(f"lat,lon={latlon[0]:.6f},{latlon[1]:.6f}")  # ① 좌표
    if op_rooms is not None and not (isinstance(op_rooms, float) and math.isnan(op_rooms)):
        body.append(f"OR={int(op_rooms)}")              # ② 수술실수
    if beds is not None and not (isinstance(beds, float) and math.isnan(beds)):
        body.append(f"Beds={int(beds)}")                    # ③ 병상수
    body.append(f"GradeCode={grade_code}")                    # ④ 등급코드
    if extra_lines:                                           # ⑤ 병원등급, 거리, 소요시간 등
        body += [x for x in extra_lines if x]

    folium.Marker(
        location=[latlon[0], latlon[1]],
        icon=folium.Icon(color=color, icon="plus", prefix="fa"),
        tooltip=name,
        popup="<br>".join(body)
    ).add_to(m)



def draw_route_from_json(m: folium.Map, route_obj: dict, highlight: bool=False):
    meta = route_obj.get("meta", {})
    api_provider = meta.get("api_provider", "naver")

    if api_provider == "kakao":
        # Kakao API: Parse kakao_response structure
        payload = (route_obj.get("payload") or {}).get("kakao_response", {})
        routes = payload.get("routes", [])
        if not routes:
            return

        route = routes[0]
        sections = route.get("sections", [])
        if not sections:
            return

        # Kakao API structure: sections[0].roads[]
        roads = sections[0].get("roads", [])

        for road in roads:
            traffic_state = road.get("traffic_state", 0)
            traffic_speed = road.get("traffic_speed")
            road_name = road.get("name", "")
            vertexes = road.get("vertexes", [])

            # Convert vertexes from [lon, lat, lon, lat, ...] to [[lat, lon], ...]
            latlngs = []
            for i in range(0, len(vertexes), 2):
                if i + 1 < len(vertexes):
                    latlngs.append([vertexes[i+1], vertexes[i]])  # [lat, lon]

            if not latlngs:
                continue

            # Map Kakao traffic_state directly
            # Kakao: 0=정보없음, 1=정체, 2=지체, 3=서행, 4=원활, 6=교통사고
            cong = traffic_state

            # Build tooltip with road info
            tooltip_parts = []
            if road_name:
                tooltip_parts.append(road_name)
            tooltip_parts.append(CONG_LABELS.get(cong, "미확인"))
            if traffic_speed is not None:
                tooltip_parts.append(f"{traffic_speed:.0f}km/h")
            tooltip_text = " · ".join(tooltip_parts)

            folium.PolyLine(
                locations=latlngs,
                color=CONG_COLORS.get(cong, "#888888"),
                weight=8 if highlight else 5,
                opacity=0.9 if highlight else 0.7,
                tooltip=tooltip_text
            ).add_to(m)

    elif api_provider == "osrm":
        # OSRM: GeoJSON LineString geometry, no congestion info → 단일 색 폴리라인
        payload = (route_obj.get("payload") or {}).get("osrm_response", {})
        routes = payload.get("routes", [])
        if not routes:
            return
        geom = routes[0].get("geometry", {}) or {}
        coords = geom.get("coordinates", []) or []
        # GeoJSON: [[lon, lat], ...] → folium용 [[lat, lon], ...]
        latlngs = [[c[1], c[0]] for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
        if not latlngs:
            return
        meta_loc = route_obj.get("meta") or {}
        dist_km = meta_loc.get("distance_km")
        dur_min = meta_loc.get("duration_min")
        try:
            tooltip_text = f"OSRM · {float(dist_km):.2f}km · {float(dur_min):.1f}min"
        except (TypeError, ValueError):
            tooltip_text = "OSRM"
        folium.PolyLine(
            locations=latlngs,
            color=CONG_COLORS.get(0, "#3388ff"),  # 정보없음 색상 (단일)
            weight=8 if highlight else 5,
            opacity=0.9 if highlight else 0.7,
            tooltip=tooltip_text,
        ).add_to(m)

    else:
        # Naver API: Original logic
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

        # 정확한 경로로 속도 읽기
        amb_speed = None
        uav_speed = None

        # entity_info 구조에서 읽기
        if isinstance(y, dict) and "entity_info" in y:
            entity = y["entity_info"]

            # ambulance.velocity
            if isinstance(entity, dict) and "ambulance" in entity:
                amb_data = entity["ambulance"]
                if isinstance(amb_data, dict) and "velocity" in amb_data:
                    amb_speed = float(amb_data["velocity"])

            # uav.velocity
            if isinstance(entity, dict) and "uav" in entity:
                uav_data = entity["uav"]
                if isinstance(uav_data, dict) and "velocity" in uav_data:
                    uav_speed = float(uav_data["velocity"])

        return amb_speed, uav_speed
    except Exception:
        return None, None


def get_total_samples_from_yaml(yaml_path: Optional[str]) -> int:
    """YAML에서 total_samples 값 읽기 (성능 최적화용)"""
    if not yaml_path or not exists_file(yaml_path):
        return 0
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            y = yaml.safe_load(f)
        return y.get('rule_info', {}).get('total_samples', 0)
    except Exception:
        return 0


# ------------------------------
# 실행/재실행
# ------------------------------
# PowerShell 관련 함수는 더 이상 사용하지 않음 (Orchestrator 사용)

# ------------------------------
# 페이지 공통 설정 + CSS(멀티셀렉트 ellipsis 완화)
# ------------------------------
st.set_page_config(page_title="MCI Streamlit", page_icon="📊", layout="wide")


with st.sidebar:
    st.header("Settings")

    base_input = st.text_input(
        "base_path",
        st.session_state.base_path,
        placeholder="e.g. C:\\Users\\USER\\MCI",
        disabled=IS_CLOUD,
    )

    if IS_CLOUD:
        st.caption(f"☁️ Cloud mode: base_path is fixed to `{CLOUD_BASE_PATH}`.")

    # 로컬에서만 버튼 동작
    if (not IS_CLOUD) and st.button("Set base_path"):
        st.session_state.base_path = norm(base_input)
        if base_ok(norm(base_input)):
            st.success("✅ base_path set! Select a scenario or create a new one in the Generate tab.")
    if st.session_state.base_path and not base_ok(st.session_state.base_path):
        st.warning("Invalid base_path. (scenarios folder required)")
    # (removed guidance text for cleaner UI)
    if base_ok(st.session_state.base_path):
        exps = list_experiments_any(st.session_state.base_path)
        st.caption("Select existing scenario (optional)")

        # Ensure stored value is still valid; reset if not
        if st.session_state.selected_exp not in exps:
            st.session_state.selected_exp = ""
        # Reset coord when exp changes
        def _on_exp_change():
            st.session_state.selected_coord = ""

        st.selectbox(
            "Experiment ID",
            options=[""] + exps,
            key="selected_exp",
            on_change=_on_exp_change,
        )
        coords = list_coords_from_scenarios(st.session_state.base_path, st.session_state.selected_exp) if st.session_state.selected_exp else []
        if st.session_state.selected_coord not in coords:
            st.session_state.selected_coord = ""
        st.selectbox(
            "Coordinate folder",
            options=[""] + coords,
            key="selected_coord",
        )

        # 1) 미니맵 (좌표 선택시)
        if st.session_state.selected_coord:
            lat, lon = coord_center(st.session_state.selected_coord)
            st.caption("Current Coordinate")

            # ── folium 기반 렌더(표출 로직 동일: 한 점만) ────────────────
            try:
                import folium
                from streamlit_folium import st_folium

                chosen_tile = "CartoDB positron"

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
                st_folium(m, width='stretch', height=260)

            except Exception:
                # (폴백) streamlit 기본 지도 (타일 커스텀 불가)
                st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), width='stretch')

        st.divider()



# CSS: 전역 UI 테마 + 멀티셀렉트 폭 확장
st.markdown("""
<style>
/* ── 원본 보존: 멀티셀렉트 폭 ── */
.stMultiSelect [data-baseweb="select"]{max-width:100%!important}

/* ── 폰트 ── */
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=DM+Sans:wght@400;500;600;700&display=swap');
html, body, .stApp, [data-testid="stAppViewContainer"] {
    font-family: 'DM Sans', -apple-system, sans-serif !important;
}
h1, h2, h3, h4, h5, h6 {
    font-family: 'Outfit', 'DM Sans', -apple-system, sans-serif !important;
}

/* ── 배경 ── */
.stApp {
    background: #141417;
}

/* ── 사이드바 ── */
[data-testid="stSidebar"] {
    background: #1c1c21 !important;
    border-right: 1px solid rgba(226, 160, 74, 0.1) !important;
}
[data-testid="stSidebar"] .stMarkdown h1,
[data-testid="stSidebar"] .stMarkdown h2,
[data-testid="stSidebar"] .stMarkdown h3 {
    color: #e2a04a !important;
}
[data-testid="stSidebar"] label {
    color: #a1a1aa !important;
    font-weight: 500;
    font-size: 0.85rem;
}

/* ── 메인 타이틀 ── */
h1 {
    font-weight: 700 !important;
    letter-spacing: -0.5px;
    padding-bottom: 4px;
    color: #e4e4e7 !important;
}
.gradient-text {
    background: linear-gradient(90deg, #e2a04a 0%, #2dd4bf 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

/* ── 서브헤더 ── */
h2, h3 {
    color: #e4e4e7 !important;
    font-weight: 600 !important;
    border-bottom: 2px solid rgba(226, 160, 74, 0.18);
    padding-bottom: 8px;
    margin-bottom: 16px !important;
}

/* ── 탭 바 ── */
.stTabs [data-baseweb="tab-list"] {
    background: #1c1c21;
    border-radius: 10px;
    padding: 4px;
    gap: 4px;
    border: 1px solid rgba(255, 255, 255, 0.06);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 10px 22px;
    font-weight: 500;
    color: #71717a !important;
    transition: all 0.2s ease;
}
.stTabs [aria-selected="true"] {
    background: rgba(226, 160, 74, 0.15) !important;
    color: #e2a04a !important;
    box-shadow: none;
    border-bottom: 2px solid #e2a04a;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #d4d4d8 !important;
    background: rgba(255, 255, 255, 0.04);
}
.stTabs [data-baseweb="tab-highlight"] { display: none; }
.stTabs [data-baseweb="tab-border"] { display: none; }

/* ── 버튼 (primary: amber) ── */
.stButton > button {
    border-radius: 8px !important;
    border: 1px solid rgba(226, 160, 74, 0.4) !important;
    background: rgba(226, 160, 74, 0.12) !important;
    color: #e2a04a !important;
    font-weight: 600 !important;
    padding: 8px 20px !important;
    transition: all 0.2s ease !important;
}
.stButton > button:hover {
    background: rgba(226, 160, 74, 0.22) !important;
    border-color: #e2a04a !important;
}
.stButton > button:active { transform: translateY(0); }

/* ── 입력 필드 ── */
[data-baseweb="input"],
[data-baseweb="select"] > div,
.stTextInput > div > div,
.stNumberInput > div > div > div {
    background: #1c1c21 !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 8px !important;
    transition: border-color 0.2s ease;
}
[data-baseweb="input"]:focus-within,
[data-baseweb="select"] > div:focus-within {
    border-color: rgba(226, 160, 74, 0.5) !important;
    box-shadow: 0 0 0 2px rgba(226, 160, 74, 0.08) !important;
}

/* ── 드롭다운 메뉴 ── */
[data-baseweb="popover"] {
    border-radius: 8px !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    overflow: hidden;
}
[data-baseweb="menu"] { background: #1c1c21 !important; }

/* ── Expander ── */
[data-testid="stExpander"] {
    background: #1c1c21 !important;
    border: 1px solid rgba(255, 255, 255, 0.06) !important;
    border-radius: 10px !important;
    overflow: hidden;
}
[data-testid="stExpander"]:hover {
    border-color: rgba(255, 255, 255, 0.12) !important;
}

/* ── 메트릭 카드 ── */
[data-testid="stMetric"] {
    background: #1c1c21;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-left: 3px solid #e2a04a;
    border-radius: 10px;
    padding: 18px 20px;
    transition: all 0.2s ease;
}
[data-testid="stMetric"]:hover {
    border-color: rgba(255, 255, 255, 0.1);
    border-left-color: #e2a04a;
}
[data-testid="stMetricLabel"] {
    color: #71717a !important;
    font-size: 0.82rem !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
[data-testid="stMetricValue"] {
    color: #e4e4e7 !important;
    font-weight: 700 !important;
}

/* ── 데이터프레임 ── */
[data-testid="stDataFrame"], .stDataFrame {
    border-radius: 8px !important;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.06);
}

/* ── 구분선 ── */
hr {
    border-color: rgba(255, 255, 255, 0.06) !important;
    margin: 24px 0 !important;
}

/* ── 알림 메시지 ── */
.stAlert, [data-testid="stAlert"] { border-radius: 8px !important; }

/* ── 체크박스/라디오 호버 ── */
.stCheckbox label:hover, .stRadio label:hover { color: #e2a04a !important; }

/* ── 스크롤바 ── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #141417; }
::-webkit-scrollbar-thumb {
    background: #3f3f46;
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover { background: #52525b; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1><span>🚑</span> <span class="gradient-text">MCI Disaster Simulation Dashboard</span></h1>', unsafe_allow_html=True)

tabs = st.tabs(["Maps", "Scenarios", "Analytics", "Data Tables", "Rerun"])

# ------------------------------
# Scenarios 탭
# ------------------------------
with tabs[1]:
    st.subheader("Selected Scenario")
    bp = st.session_state.base_path; exp = st.session_state.selected_exp; coord = st.session_state.selected_coord

    # 시나리오 변경 시 로그 로드 상태 리셋
    current_scenario_key = f"{exp}_{coord}"
    if st.session_state.get("last_scenario_key") != current_scenario_key:
        st.session_state.logs_loaded = False
        st.session_state.last_scenario_key = current_scenario_key

    if bp and exp and coord:
        yaml_path = find_yaml_in_coord(bp, exp, coord)
        st.write("**YAML**:", yaml_path or "(none)")
        
        smdf = read_experiment_summary_csv(bp, exp)
        info, site_addr = summarize_experiment(smdf) if smdf is not None else ({}, None)
        lat, lon = coord_center(coord)

        site_info, sim_info = summarize_experiment_extended(smdf)
        site_info["Coordinate"] = f"{lat:.6f}, {lon:.6f}"

        with st.expander("View Experiment Summary", expanded=True):
            left, right = st.columns([0.42, 0.58])
            with left:
                st.markdown("**Incident Site**")
                st.dataframe(pd.DataFrame({"Field":list(site_info.keys()), "Value":list(site_info.values())}), width='stretch', height=170)
            with right:
                st.markdown("**Simulation Info** (summary.csv)")
                if sim_info:
                    st.dataframe(pd.DataFrame(sorted(sim_info.items(), key=lambda x: x[0]), columns=["Field","Value"]), width='stretch', height=170)
                else:
                    st.caption("No simulation info columns found in summary.csv.")


        # 성능 최적화: summary CSV에서 시뮬레이션반복 직접 확인 (가장 최신 시도)
        total_samples = 0
        if smdf is not None and not smdf.empty and "시뮬레이션반복" in smdf.columns:
            # 현재 좌표에 해당하는 행들 중 가장 최근 시도 (마지막 행)
            coord_rows = smdf[smdf["좌표"] == coord]
            if not coord_rows.empty:
                latest_row = coord_rows.iloc[-1]  # 가장 마지막 시도
                total_samples_val = latest_row.get("시뮬레이션반복")
                if pd.notna(total_samples_val):
                    total_samples = int(total_samples_val)

        st.markdown("### Execution Log")

        # 디버깅: total_samples 값 확인
        if total_samples > 0:
            st.caption(f"🔍 Detected simulation iterations: {total_samples} (latest run in summary CSV)")

        # total_samples 기반 조건부 로딩 (101회 이상은 버튼도 비활성화)
        if total_samples >= 101:
            st.warning(f"⚠️ Simulation iterations ({total_samples}) >= 101. Log viewer disabled.")
            st.info(f"📁 Check log files directly: `experiment_logs/{coord}_*.txt`")
            st.caption(f"💡 For performance, logs with 101+ iterations should be checked in the source folder.")

            # 버튼 비활성화 상태로 표시
            st.button("Load Log Files", key="load_logs_btn_disabled", disabled=True, help="Log viewer is disabled for 101+ iterations")
            logs = None
        else:
            # 성능 최적화: 버튼 클릭 시에만 로그 로드 (다른 탭 로딩 속도 개선)
            if st.button("Load Log Files", key="load_logs_btn", help="Click to load logs"):
                st.session_state.logs_loaded = True

            if st.session_state.get("logs_loaded", False):
                logs = experiment_log_candidates(bp, exp, coord)
            else:
                st.info("💡 Click 'Load Log Files' above to view logs. (Disabled by default for faster tab loading)")
                logs = None

        if logs:
            log_sel = st.selectbox("Select Log File (experiment_logs/<coord>)", logs)
            log_text = _read_text_any(log_sel)
            blocks = parse_log_blocks(log_text)
            # (Unlabeled) 블록 숨김
            rule_list = [b["rule"] for b in blocks if b.get("rule")!="(Unlabeled)"] if blocks else []
            if not rule_list:
                st.info("No event patterns found. (Check log format)")
            else:
                sel_rule = st.selectbox("Select Rule", options=rule_list, index=0)

                # [추가] 선택한 Rule에서 사용 가능한 Iter 목록 수집
                rule_blocks = [b for b in blocks if b.get("rule") == sel_rule]
                iter_list = sorted({b.get("iter") for b in rule_blocks if b.get("iter") is not None})

                # [추가] Iter 셀렉터 (있을 때만 노출)
                sel_iter = None
                if iter_list:
                    sel_iter = st.selectbox("Select Iteration", iter_list, index=0, help="Based on 'Iter : n' lines in the log")
                    # 선택된 Rule & Iter 조합으로 필터
                    cand_blocks = [b for b in rule_blocks if b.get("iter") == sel_iter]
                else:
                    # Iter 라인이 없으면 기존 방식 유지(첫 블록)
                    st.caption("No 'Iter' lines found — treating this log as a single run.")
                    cand_blocks = rule_blocks

                # 선택 블록 최종 결정(복수면 첫 블록)
                blk = cand_blocks[0] if cand_blocks else None

                # (선택) 현재 선택 상태 안내
                st.caption(f"Selected: Rule={sel_rule} / Iter={sel_iter if sel_iter is not None else 'N/A'}")


                st.markdown("#### Patient Story (Summary)")
                psum = build_patient_summary(blk["events"]) if blk else pd.DataFrame()
                if psum.empty:
                    st.caption("No patient events found.")
                else:
                    st.dataframe(psum, width='stretch', height=340)
                    _suffix = f"_iter{sel_iter}" if sel_iter is not None else ""
                    st.download_button(
                        "⬇️ Patient Timeline (csv)",
                        psum.to_csv(index=False).encode('utf-8-sig'),
                        file_name=f"patient_timeline{_suffix}.csv"
                    )


                st.markdown("#### Full Event Table")
                ev_df = pd.DataFrame(blk["events"]).rename(columns={"t":"Time","eid":"EventID","ev":"Event","p":"Patient","a":"Ambulance","u":"UAV","h":"Hospital"}) if blk else pd.DataFrame()
                st.dataframe(ev_df, width='stretch', height=320)
                _suffix = f"_iter{sel_iter}" if sel_iter is not None else ""
                st.download_button("⬇️ Full Events (csv)", ev_df.to_csv(index=False).encode('utf-8-sig'), file_name=f"events_all{_suffix}.csv")

            st.markdown("#### View Raw Log")
            with st.expander("Expand Raw Text", expanded=False):
                st.code(log_text[:30000] + ("\n... (생략)" if len(log_text) > 30000 else ""))
                st.download_button("Download Raw Log", log_text, file_name=os.path.basename(log_sel))

            st.markdown("---")
            st.markdown("### Action/Rule Reference")
            st.markdown(ACTION_TOOLTIP_MD)
        else:
            st.info("No log files found for this combination.")


# ------------------------------
# Maps 탭 (복수선택 + UAV 출동/이송 토글 + 범례 강화)
# ------------------------------
with tabs[0]:
    st.subheader("Map Visualization")
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
    yaml_path = find_yaml_in_coord(bp, exp, coord)

    # JSON 경로(전체 로드; 지도 시각화용 - 시뮬레이션 반복수와 무관)
    c2s_all = load_json_files(rdirs["center2site"])  # Center→Site
    h2s_all = load_json_files(rdirs["hos2site"])     # Site→Hospitals

    # 병원/센터 메타
    hosp_xl   = read_excel_hospital(bp)   # 엑셀(요양기관명, 종별코드, x/y좌표, 전화/주소 등)

    # road/euc CSV (표/거리 참조용) — cached (top-level function)
    hinfo_df, center_df, ambinfo_df, dist_road_df, hinfo_euc_df, dist_euc_df = _load_scenario_csvs(bp, exp, coord)
    dist_road_map = dict(zip(dist_road_df["Index"], dist_road_df["distance"])) if not dist_road_df.empty else {}
    dur_road_map = dict(zip(dist_road_df["Index"], dist_road_df["duration"])) if not dist_road_df.empty and "duration" in dist_road_df.columns else {}
    dist_euc_map  = dict(zip(dist_euc_df["Index"], dist_euc_df["distance"])) if not dist_euc_df.empty else {}

    # 엑셀 이름→좌표 매핑
    xl_coord = {}
    if hosp_xl is not None and "요양기관명" in hosp_xl.columns:
        for _, rr in hosp_xl.iterrows():
            nm = str(rr.get("요양기관명","")).strip()
            y  = rr.get("y좌표", rr.get("y", None))
            x  = rr.get("x좌표", rr.get("x", None))
            if nm and pd.notna(y) and pd.notna(x):
                xl_coord[nm] = (float(y), float(x))

    # 종별코드 라벨링(요청: 1=상급종합병원, 11=종합병원, 그 외=일반병원)
    def code_to_grade(c):
        try:
            c = int(c)
        except Exception:
            return "Hospital"
        if c == 1:  return "Tertiary Hospital"
        if c == 11: return "General Hospital"
        return "Hospital"

    # ── 지도 테마(지도 바로 위) ─────────────────────────────────────────────
    theme = st.radio("Map Theme", ["Light","Dark"], horizontal=True, key="theme_radio_maps_bottom")
    if theme == "Light":
        tile_name = st.selectbox("Light Tile", ["OpenStreetMap","CartoDB Positron"], index=0, key="light_tile_select")
    else:
        tile_name = "CartoDB Dark_Matter"

    if not (bp and exp and coord):
        st.info("Select base_path / Experiment / Coord from the sidebar.")
        st.stop()

    # ─────────────────────────────────────────────────────────────────────
    # ① AMB 경로 (C→S 표 / S→H 표)
    # ─────────────────────────────────────────────────────────────────────
    _route_exp = st.expander("Route Details & Selection", expanded=False)
    with _route_exp:
        st.markdown("### AMB Routes")
        col_amb_c2s, col_amb_s2h = st.columns(2)

    # --- AMB: C→S(출동) 표 (표시, 인덱스, 안전센터/소방서, 거리) ---
    with col_amb_c2s:
        st.markdown("**Fire Station → Incident Site (Dispatch)**")

        # ✔ amb_info_road.csv 기준 표 구성 (인덱스/이름/거리=init_distance/시간=duration)
        if not ambinfo_df.empty:
            rename_dict = {
                "Index":"Index",
                "Fire Station":"Fire Station",
                "init_distance":"Distance(km)",
            }
            cols = ["Index","Fire Station","Distance(km)"]
            if "Fleet Size" in ambinfo_df.columns:
                rename_dict["Fleet Size"] = "Fleet Size"
                cols.append("Fleet Size")
            if "duration" in ambinfo_df.columns:
                rename_dict["duration"] = "Duration(min)"
                cols.append("Duration(min)")

            c2s_df = ambinfo_df.rename(columns=rename_dict)[cols].copy()
            # 모든 숫자 컬럼을 명시적으로 변환
            c2s_df["Index"] = pd.to_numeric(c2s_df["Index"], errors="coerce").fillna(0).astype(int)
            c2s_df["Distance(km)"] = pd.to_numeric(c2s_df["Distance(km)"], errors="coerce").fillna(0.0).round(2)
            if "Duration(min)" in c2s_df.columns:
                c2s_df["Duration(min)"] = pd.to_numeric(c2s_df["Duration(min)"], errors="coerce").fillna(0.0).round(1)
            if "Fleet Size" in c2s_df.columns:
                c2s_df["Fleet Size"] = pd.to_numeric(c2s_df["Fleet Size"], errors="coerce").fillna(1).astype(int)
            # 안전센터/소방서는 문자열로 확실히 변환
            c2s_df["Fire Station"] = c2s_df["Fire Station"].astype(str)
        else:
            c2s_df = pd.DataFrame({
                "Index": pd.Series(dtype='int'),
                "Fire Station": pd.Series(dtype='str'),
                "Distance(km)": pd.Series(dtype='float'),
                "Duration(min)": pd.Series(dtype='float'),
            })

        # 기본 선택 상태
        if "amb_c2s_sel_idx" not in st.session_state:
            st.session_state.amb_c2s_sel_idx = set(c2s_df["Index"].tolist())

        b1, b2 = st.columns(2)
        if b1.button("Select All (C→S)"):
            st.session_state.amb_c2s_sel_idx = set(c2s_df["Index"].tolist())
        if b2.button("Deselect All (C→S)"):
            st.session_state.amb_c2s_sel_idx = set()

        c2s_df_show = c2s_df.copy()
        c2s_df_show["Show"] = c2s_df_show["Index"].apply(lambda i: i in st.session_state.amb_c2s_sel_idx)
        # Explicit boolean conversion to prevent React error #185
        c2s_df_show["Show"] = c2s_df_show["Show"].astype(bool)
        # ▶ 표시를 맨 앞으로
        show_cols = ["Show","Index","Fire Station","Distance(km)"]
        if "Duration(min)" in c2s_df_show.columns:
            show_cols.append("Duration(min)")
        if "Fleet Size" in c2s_df_show.columns:
            show_cols.insert(3, "Fleet Size")
        c2s_df_show = c2s_df_show[show_cols].reset_index(drop=True)

        col_cfg = {
            "Show": st.column_config.CheckboxColumn("Show"),
            "Index": st.column_config.NumberColumn("Index", disabled=True),
            "Fire Station": st.column_config.TextColumn("Fire Station", disabled=True),
            "Distance(km)": st.column_config.NumberColumn("Distance(km)", disabled=True, format="%.2f"),
        }
        if "Duration(min)" in c2s_df_show.columns:
            col_cfg["Duration(min)"] = st.column_config.NumberColumn("Duration(min)", disabled=True, format="%.1f")
        if "Fleet Size" in c2s_df_show.columns:
            col_cfg["Fleet Size"] = st.column_config.NumberColumn("Fleet Size", disabled=True)
        edited_c2s = st.data_editor(
            c2s_df_show,
            width='stretch',
            num_rows="fixed",
            hide_index=True,
            column_config=col_cfg,
            key="tbl_c2s"
        )
        st.session_state.amb_c2s_sel_idx = set(edited_c2s.loc[edited_c2s["Show"]==True, "Index"].tolist())

    # --- AMB: S→H(이송) 표 (표시, 인덱스, 병원, 종별코드, 병원등급, 거리) ---
    with col_amb_s2h:
        st.markdown("**Incident Site → Hospital (Transport)**")

        # ✔ hospital_info_road + distance_Hos2Site_road 기준
        if not hinfo_df.empty:
            s2h_df = hinfo_df.rename(columns={
                "Hospital Name":"Hospital"
            })[["Index","Hospital","Grade Code"]].copy()
            s2h_df["Hospital Grade"] = s2h_df["Grade Code"].apply(code_to_grade)
            if dist_road_map:
                s2h_df["Distance(km)"] = s2h_df["Index"].map(dist_road_map).round(2)
            if dur_road_map:
                s2h_df["Duration(min)"] = s2h_df["Index"].map(dur_road_map).round(1)
        else:
            s2h_df = pd.DataFrame(columns=["Index","Hospital","Grade Code","Hospital Grade","Distance(km)","Duration(min)"])

        if "amb_s2h_sel_idx" not in st.session_state:
            st.session_state.amb_s2h_sel_idx = set(s2h_df["Index"].tolist())

        c, d = st.columns(2)
        if c.button("Select All (S→H)"):
            st.session_state.amb_s2h_sel_idx = set(s2h_df["Index"].tolist())
        if d.button("Deselect All (S→H)"):
            st.session_state.amb_s2h_sel_idx = set()

        s2h_df_show = s2h_df.copy()
        s2h_df_show["Show"] = s2h_df_show["Index"].apply(lambda i: i in st.session_state.amb_s2h_sel_idx)
        # ▶ 표시를 맨 앞으로
        s2h_show_cols = ["Show","Index","Hospital","Grade Code","Hospital Grade","Distance(km)"]
        if "Duration(min)" in s2h_df_show.columns:
            s2h_show_cols.append("Duration(min)")
        s2h_df_show = s2h_df_show[s2h_show_cols]

        s2h_col_cfg = {
            "Show":     st.column_config.CheckboxColumn("Show"),
            "Index":   st.column_config.NumberColumn("Index", disabled=True),
            "Hospital":     st.column_config.TextColumn("Hospital", disabled=True),
            "Grade Code": st.column_config.NumberColumn("Grade Code", disabled=True),
            "Hospital Grade": st.column_config.TextColumn("Hospital Grade", disabled=True),
            "Distance(km)": st.column_config.NumberColumn("Distance(km)", disabled=True, format="%.2f"),
        }
        if "Duration(min)" in s2h_df_show.columns:
            s2h_col_cfg["Duration(min)"] = st.column_config.NumberColumn("Duration(min)", disabled=True, format="%.1f")

        edited_s2h = st.data_editor(
            s2h_df_show,
            width='stretch',
            num_rows="fixed",
            hide_index=True,
            column_config=s2h_col_cfg,
            key="tbl_s2h"
        )
        st.session_state.amb_s2h_sel_idx = set(edited_s2h.loc[edited_s2h["Show"]==True, "Index"].tolist())

    # ─────────────────────────────────────────────────────────────────────
    # ② UAV 경로 (출동/이송 — 직선거리 표출)
    # ─────────────────────────────────────────────────────────────────────
    with _route_exp:
        st.markdown("### UAV Routes")
        col_uav_out, col_uav_back = st.columns(2)

    # 출동(병원→사고): 헬기장 병원 (uav_info.csv에서 읽기)
    with col_uav_out:
        st.markdown("**Helipad Hospital → Incident Site (Dispatch)**")

        uav_dispatch_latlons = []

        # uav_info.csv 읽기
        uav_info_path = Path(bp) / "scenarios" / exp / coord / "uav_info.csv"
        if os.path.exists(uav_info_path):
            try:
                uav_df = pd.read_csv(uav_info_path, encoding="utf-8-sig")
                uav_df.rename(columns={
                    "종별코드": "Grade Code", "요양기관명": "Hospital Name",
                    "수술실수": "ORs", "병상수": "Beds",
                }, inplace=True)

                # 새 형식 확인 (6컬럼)
                if "Hospital Name" in uav_df.columns:
                    for _, row in uav_df.iterrows():
                        name = str(row["Hospital Name"]).strip()
                        code = row.get("Grade Code", 1)

                        # 엑셀에서 좌표 조회
                        if name in xl_coord:
                            y, x = xl_coord[name]
                            uav_dispatch_latlons.append((y, x, name, code))
                        else:
                            print(f"⚠️ UAV 병원 '{name}' 좌표 없음")
                else:
                    print("⚠️ uav_info.csv 구 형식 (2컬럼) - 업데이트 필요")
                    # 폴백: tier3 사용
                    if not hinfo_df.empty and {"Grade Code","Hospital Name"}.issubset(hinfo_df.columns):
                        tmp = hinfo_df.copy()
                        tmp["Grade Code"] = pd.to_numeric(tmp["Grade Code"], errors="coerce")
                        for _, rr in tmp[tmp["Grade Code"]==1].iterrows():
                            name = str(rr.get("Hospital Name","Tier3")).strip()
                            if name in xl_coord:
                                y, x = xl_coord[name]
                                uav_dispatch_latlons.append((y, x, name, 1))
            except Exception as e:
                print(f"⚠️ uav_info.csv 로드 실패: {e}")
        else:
            print(f"⚠️ uav_info.csv 없음: {uav_info_path}")

        # 데이터가 없으면 tier3 폴백
        if not uav_dispatch_latlons and not hinfo_df.empty and {"Grade Code","Hospital Name"}.issubset(hinfo_df.columns):
            tmp = hinfo_df.copy()
            tmp["Grade Code"] = pd.to_numeric(tmp["Grade Code"], errors="coerce")
            for _, rr in tmp[tmp["Grade Code"]==1].iterrows():
                name = str(rr.get("Hospital Name","Tier3")).strip()
                if name in xl_coord:
                    y, x = xl_coord[name]
                    uav_dispatch_latlons.append((y, x, name, 1))

        uav_out_rows = []
        # UAV 속도를 YAML에서 읽기 (Rerun 탭에서 변경한 속도 반영)
        _, uav_velocity_from_yaml = get_speed_from_yaml(yaml_path)
        uav_velocity = uav_velocity_from_yaml if uav_velocity_from_yaml else 80  # 기본값 80 km/h

        for i, (y, x, nm, code) in enumerate(uav_dispatch_latlons):
            dkm = _haversine_km(y, x, lat, lon)  # 직선거리
            duration_min = (dkm / uav_velocity) * 60  # 시간(분) = 거리 / 속도 * 60
            uav_out_rows.append({
                "Index": i,
                "Hospital": nm,
                "Grade Code": code,
                "Hospital Grade": code_to_grade(code),
                "Distance(km)": round(dkm, 2),
                "Duration(min)": round(duration_min, 1)
            })
        uav_out_df = pd.DataFrame(uav_out_rows)

        if "uav_c2s_sel_idx" not in st.session_state:
            st.session_state.uav_c2s_sel_idx = set(uav_out_df["Index"].tolist())

        f1, f2 = st.columns(2)
        if f1.button("UAV Dispatch Select All"):
            st.session_state.uav_c2s_sel_idx = set(uav_out_df["Index"].tolist())
        if f2.button("UAV Dispatch Deselect All"):
            st.session_state.uav_c2s_sel_idx = set()

        uav_out_df_show = uav_out_df.copy()
        uav_out_df_show["Show"] = uav_out_df_show["Index"].apply(lambda i: i in st.session_state.uav_c2s_sel_idx)
        # ▶ 표시를 맨 앞으로, 거리와 시간은 마지막
        uav_out_df_show = uav_out_df_show[["Show","Index","Hospital","Grade Code","Hospital Grade","Distance(km)","Duration(min)"]]

        edited_uav_out = st.data_editor(
            uav_out_df_show,
            width='stretch',
            num_rows="fixed",
            hide_index=True,
            column_config={
                "Show":     st.column_config.CheckboxColumn("Show"),
                "Index":   st.column_config.NumberColumn("Index", disabled=True),
                "Hospital":     st.column_config.TextColumn("Hospital", disabled=True),
                "Grade Code": st.column_config.NumberColumn("Grade Code", disabled=True),
                "Hospital Grade": st.column_config.TextColumn("Hospital Grade", disabled=True),
                "Distance(km)": st.column_config.NumberColumn("Distance(km)", disabled=True, format="%.2f"),
                "Duration(min)": st.column_config.NumberColumn("Duration(min)", disabled=True, format="%.1f"),
            },
            key="tbl_uav_out"
        )
        # 출동과 이송 선택 동기화
        selected_indices = set(edited_uav_out.loc[edited_uav_out["Show"]==True, "Index"].tolist())
        st.session_state.uav_c2s_sel_idx = selected_indices
        st.session_state.uav_s2h_sel_idx = selected_indices

    # 이송(사고→병원): 출동과 동일한 헬기장 병원 (왕복 셔틀)
    with col_uav_back:
        st.markdown("**Incident Site → Helipad Hospital (Transport)**")

        # ✔ UAV는 왕복 셔틀: 출동과 동일한 헬기장 병원으로 이송
        # uav_out_df와 동일한 데이터 사용
        uav_back_df = uav_out_df.copy()

        # 세션 상태 공유 (출동과 이송이 동일한 선택 상태)
        if "uav_s2h_sel_idx" not in st.session_state:
            st.session_state.uav_s2h_sel_idx = st.session_state.uav_c2s_sel_idx.copy()

        g1, g2 = st.columns(2)
        if g1.button("UAV Transport Select All"):
            st.session_state.uav_s2h_sel_idx = set(uav_back_df["Index"].tolist())
            st.session_state.uav_c2s_sel_idx = set(uav_back_df["Index"].tolist())
        if g2.button("UAV Transport Deselect All"):
            st.session_state.uav_s2h_sel_idx = set()
            st.session_state.uav_c2s_sel_idx = set()

        uav_back_df_show = uav_back_df.copy()
        uav_back_df_show["Show"] = uav_back_df_show["Index"].apply(lambda i: i in st.session_state.uav_s2h_sel_idx)
        # ▶ 표시를 맨 앞으로, 거리와 시간은 마지막
        uav_back_df_show = uav_back_df_show[["Show","Index","Hospital","Grade Code","Hospital Grade","Distance(km)","Duration(min)"]]

        edited_uav_back = st.data_editor(
            uav_back_df_show,
            width='stretch',
            num_rows="fixed",
            hide_index=True,
            column_config={
                "Show":     st.column_config.CheckboxColumn("Show"),
                "Index":   st.column_config.NumberColumn("Index", disabled=True),
                "Hospital":     st.column_config.TextColumn("Hospital", disabled=True),
                "Grade Code": st.column_config.NumberColumn("Grade Code", disabled=True),
                "Hospital Grade": st.column_config.TextColumn("Hospital Grade", disabled=True),
                "Distance(km)": st.column_config.NumberColumn("Distance(km)", disabled=True, format="%.2f"),
                "Duration(min)": st.column_config.NumberColumn("Duration(min)", disabled=True, format="%.1f"),
            },
            key="tbl_uav_back"
        )
        # 출동과 이송 선택 동기화
        selected_indices = set(edited_uav_back.loc[edited_uav_back["Show"]==True, "Index"].tolist())
        st.session_state.uav_s2h_sel_idx = selected_indices
        st.session_state.uav_c2s_sel_idx = selected_indices

    # ─────────────────────────────────────────────────────────────────────
    # ③ 지도 생성 및 출력(최상단 map_holder에 표출)
    # ─────────────────────────────────────────────────────────────────────
    m = folium.Map(location=center, zoom_start=12, control_scale=True, tiles=tile_name)

    # 사고지점 마커
    site_popup = f"Incident Site<br>lat,lon={lat:.6f},{lon:.6f}"
    if site_addr: site_popup += f"<br>Address: {site_addr}"
    folium.Marker(
        [lat,lon],
        icon=folium.Icon(color="purple", icon="map-pin", prefix="fa"),
        tooltip="Incident Site", popup=site_popup
    ).add_to(m)

    # ─ AMB C→S 라인/마커 ─
    # 이름 → JSON route 매핑 (센터명으로 연결)
    c2s_map = {}
    for obj in c2s_all:  # 전체 탐색
        meta = obj.get("meta", {})
        nm = str(meta.get("name","")).strip()
        if nm:
            c2s_map[nm] = obj

    # ✔ amb_info_road 순서/선택 기준으로 그림
    for _, row in c2s_df.iterrows():
        i = int(row["Index"])
        if i not in st.session_state.amb_c2s_sel_idx:
            continue
        cname = str(row["Fire Station"]).strip()
        obj   = c2s_map.get(cname)
        if obj is None:
            continue

        meta = obj.get("meta", {})
        c    = meta.get("center") or meta.get("start")  # [lon, lat]
        clatlon = (c[1], c[0]) if (isinstance(c, list) and len(c)==2) else None

        addr = tel = ""
        if not center_df.empty and "기관명" in center_df.columns and clatlon:
            # 좌표 기반 매칭: 같은 이름의 센터가 여러 개일 경우 가장 가까운 것 선택
            msk = (center_df["기관명"].astype(str) == cname)
            if msk.any():
                candidates = center_df[msk].copy()
                # 거리 계산 (Haversine이 아닌 간단한 유클리드 거리)
                if "y좌표" in candidates.columns and "x좌표" in candidates.columns:
                    candidates["_dist"] = ((candidates["y좌표"] - clatlon[0])**2 +
                                          (candidates["x좌표"] - clatlon[1])**2)**0.5
                    rowc = candidates.sort_values("_dist").iloc[0]
                else:
                    rowc = candidates.iloc[0]
                addr = str(rowc.get("주소","")); tel = str(rowc.get("전화번호",""))

        # 거리는 ✔ amb_info_road의 init_distance 사용
        # (기존) extra 구성부를 아래처럼 교체
        dist_csv = row["Distance(km)"] if "Distance(km)" in row and pd.notna(row["Distance(km)"]) else None
        dist_json, dur_min, _ = _extract_summary_meta(obj)  # JSON 경로 요약

        extra = []
        if addr: extra.append(f"Address: {addr}")       # ① 주소
        if tel:  extra.append(f"Phone: {tel}")        # ② 전화
        qty = row.get("Fleet Size", None)
        if qty is not None and pd.notna(qty):
            extra.append(f"Fleet: {int(qty)}")
        # ③ 거리 (우선 CSV, 없으면 JSON)
        dk = float(dist_csv) if dist_csv is not None else (float(dist_json) if dist_json is not None else None)
        if dk is not None:
            extra.append(f"🚑 Center→Site: {dk:.2f} km")
        # ④ 소요시간
        if dur_min is not None and dur_min > 0:
            extra.append(f"Duration: {dur_min:.1f} min")

        if clatlon:
            add_center_marker(m, cname, clatlon, extra)


        # 실제 라인은 JSON 경로
        draw_route_from_json(m, obj, highlight=False)

    # ─ AMB S→H 라인/마커 ─
    # 이름/Index → JSON route 매핑 (병원명으로 연결)
    h2s_map = {}
    h2s_idx_map = {}
    for obj in h2s_all:  # 전체 탐색
        meta = obj.get("meta", {})
        nm = str(meta.get("name","")).strip()
        if nm:
            h2s_map[nm] = obj
        try:
            idx = int(meta.get("source_index"))
            h2s_idx_map[idx] = obj
        except Exception:
            pass

    # ✔ hospital_info_road 순서/선택 + distance_Hos2Site_road 거리 표출
    for _, row in s2h_df.iterrows():
        i = int(row["Index"])
        if i not in st.session_state.amb_s2h_sel_idx:
            continue
        name = str(row["Hospital"]).strip()
        euc_idx = int(row.get("euc_idx", i))
        obj = h2s_idx_map.get(euc_idx) or h2s_map.get(name)
        if obj is None:
            continue

        # 좌표/메타는 엑셀에서 보강
        latlon = None; phone = addr = None
        code   = row.get("Grade Code", None)
        # 1) route meta 좌표(이름 중복시 Index 우선)
        meta = obj.get("meta", {}) if isinstance(obj, dict) else {}
        hosp_meta = meta.get("hospital")
        if isinstance(hosp_meta, (list, tuple)) and len(hosp_meta) == 2:
            latlon = (float(hosp_meta[1]), float(hosp_meta[0]))

        # 2) 엑셀: 주소/전화 보강, 좌표는 없을 때만 보정
        if hosp_xl is not None and "요양기관명" in hosp_xl.columns:
            rx = hosp_xl[hosp_xl["요양기관명"] == name]
            if not rx.empty:
                phone = rx.iloc[0].get("전화번호", None)
                addr  = rx.iloc[0].get("주소", None)
                if latlon is None:
                    y = rx.iloc[0].get("y좌표", rx.iloc[0].get("y", None))
                    x = rx.iloc[0].get("x좌표", rx.iloc[0].get("x", None))
                    if pd.notna(y) and pd.notna(x):
                        latlon = (float(y), float(x))

            # (기존) 좌표/메타 얻는 부분은 그대로 두고,
            #       추가로 hinfo_df에서 병상수/수술실수, JSON에서 소요시간을 읽어 붙임

            # 거리: 표의 (거리(km)) 우선, 없으면 JSON 요약 거리
            dkm_csv = row.get("Distance(km)", None)
            dkm_json, dur_min, _ = _extract_summary_meta(obj)

            dk = float(dkm_csv) if pd.notna(dkm_csv) else (float(dkm_json) if dkm_json is not None else None)

            # 병상/수술실: hospital_info_road.csv 원본에서 인덱스 i로 조회
            beds_val = None
            ops_val  = None
            orig = hinfo_df[hinfo_df["Index"] == i]
            if not orig.empty:
                beds_val = orig.iloc[0].get("Beds", None)
                ops_val  = orig.iloc[0].get("ORs", None)

            grade_label = code_to_grade(code)
            extras = [f"Grade: {grade_label}"]                 # ⑤-1 병원등급
            if dk is not None:
                extras.append(f"🏥 Site→Hospital: {dk:.2f} km")   # ⑤-2 거리 (이모지 유지)
            if dur_min is not None and dur_min > 0:
                extras.append(f"Duration: {dur_min:.1f} min")      # ⑤-3 소요시간

            if latlon:
                add_hospital_marker(
                    m, name, code, latlon, ops_val, beds_val, extras
                )

        # 라인은 JSON 경로
        draw_route_from_json(m, obj, highlight=False)

    # ─ UAV Dispatch(Hosp→Site) ─
    for i, (y, x, name, code) in enumerate(uav_dispatch_latlons):
        if i not in st.session_state.uav_c2s_sel_idx:
            continue
        dkm = _haversine_km(y, x, lat, lon)

        # 헬기장 병원 마커 추가
        # uav_out_df에서 병상수/수술실수 가져오기
        beds_val = None
        ops_val = None
        # Reuse already-loaded uav_df instead of re-reading CSV
        if 'uav_df' in dir() and uav_df is not None and i < len(uav_df):
            if "Beds" in uav_df.columns:
                beds_val = uav_df.iloc[i].get("Beds", None)
            if "ORs" in uav_df.columns:
                ops_val = uav_df.iloc[i].get("ORs", None)

        grade_label = code_to_grade(code)
        extras = [
            f"Grade: {grade_label}",
            f"🛩️ Helipad→Site: {dkm:.2f} km"
        ]

        add_hospital_marker(m, name, code, (y, x), ops_val, beds_val, extras)

        # 출동 경로 그리기
        draw_uav_dash(
            m, (y,x), (lat,lon),
            UAV_OUT_COLOR,
            f"🛩️ Dispatch {name}→Site · {dkm:.2f} km"
        )

    # ─ UAV 이송(사고→헬기장 병원) ─
    # ✔ UAV는 왕복 셔틀: 헬기장 병원에서 출발해서 다시 헬기장 병원으로 돌아감
    # uav_dispatch_latlons와 동일한 병원 리스트 사용
    for i, (y, x, name, code) in enumerate(uav_dispatch_latlons):
        if i not in st.session_state.uav_s2h_sel_idx:
            continue
        dkm = _haversine_km(lat, lon, y, x)
        draw_uav_dash(
            m, (lat,lon), (y,x),
            UAV_BACK_COLOR,
            f"🛩️ Transport Site→{name} · {dkm:.2f} km"
        )

    # ─ 범례/속도 ─
    amb_speed, uav_speed = get_speed_from_yaml(find_yaml_in_coord(bp, exp, coord))
    legend_html = [
        '<div style="position: fixed; bottom: 18px; left: 12px; z-index: 9999; background: rgba(255,255,255,0.96); color: #222; padding: 10px 12px; border-radius: 10px; font-size: 12px; line-height: 1.35; box-shadow: 0 2px 8px rgba(0,0,0,.25); border: 1px solid #ccc;">',
        '<b>Legend (Kakao Traffic)</b><br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:5px solid {CONG_COLORS[0]};margin:2px 6px 2px 0;"></span>Unknown(0)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:5px solid {CONG_COLORS[1]};margin:2px 6px 2px 0;"></span>Congested(1)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:5px solid {CONG_COLORS[2]};margin:2px 6px 2px 0;"></span>Slow(2)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:5px solid {CONG_COLORS[3]};margin:2px 6px 2px 0;"></span>Moderate(3)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:5px solid {CONG_COLORS[4]};margin:2px 6px 2px 0;"></span>Clear(4)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:5px solid {CONG_COLORS[6]};margin:2px 6px 2px 0;"></span>Accident(6)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:3px dashed {UAV_OUT_COLOR};margin:6px 6px 2px 0;"></span>UAV Dispatch(Hosp→Site)<br>',
        f'<span style="display:inline-block;width:26px;height:0;border-top:3px dashed {UAV_BACK_COLOR};margin:2px 6px 0 0;"></span>UAV Transport(Site→Hosp)<br>',
    ]
    if amb_speed or uav_speed:
        sp = []
        if amb_speed: sp.append(f"🚑 AMB≈{amb_speed} km/h")
        if uav_speed: sp.append(f"🛩️ UAV≈{uav_speed} km/h")
        legend_html.append(" · ".join(sp) + '<br>')
    legend_html.append('<span style="opacity:.7; color:#555;">* Click marker popup for route details</span>')
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
        # 성능 최적화: key 설정으로 불필요한 재렌더링 방지
        st_folium(m, width=None, height=690, key="main_map", returned_objects=[])


# ------------------------------
# Analytics 탭 (정렬 테이블 + ANOVA 스위트)
# ------------------------------

@st.cache_data
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
    """
    STAT 파일을 RAW 기준으로 재정렬
    ✅ 누락된 시나리오도 처리 (UAV=0 케이스 대응)
    """
    
    # 1. STAT 파일 읽기 - 룰 이름을 키로 사용
    stat_dict = {}  # {rule_name: [(mean, std, ci) for each metric]}
    
    with open(stat_path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    
    st.caption(f"📊 STAT file: {len(lines)} lines total")
    
    # 예상 라인 수 확인
    expected = 320  # 64 × 5
    if len(lines) != expected:
        st.warning(f"⚠️ STAT line count mismatch: {len(lines)} (expected: {expected})")
        st.caption(f"→ {expected - len(lines)} scenarios may be missing")
    
    # 2. 각 줄을 파싱하여 딕셔너리에 저장
    for line in lines:
        parts = line.split()
        
        if len(parts) < 3:
            continue
        
        try:
            mean = float(parts[-3])
            std = float(parts[-2])
            ci = float(parts[-1])
            
            # 룰 이름 추출
            rule_name = " ".join(parts[:-3]).strip()
            
            # 룰별로 메트릭 저장 (순서대로 5개: Reward, Time, PDR, Reward_woG, PDR_woG)
            if rule_name not in stat_dict:
                stat_dict[rule_name] = []
            
            stat_dict[rule_name].append((mean, std, ci))
            
        except ValueError:
            continue
    
    # 3. RAW 파일에서 정확한 룰 순서 가져오기
    raw_path = stat_path.replace("_stat.txt", ".txt")
    
    if not os.path.exists(raw_path):
        st.error("❌ RAW file not found!")
        return pd.DataFrame(), pd.DataFrame()
    
    dfraw = parse_raw_results(raw_path)
    reward_data = dfraw[dfraw["metric"] == "Reward"]
    
    # RAW의 룰 순서 (실제 실행된 순서)
    rule_order = reward_data[reward_data["run"] == 1]["rule"].tolist()
    
    st.info(f"✅ RAW file: {len(rule_order)} scenarios confirmed")
    
    # 4. RAW 순서대로 STAT 데이터 매칭
    result_rows = []
    missing_count = 0
    
    for idx, rule in enumerate(rule_order):
        row = {
            "ScenarioIdx": idx,
        }
        
        # Phase, RedPolicy 등 파싱
        match = re.match(
            r'(START|ReSTART),\s*(RedOnly|YellowNearest),\s*Red\s+(\w+),\s*Yellow\s+(\w+)', 
            rule
        )
        if match:
            row["Phase"] = match.group(1)
            row["RedPolicy"] = match.group(2)
            row["RedAction"] = match.group(3)
            row["YellowAction"] = match.group(4)
        
        # STAT에서 해당 룰 찾기
        if rule in stat_dict:
            stats = stat_dict[rule]
            
            # ✅ 기존 컬럼 이름 형식 유지: M1_mean, M2_mean, ...
            for m_idx in range(5):
                if m_idx < len(stats):
                    mean, std, ci = stats[m_idx]
                    row[f"M{m_idx+1}_mean"] = mean
                    row[f"M{m_idx+1}_std"] = std
                    row[f"M{m_idx+1}_ci"] = ci
                else:
                    row[f"M{m_idx+1}_mean"] = np.nan
                    row[f"M{m_idx+1}_std"] = np.nan
                    row[f"M{m_idx+1}_ci"] = np.nan
        else:
            # STAT에 없는 룰 → RAW에서 직접 계산
            st.warning(f"⚠️ Not in STAT: {rule}")
            missing_count += 1
            
            # RAW 데이터에서 직접 통계 계산
            metric_names = ["Reward", "Time", "PDR", "Reward_woG", "PDR_woG"]
            
            for m_idx, metric in enumerate(metric_names):
                metric_data = dfraw[(dfraw["metric"] == metric) & (dfraw["rule"] == rule)]
                
                if not metric_data.empty:
                    values = metric_data["value"].values
                    mean = np.mean(values)
                    std = np.std(values, ddof=1) if len(values) > 1 else 0
                    
                    # 95% CI 계산
                    if len(values) > 1:
                        from scipy.stats import t
                        se = std / np.sqrt(len(values))
                        ci = t.interval(0.95, len(values)-1, loc=mean, scale=se)
                        ci_half = (ci[1] - ci[0]) / 2
                    else:
                        ci_half = 0
                    
                    row[f"M{m_idx+1}_mean"] = mean
                    row[f"M{m_idx+1}_std"] = std
                    row[f"M{m_idx+1}_ci"] = ci_half
                else:
                    row[f"M{m_idx+1}_mean"] = np.nan
                    row[f"M{m_idx+1}_std"] = np.nan
                    row[f"M{m_idx+1}_ci"] = np.nan
        
        result_rows.append(row)
    
    if missing_count > 0:
        st.warning(f"⚠️ {missing_count} scenarios computed directly from RAW")
    
    wide = pd.DataFrame(result_rows)
    

    
    # ✅ long 형식도 생성 (기존 코드 호환성)
    long_rows = []
    metric_names = ["Reward", "Time", "PDR", "Reward_woG", "PDR_woG"]
    
    for _, row in wide.iterrows():
        for m_idx, metric in enumerate(metric_names):
            long_rows.append({
                "ScenarioIdx": row["ScenarioIdx"],
                "Metric": f"M{m_idx+1}",
                "mean": row.get(f"M{m_idx+1}_mean", np.nan),
                "std": row.get(f"M{m_idx+1}_std", np.nan),
                "ci": row.get(f"M{m_idx+1}_ci", np.nan),
                "Phase": row.get("Phase", ""),
                "RedPolicy": row.get("RedPolicy", ""),
                "RedAction": row.get("RedAction", ""),
                "YellowAction": row.get("YellowAction", ""),
            })
    
    long_df = pd.DataFrame(long_rows)
    
    return wide, long_df

# Raw 결과 파싱 (Rule×Sample 스택)
RAW_RE = re.compile(r'^(START|ReSTART),\s*(RedOnly|YellowNearest),\s*Red\s+([A-Za-z_]+),\s*Yellow\s+([A-Za-z_]+)')



# ------------------------------
# Analytics 탭 (ANOVA 분석)
# ------------------------------

# ===== Analysis 탭 =====
with tabs[2]:
    st.subheader("RAW Result Analysis (results_{coord}.txt)")

    bp   = st.session_state.base_path
    exp  = st.session_state.selected_exp
    coord= st.session_state.selected_coord

    # 시나리오 변경 시 Analytics 로드 상태 리셋
    current_analytics_key = f"{exp}_{coord}"
    if st.session_state.get("last_analytics_key") != current_analytics_key:
        st.session_state.analytics_loaded = False
        st.session_state.last_analytics_key = current_analytics_key

    if not (bp and exp and coord):
        st.info("Select a scenario from the sidebar first.")
    else:
        spath = results_stat_path(bp, exp, coord)   # 기존 함수
        rpath = results_raw_path(bp, exp, coord)    # 기존 함수

        # 성능 최적화: 버튼 클릭 시에만 Analytics 데이터 로드
        st.info("💡 Large simulation results may take time to load. Click the button below to start analysis.")

        if st.button("Load Analysis Data", key="load_analytics_btn", help="Parse and analyze RAW results"):
            st.session_state.analytics_loaded = True

        if not st.session_state.get("analytics_loaded", False):
            st.caption("💡 Click 'Load Analysis Data' above to view analysis. (Disabled by default for faster tab loading)")
        else:
            analytics_tabs = st.tabs(["RAW Data", "STAT Summary", "ANOVA Suite"])

            # ── RAW Data sub-tab ──
            with analytics_tabs[0]:
                raw_tables = {}
                if rpath and os.path.exists(rpath):
                    with st.spinner("Parsing RAW results... (large files may take a moment)"):
                        raw_tables = parse_raw_all_metrics(rpath)  # {metric: df}

                    if raw_tables:
                        # 파일에 실제 들어있는 지표만 옵션으로 노출
                        metric_options = [m for m in RAW_METRIC_NAMES if m in raw_tables.keys()]
                        picked = st.multiselect(
                            "Select metrics to display",
                            options=metric_options,
                            default=[metric_options[0]] if metric_options else [],
                            help="Only selected metrics will be shown below."
                        )
                        for m in picked:
                            st.markdown(f"#### RAW Table -- **{m}** (per run)")
                            st.dataframe(raw_tables[m], width='stretch')
                    else:
                        st.warning("No readable blocks found in RAW (results_*.txt).")
                else:
                    st.warning("RAW (results_*.txt) file not found.")

            # ── STAT Summary sub-tab ──
            with analytics_tabs[1]:
                st.subheader("STAT Summary Analysis (_stat.txt)")
                st.info(
                "results/exp_YYYYMMDD_HHMMSS/(lat,lon)/results_{coord}.txt (Raw), results_{coord}_stat.txt (Stat)\n\n"
                "- **Reward**: Survival probability sum\n- **Time**: Elapsed time\n- **PDR**\n- **w.o.G**: Excluding Green"
            )

            wide, long_df = (pd.DataFrame(), pd.DataFrame())
            if spath and os.path.exists(spath):
                wide, long_df = parse_stat_file(spath)

            if not wide.empty:
                display = wide.rename(columns={
                    "M1_mean":"Reward Mean","M1_std":"Reward Std","M1_ci":"Reward 95%CI",
                    "M2_mean":"Time Mean","M2_std":"Time Std","M2_ci":"Time 95%CI",
                    "M3_mean":"PDR Mean","M3_std":"PDR Std","M3_ci":"PDR 95%CI",
                    "M4_mean":"Reward w.o.G Mean","M4_std":"Reward w.o.G Std","M4_ci":"Reward w.o.G 95%CI",
                    "M5_mean":"PDR w.o.G Mean","M5_std":"PDR w.o.G Std","M5_ci":"PDR w.o.G 95%CI",
                })
                st.dataframe(display, width='stretch')

                st.markdown("#### Scenario Ranking (Sort by)")
                crit = st.selectbox("Sort by", ["Reward (desc)","PDR (asc)","Time (asc)"], index=0)
                if crit == "Reward (desc)":
                    df_sorted = wide.sort_values("M1_mean", ascending=False)
                    cols = ["ScenarioIdx","Phase","RedPolicy","RedAction","YellowAction","M1_mean","M1_ci"]
                elif crit == "PDR (asc)":
                    df_sorted = wide.sort_values("M3_mean", ascending=True)
                    cols = ["ScenarioIdx","Phase","RedPolicy","RedAction","YellowAction","M3_mean","M3_ci"]
                else:
                    df_sorted = wide.sort_values("M2_mean", ascending=True)
                    cols = ["ScenarioIdx","Phase","RedPolicy","RedAction","YellowAction","M2_mean","M2_ci"]
                st.dataframe(df_sorted[cols], width='stretch')
            else:
                st.info("STAT summary file not found or empty.")

            # ── ANOVA Suite sub-tab ── (opened below after helper definitions)

            import itertools

            def make_total_row(anova_tbl: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
                ss_total = float(((y - y.mean())**2).sum())
                N = len(y)
                total = pd.DataFrame(
                    {"sum_sq":[ss_total], "df":[N-1], "mean_sq":[np.nan], "F":[np.nan], "PR(>F)":[np.nan], "eta_sq":[np.nan], "omega_sq":[np.nan]},
                    index=["Total"]
                )
                out = anova_tbl.copy()
                # eta-squared
                out["eta_sq"] = out["sum_sq"] / ss_total
                # omega-squared (bias-corrected)
                if "Residual" in out.index:
                    ms_res = float(out.loc["Residual", "sum_sq"] / out.loc["Residual", "df"]) if out.loc["Residual", "df"] > 0 else 0.0
                    out["omega_sq"] = (out["sum_sq"] - out["df"] * ms_res) / (ss_total + ms_res)
                    out.loc[out["omega_sq"] < 0, "omega_sq"] = 0.0
                    out.loc["Residual", "omega_sq"] = np.nan
                else:
                    out["omega_sq"] = np.nan
                if "df" in out.columns and "sum_sq" in out.columns:
                    out["mean_sq"] = out["sum_sq"] / out["df"]
                cols = ["sum_sq","df","mean_sq","F","PR(>F)","eta_sq","omega_sq"]
                out = out.reindex(columns=cols)
                return pd.concat([out, total], axis=0)


            def block_adjust(df, yvar, block_col):
                """블록-잔차화: y* = y - 블록평균."""
                df = df.copy()
                df["y_adj"] = df[yvar] - df.groupby(block_col)[yvar].transform("mean")
                return df
            def _means_series(df: pd.DataFrame, group_col: str, value_col: str) -> pd.Series:
                """
                그룹 평균을 '항상 Series'로 반환 (중복 컬럼명/버전 이슈 방어).
                - df[value_col]이 DataFrame로 떨어지면 첫 컬럼만 사용
                - 값은 숫자로 강제 변환
                """
                col = df.loc[:, value_col]  # 중복 이름이면 DataFrame
                if isinstance(col, pd.DataFrame):
                    col = col.iloc[:, 0]     # 첫 컬럼만 채택
                col = pd.to_numeric(col.squeeze(), errors="coerce")
                g = pd.DataFrame({group_col: df[group_col].values, "__y__": col.values})
                tmp = g.groupby(group_col, as_index=False)["__y__"].mean()
                s = tmp.set_index(group_col)["__y__"]
                return s
        
            def _scalar(x, default=np.nan) -> float:
                """어떤 타입이 와도 확실히 float 스칼라로 변환."""
                try:
                    a = np.asarray(x)
                    return float(a.ravel()[0])
                except Exception:
                    return float(default)


            def welch_holm_posthoc(df, grp, yvar, alpha=0.05):
                """Pairwise Welch t-tests with Holm correction (used when pingouin is unavailable)."""
                from scipy import stats as sps
                pairs, pvals = [], []
                for g1, g2 in itertools.combinations(sorted(df[grp].unique()), 2):
                    x = df.loc[df[grp]==g1, yvar].values
                    y = df.loc[df[grp]==g2, yvar].values
                    _, p = sps.ttest_ind(x, y, equal_var=False)
                    pairs.append((g1,g2)); pvals.append(p)
                ph = pd.DataFrame(pairs, columns=["group1","group2"])
                from statsmodels.stats.multitest import multipletests
                ph["p-adj"] = multipletests(pvals, method="holm")[1]
                ph["reject"] = ph["p-adj"] < alpha
                return ph

            def tukey_table(endog, groups, alpha=0.05):
                from statsmodels.stats.multicomp import pairwise_tukeyhsd
                th = pairwise_tukeyhsd(endog=endog, groups=groups, alpha=alpha)
                tb = pd.DataFrame(th.summary().data[1:], columns=th.summary().data[0])
                # 표준화 컬럼명
                tb = tb.rename(columns={"group1":"group1","group2":"group2","reject":"reject","p-adj":"p-adj"})
                if "p-adj" not in tb.columns:
                    # statsmodels 버전에 따라 p-adj가 없을 수 있음 → 계산 불가 시 NaN
                    tb["p-adj"] = np.nan
                return tb

            def conover_friedman(df_block_rule: pd.DataFrame, alpha: float = 0.05):
                """
                Friedman 유의 후 사후검정:
                1순위: Conover + Holm (scikit-posthocs)
                실패 시: Nemenyi (fallback)
                항상 (posthoc_df, err_msg) 튜플을 반환.
                """
                import numpy as np
                import pandas as pd
                try:
                    import scikit_posthocs as sp
                except Exception as e:
                    return pd.DataFrame(), f"scikit-posthocs import failed: {e}"

                # 공통: wide → long 변환 함수
                def _wide_to_long(ph_wide: pd.DataFrame) -> pd.DataFrame:
                    tmp = ph_wide.copy()
                    # 인덱스 이름 보정
                    if tmp.index.name is None:
                        tmp.index.name = "group1"
                    long = tmp.reset_index().melt(id_vars=tmp.index.name, var_name="group2", value_name="p-adj")
                    long = long[long["group1"] < long["group2"]].reset_index(drop=True)
                    long["reject"] = long["p-adj"] < alpha
                    return long

                # 1) Conover + Holm
                try:
                    ph = sp.posthoc_conover_friedman(df_block_rule, p_adjust='holm')
                    return _wide_to_long(ph), None
                except Exception as e1:
                    # 2) Nemenyi fallback
                    try:
                        ph2 = sp.posthoc_nemenyi_friedman(df_block_rule)
                        msg = f"Conover failed, using Nemenyi instead: {e1}"
                        return _wide_to_long(ph2), msg
                    except Exception as e2:
                        return pd.DataFrame(), f"Both Conover/Nemenyi failed: {e1} / {e2}"

            def cld_from_pairs(means: pd.Series, pair_tbl: pd.DataFrame, alpha=0.05):
                """
                Compact Letter Display based on the absorption algorithm
                (Piepho 2004, "An algorithm for a letter-based representation
                of all pairwise comparisons").

                Each group may receive multiple letters (e.g. "ab"). Two groups
                sharing at least one letter are NOT significantly different.
                Groups sharing NO letters ARE significantly different.

                - means: index=group name, values=mean (pre-sorted by caller)
                - pair_tbl: must contain ['group1','group2'] and ['reject'] or ['p-adj']
                Returns DataFrame with columns [rule, mean, CLD].
                """
                # 빈 테이블이면 전부 A
                if pair_tbl is None or pair_tbl.empty or len(means) <= 1:
                    return pd.DataFrame({"rule": means.index, "mean": means.values, "CLD": ["a"]*len(means)})

                ph = pair_tbl.copy()
                if "reject" in ph.columns:
                    ph["sig"] = ph["reject"].astype(bool)
                else:
                    ph["sig"] = ph["p-adj"] < alpha

                # 유의 쌍 집합 (정렬된 튜플)
                _key = lambda a, b: tuple(sorted((a, b)))
                sig_pairs = set()
                for _, r in ph.iterrows():
                    if bool(r["sig"]):
                        sig_pairs.add(_key(r["group1"], r["group2"]))

                ordered = list(means.index)
                n = len(ordered)

                # --- Absorption algorithm ---
                # Start: single letter 'a' assigned to all groups
                # Each letter defines a "family" of groups that are mutually non-significant.
                # If a family contains a significant pair, split it by removing one member
                # and assigning a new letter.

                # Initial: one family containing all groups
                families = [set(ordered)]  # list of sets

                changed = True
                max_iter = n * 26  # safety limit
                iteration = 0
                while changed and iteration < max_iter:
                    changed = False
                    iteration += 1
                    new_families = []
                    for fam in families:
                        # Check if this family contains any significant pair
                        has_sig = False
                        for a_grp in fam:
                            for b_grp in fam:
                                if a_grp < b_grp and _key(a_grp, b_grp) in sig_pairs:
                                    has_sig = True
                                    break
                            if has_sig:
                                break

                        if not has_sig:
                            new_families.append(fam)
                        else:
                            # Split: find the member whose removal resolves the most conflicts
                            best_remove = None
                            best_conflicts = -1
                            for candidate in fam:
                                conflicts = sum(
                                    1 for other in fam
                                    if other != candidate and _key(candidate, other) in sig_pairs
                                )
                                if conflicts > best_conflicts:
                                    best_conflicts = conflicts
                                    best_remove = candidate

                            # Keep family without the removed member
                            remaining = fam - {best_remove}
                            if remaining:
                                new_families.append(remaining)
                            # New family: the removed member + all non-significant partners from original
                            new_fam = {best_remove}
                            for other in fam:
                                if other != best_remove and _key(best_remove, other) not in sig_pairs:
                                    new_fam.add(other)
                            new_families.append(new_fam)
                            changed = True

                    # Deduplicate families (same set of members)
                    unique = []
                    seen = set()
                    for fam in new_families:
                        key_frozen = frozenset(fam)
                        if key_frozen not in seen:
                            seen.add(key_frozen)
                            unique.append(fam)
                    families = unique

                # Absorb: remove families that are subsets of other families
                families.sort(key=len, reverse=True)
                absorbed = []
                for i, fam in enumerate(families):
                    is_subset = False
                    for j, other in enumerate(absorbed):
                        if fam.issubset(other):
                            is_subset = True
                            break
                    if not is_subset:
                        absorbed.append(fam)
                families = absorbed

                # Assign letters (a, b, c, ...) to families, sorted by best mean
                def family_rank(fam):
                    # rank by the best (first in ordered list) member
                    return min(ordered.index(g) for g in fam)
                families.sort(key=family_rank)

                letters_list = [chr(ord('a') + i) if i < 26 else chr(ord('a') + i - 26).upper()
                                for i in range(len(families))]

                group_letters = {g: [] for g in ordered}
                for letter, fam in zip(letters_list, families):
                    for g in fam:
                        group_letters[g].append(letter)

                return pd.DataFrame({
                    "rule": ordered,
                    "mean": [means[g] for g in ordered],
                    "CLD":  ["".join(group_letters[g]) for g in ordered],
                })
            def _series_1d(obj) -> pd.Series:
                """DataFrame/Series/ndarray/리스트 등 무엇이 와도 1D Series(float)로 강제."""
                if isinstance(obj, pd.DataFrame):
                    s = obj.iloc[:, 0]
                elif isinstance(obj, pd.Series):
                    s = obj
                else:
                    s = pd.Series(obj)
                return pd.to_numeric(s.astype(float), errors="coerce")

            def _make_dd_work(df: pd.DataFrame, yvar: str) -> pd.DataFrame:
                """
                사후검정용 워크 테이블을 항상 'rule' + '__y__' 2컬럼으로 생성.
                - df[yvar]가 DataFrame이어도 1열만 취함(1D 강제)
                - '__y__'는 pingouin/Tukey 등에서 dv/종속변수명으로 사용
                """
                y_s = _series_1d(df.loc[:, yvar])
                return pd.DataFrame({"rule": df["rule"].values, "__y__": y_s.values})


            with analytics_tabs[2]:
              st.markdown("#### ANOVA (One-way / RCBD / Reduced Factorial)")
              if not rpath:
                st.caption(f"Raw file (results_{coord}.txt) not found; skipping ANOVA.")
              else:
                dfraw = parse_raw_results(rpath)  # 반드시 long 형식
                if dfraw.empty:
                    st.caption("RAW parsing result is empty. Check file format.")
                else:
                    metric = st.selectbox("Metric", ["Reward","Time","PDR","Reward_woG","PDR_woG"], index=0)
                    d = dfraw[dfraw["metric"] == metric].copy()
                    if d.empty:
                        st.warning("No data found for the selected metric.")
                    else:
                        # 변환
                        # (요청 반영) Time은 원척도, PDR은 logit 선택 가능, Reward는 원척도
                        if metric == "Time":
                            trans_opts, trans_idx = ["None"], 0
                        elif metric.startswith("PDR"):
                            trans_opts, trans_idx = ["None","logit(PDR)"], 1   # 기본 logit
                        else:  # Reward, Reward_woG
                            trans_opts, trans_idx = ["None"], 0

                        trans = st.selectbox("Transform", trans_opts, index=trans_idx)
                        yvar = "value"; eps = 1e-6

                        if trans == "logit(PDR)":
                            d[yvar] = np.log((d[yvar]+eps)/(1-d[yvar]+eps)); st.caption("Logit transform applied to PDR.")
                        # (Time/Reward는 변환 없음)

                        if "rule" not in d.columns:
                            d["rule"] = d[["Phase","RedPolicy","RedAction","YellowAction"]].agg(", ".join, axis=1)

                        mode = st.radio("Analysis Type", ["One-way (rule only)","One-way + Block(run) (RCBD recommended)","Reduced Factorial (main + 2-way)"],
                                        index=1, horizontal=True)
                        if "Block" in mode or "Factorial" in mode:
                            st.caption("RCBD assumes Common Random Numbers (CRN): all 64 rules within each run share the same random seed, so `run` is a valid block variable.")

                        if not HAS_SM:
                            st.warning("statsmodels not installed. Cannot run ANOVA. `pip install statsmodels` and retry.")
                        else:
                            import statsmodels.api as sm
                            import statsmodels.formula.api as smf
                            from scipy import stats as sps

                            # 모형 적합
                            if mode == "One-way (rule only)":
                                formula = f"{yvar} ~ C(rule)"
                                st.caption("Model: value ~ C(rule)")
                            elif mode == "One-way + Block(run) (RCBD recommended)":
                                formula = f"{yvar} ~ C(rule) + C(run)"
                                st.caption("Model: value ~ C(rule) + C(run)  (run=block)")
                            else:
                                # Reduced factorial: main effects + 2-way interactions + block(run)
                                formula = (f"{yvar} ~ C(run) + C(Phase) + C(RedPolicy) + C(RedAction) + C(YellowAction)"
                                           " + C(Phase):C(RedPolicy) + C(Phase):C(RedAction) + C(Phase):C(YellowAction)"
                                           " + C(RedPolicy):C(RedAction) + C(RedPolicy):C(YellowAction)"
                                           " + C(RedAction):C(YellowAction)")
                                st.caption("Model: C(run) + main effects + all 2-way interactions (3/4-way excluded for power)")

                            model = smf.ols(formula, data=d).fit()
                            anova_tbl = sm.stats.anova_lm(model, typ=2)

                            # Total 포함 + η²
                            out = make_total_row(anova_tbl, d[yvar])
                            st.dataframe(out, width='stretch')

                            # Significant effects summary
                            alpha = st.slider("Significance Level (alpha)", 0.001, 0.1, 0.05, 0.001)
                            sig = out[(out.index!="Total") & (out["PR(>F)"] < alpha)].sort_values("PR(>F)")
                            if not sig.empty:
                                st.markdown("##### Interpretation Summary")
                                lines = []
                                for idx, r in sig.iterrows():
                                    omega = f", ω²={r['omega_sq']:.3f}" if pd.notna(r.get('omega_sq')) else ""
                                    lines.append(f"- **{idx}**: p={r['PR(>F)']:.3g}, η²={r['eta_sq']:.3f}{omega}")
                                st.markdown("\n".join(lines))
                            else:
                                st.caption("No significant effects found.")
                            st.caption(f"Model fit: R²={model.rsquared:.3f}, Adj.R²={model.rsquared_adj:.3f}")

                            # RCBD assumption check: Tukey non-additivity test
                            if mode == "One-way + Block(run) (RCBD recommended)":
                                try:
                                    # Tukey 1-df test for non-additivity
                                    fitted = model.fittedvalues
                                    resid_vals = model.resid
                                    d_tukey = d.copy()
                                    d_tukey["_fitted_sq"] = fitted ** 2
                                    model_aug = smf.ols(f"{yvar} ~ C(rule) + C(run) + _fitted_sq", data=d_tukey).fit()
                                    anova_aug = sm.stats.anova_lm(model_aug, typ=2)
                                    if "_fitted_sq" in anova_aug.index:
                                        p_nonadd = float(anova_aug.loc["_fitted_sq", "PR(>F)"])
                                        st.write(f"Tukey Non-additivity: p={p_nonadd:.3g}")
                                        if p_nonadd < alpha:
                                            st.warning("⚠️ Significant block×treatment interaction detected (Tukey non-additivity p < alpha). RCBD additivity assumption may be violated.")
                                except Exception as e_tukey:
                                    st.caption(f"Tukey non-additivity test skipped: {e_tukey}")

                            # Residual Diagnostics
                            st.markdown("##### Residual Diagnostics")
                            resid = model.resid
                            fitted_vals = model.fittedvalues

                            # Shapiro-Wilk
                            if len(resid) >= 3:
                                try:
                                    W, p_shap = (sps.shapiro(resid.sample(min(len(resid), 500), random_state=0))
                                                if len(resid) > 500 else sps.shapiro(resid))
                                    st.write(f"Shapiro-Wilk: W={W:.4f}, p={p_shap:.3g}")
                                except Exception as e:
                                    p_shap = 1.0; st.caption(f"Shapiro-Wilk computation failed: {e}")
                            else:
                                p_shap = 1.0

                            # Anderson-Darling
                            try:
                                ad_result = sps.anderson(resid, dist="norm", method="interpolate")
                                st.write(f"Anderson-Darling: A²={ad_result.statistic:.4f}, "
                                         f"p={ad_result.pvalue:.4f}")
                                if ad_result.pvalue < 0.05:
                                    st.caption("Anderson-Darling rejects normality at 5% level.")
                            except Exception:
                                pass

                            # QQ plot
                            qq = sps.probplot(resid, dist="norm")
                            qq_df = pd.DataFrame({"Theoretical": qq[0][0], "Residual": np.sort(resid)})
                            st.altair_chart(alt.Chart(qq_df).mark_point().encode(x="Theoretical:Q", y="Residual:Q").properties(title="QQ Plot", height=280), width='stretch')

                            # Residual histogram
                            st.altair_chart(alt.Chart(pd.DataFrame({"resid": resid})).mark_bar().encode(x=alt.X("resid:Q", bin=alt.Bin(maxbins=40)), y="count()").properties(title="Residual Histogram", height=200), width='stretch')

                            # Residuals vs Fitted scatter
                            rvf_df = pd.DataFrame({"Fitted": fitted_vals, "Residual": resid})
                            rvf_chart = alt.Chart(rvf_df).mark_point(opacity=0.5).encode(
                                x=alt.X("Fitted:Q"), y=alt.Y("Residual:Q")
                            ).properties(title="Residuals vs Fitted", height=280)
                            zero_line = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="red", strokeDash=[4,4]).encode(y="y:Q")
                            st.altair_chart(rvf_chart + zero_line, width='stretch')
                        

                            # p_shap 스칼라 보정 (Levene는 사후검정 섹션에서 1회만 수행)
                            p_shap = _scalar(p_shap, default=1.0)
                            p_lev  = np.nan  # 아래 사후검정 섹션에서 계산
                            alpha  = _scalar(alpha,  default=0.05)

                            # ===== 사후검정 & CLD =====
                            st.markdown("##### Post-hoc Tests")
                            posthoc = pd.DataFrame(); explain = ""

                            def _small_is_better(m: str) -> bool:
                                # Time, PDR(woG 포함)=작을수록 좋음 / Reward류=클수록 좋음
                                return (m == "Time") or m.startswith("PDR")

                            # --- EMM-based post-hoc for RCBD; Games-Howell for One-way ---
                            def _emm_pairwise(model_obj, data, rule_col, block_col, yvar, alpha_val):
                                """
                                Estimated Marginal Means (EMM) pairwise comparison.
                                Uses RCBD model's MS_residual as the pooled error term.
                                Pairwise differences tested with t-distribution, Holm-corrected.
                                """
                                ms_res = model_obj.mse_resid
                                df_res = model_obj.df_resid
                                rules = sorted(data[rule_col].unique())
                                n_per_cell = data.groupby(rule_col).size()

                                # EMM = marginal mean of each rule (averaged over blocks)
                                emm = data.groupby(rule_col)[yvar].mean()

                                pairs, pvals, diffs = [], [], []
                                for g1, g2 in itertools.combinations(rules, 2):
                                    diff = emm[g1] - emm[g2]
                                    n1, n2 = n_per_cell[g1], n_per_cell[g2]
                                    se = np.sqrt(ms_res * (1.0/n1 + 1.0/n2))
                                    t_stat = diff / se if se > 0 else 0
                                    p_val = 2.0 * (1.0 - sps.t.cdf(abs(t_stat), df_res))
                                    pairs.append((g1, g2))
                                    pvals.append(p_val)
                                    diffs.append(diff)

                                from statsmodels.stats.multitest import multipletests
                                reject, p_adj, _, _ = multipletests(pvals, method="holm", alpha=alpha_val)
                                ph = pd.DataFrame({
                                    "group1": [p[0] for p in pairs],
                                    "group2": [p[1] for p in pairs],
                                    "diff": diffs,
                                    "p-adj": p_adj,
                                    "reject": reject,
                                })
                                return ph, emm

                            if mode == "One-way + Block(run) (RCBD recommended)":
                                # EMM-based pairwise comparison using RCBD model error
                                try:
                                    posthoc, emm_means = _emm_pairwise(model, d, "rule", "run", yvar, alpha)
                                    means_for_cld = emm_means.sort_values(ascending=_small_is_better(metric))
                                    explain = "EMM pairwise t-tests (RCBD MS_residual) + Holm correction"
                                except Exception as e_emm:
                                    # Fallback to block-adjusted Games-Howell
                                    dd = block_adjust(d, yvar, block_col="run").rename(columns={"y_adj": yvar})
                                    dd_work = _make_dd_work(dd, yvar)
                                    means_for_cld = _means_series(dd_work, "rule", "__y__").sort_values(
                                        ascending=_small_is_better(metric))
                                    try:
                                        import pingouin as pg
                                        gh = pg.pairwise_gameshowell(dv="__y__", between="rule", data=dd_work)
                                        posthoc = gh.rename(columns={"A":"group1","B":"group2","pval":"p-adj"})
                                        posthoc["reject"] = posthoc["p-adj"] < alpha
                                        explain = f"Games-Howell on block-adjusted y* (EMM failed: {e_emm})"
                                    except Exception:
                                        y_post = dd_work["__y__"]; grp_post = dd_work["rule"]
                                        posthoc = welch_holm_posthoc(
                                            pd.DataFrame({"rule": grp_post.values, "y": y_post.values}),
                                            "rule", "y", alpha=alpha)
                                        explain = f"Welch t + Holm on block-adjusted y* (EMM failed: {e_emm})"
                                # Levene on block-adjusted residuals
                                dd_lev = block_adjust(d, yvar, block_col="run").rename(columns={"y_adj": yvar})
                                dd_lev_work = _make_dd_work(dd_lev, yvar)
                                lev_groups = [g["__y__"].values for _, g in dd_lev_work.groupby("rule")]
                            else:
                                # One-way: Games-Howell (robust to unequal variance)
                                dd_work = _make_dd_work(d, yvar)
                                y_post  = dd_work["__y__"]
                                grp_post= dd_work["rule"]
                                means_for_cld = _means_series(dd_work, "rule", "__y__").sort_values(
                                    ascending=_small_is_better(metric))
                                lev_groups = [g["__y__"].values for _, g in dd_work.groupby("rule")]
                                try:
                                    import pingouin as pg
                                    gh = pg.pairwise_gameshowell(dv="__y__", between="rule", data=dd_work)
                                    posthoc = gh.rename(columns={"A":"group1","B":"group2","pval":"p-adj"})
                                    posthoc["reject"] = posthoc["p-adj"] < alpha
                                    explain = "Games-Howell"
                                except Exception:
                                    posthoc = welch_holm_posthoc(
                                        pd.DataFrame({"rule": grp_post.values, "y": y_post.values}),
                                        "rule", "y", alpha=alpha)
                                    explain = "Pairwise Welch t-tests + Holm correction (pingouin unavailable)"

                            try:
                                if len(lev_groups) >= 2 and all(len(x) > 1 for x in lev_groups):
                                    p_lev = sps.levene(*lev_groups, center="median").pvalue
                                else:
                                    p_lev = np.nan
                                st.write(f"Levene(Brown-Forsythe): p={_scalar(p_lev):.3g}")
                            except Exception:
                                p_lev = np.nan

                            # --- 결과 출력 & CLD ---
                            if not posthoc.empty:
                                st.caption(explain)
                                st.dataframe(posthoc, width='stretch')

                                ph = posthoc.copy()
                                if ("p-adj" not in ph.columns) and ("reject" not in ph.columns):
                                    st.info("No p-value information available for CLD.")
                                else:
                                    cld = cld_from_pairs(means_for_cld, ph, alpha=alpha)
                                    st.markdown("##### CLD (shared letter = no significant difference, 'a' = best)")
                                    st.caption("CLD uses the absorption algorithm (Piepho 2004). Groups may have multiple letters (e.g. 'ab'). "
                                               "Two groups sharing at least one letter are not significantly different.")
                                    st.dataframe(cld, width='stretch')

                                    # 최종 후보(‘A’ 그룹) — 지표 방향에 맞춰 정렬
                                    st.markdown(f"#### Top Candidates (**{metric}**, groups containing letter 'a')")
                                    top = cld[cld["CLD"].str.contains("a", na=False)].sort_values("mean", ascending=_small_is_better(metric))
                                    st.dataframe(top, width='stretch')

                                    # ================== A그룹 교집합 (Reward ∩ Time ∩ PDR, RCBD 기준) ==================구해도 좋습니다.")
                                    st.markdown("### A-Group Intersection (Reward ∩ Time(asc) ∩ PDR(asc), RCBD)")

                                    def _prep_metric(dfraw_all: pd.DataFrame, metric_name: str):
                                        """raw(long)에서 metric 행 추출 + rule 컬럼 보정."""
                                        dsub = dfraw_all[dfraw_all["metric"] == metric_name].copy()
                                        if dsub.empty:
                                            return pd.DataFrame()
                                        if "rule" not in dsub.columns:
                                            dsub["rule"] = dsub[["Phase","RedPolicy","RedAction","YellowAction"]].agg(", ".join, axis=1)
                                        return dsub

                                    def _transform_for_metric(d: pd.DataFrame, metric_name: str, eps: float = 1e-6):
                                        """
                                        변환 스케일:
                                        - PDR(woG 포함): logit
                                        - Time, Reward(woG 포함): 원척도
                                        """
                                        d = d.copy(); yvar = "value"
                                        if metric_name.startswith("PDR"):
                                            d[yvar] = np.log((d[yvar] + eps)/(1 - d[yvar] + eps))  # logit
                                            scale = "logit"
                                        else:
                                            scale = "original"
                                        return d, yvar, scale

                                    def _rcbd_posthoc_cld(d: pd.DataFrame, yvar: str, alpha: float = 0.05, prefer_small_is_A: bool = False):
                                        """
                                        RCBD: y ~ C(rule) + C(run), EMM-based pairwise t-tests using
                                        the model's MS_residual as pooled error, Holm-corrected.
                                        CLD via absorption algorithm (Piepho 2004).
                                        prefer_small_is_A=True  → ascending sort (a = smallest = Best)
                                        prefer_small_is_A=False → descending sort (a = largest = Best)
                                        """
                                        from scipy import stats as sps

                                        posthoc = pd.DataFrame()
                                        explain = ""

                                        # Fit RCBD model for this metric
                                        try:
                                            rcbd_model = smf.ols(f"{yvar} ~ C(rule) + C(run)", data=d).fit()
                                            posthoc_emm, emm_means = _emm_pairwise(rcbd_model, d, "rule", "run", yvar, alpha)
                                            posthoc = posthoc_emm
                                            means_for_cld = emm_means.sort_values(ascending=prefer_small_is_A)
                                            explain = "EMM pairwise t-tests (RCBD MS_residual) + Holm"
                                        except Exception as e_emm:
                                            # Fallback: block-adjusted Games-Howell
                                            dd = block_adjust(d, yvar, block_col="run").rename(columns={"y_adj": yvar})
                                            dd_work = _make_dd_work(dd, yvar)
                                            means_for_cld = _means_series(dd_work, "rule", "__y__").sort_values(
                                                ascending=prefer_small_is_A)
                                            try:
                                                import pingouin as pg
                                                gh = pg.pairwise_gameshowell(dv="__y__", between="rule", data=dd_work)
                                                posthoc = gh.rename(columns={"A":"group1","B":"group2","pval":"p-adj"})
                                                posthoc["reject"] = posthoc["p-adj"] < alpha
                                                explain = f"Games-Howell block-adjusted (EMM failed: {e_emm})"
                                            except Exception:
                                                y_post = dd_work["__y__"]; grp_post = dd_work["rule"]
                                                posthoc = welch_holm_posthoc(
                                                    pd.DataFrame({"rule": grp_post.values, "y": y_post.values}),
                                                    "rule", "y", alpha=alpha)
                                                explain = f"Welch t + Holm block-adjusted (EMM failed: {e_emm})"

                                        # --- CLD 산출
                                        if posthoc.empty or (("p-adj" not in posthoc.columns) and ("reject" not in posthoc.columns)):
                                            return means_for_cld, pd.DataFrame(), explain

                                        cld = cld_from_pairs(means_for_cld, posthoc, alpha=alpha)
                                        return means_for_cld, cld, explain

                                    with st.expander("A-Group Intersection (Reward up, Time down, PDR down)", expanded=True):
                                        alpha_int = st.slider("Alpha for intersection", 0.001, 0.1, 0.05, 0.001, key="alpha_intersect_all")
                                        alpha_int = float(alpha_int)   # 슬라이더 값 스칼라화
                                        # --- Reward (클수록 A) ---
                                        d_rew = _prep_metric(dfraw, "Reward")
                                        if d_rew.empty:
                                            st.info("No Reward data.")
                                            A_rew, disp_rew = set(), pd.Series(dtype=float)
                                        else:
                                            d_rew_tr, y_rew, _ = _transform_for_metric(d_rew, "Reward")
                                            means_rew, cld_rew, _ = _rcbd_posthoc_cld(d_rew_tr, y_rew, alpha=alpha_int, prefer_small_is_A=False)
                                            A_rew = set(cld_rew.loc[cld_rew["CLD"].str.contains("a", na=False),"rule"]) if not cld_rew.empty else set()
                                            disp_rew = d_rew.groupby("rule")["value"].mean().rename("Reward_mean(orig)")

                                        # --- Time (작을수록 A) ---
                                        d_time = _prep_metric(dfraw, "Time")
                                        if d_time.empty:
                                            st.info("No Time data.")
                                            A_time, disp_time = set(), pd.Series(dtype=float)
                                        else:
                                            d_time_tr, y_time, _ = _transform_for_metric(d_time, "Time")
                                            means_time, cld_time, _ = _rcbd_posthoc_cld(d_time_tr, y_time, alpha=alpha_int, prefer_small_is_A=True)
                                            A_time = set(cld_time.loc[cld_time["CLD"].str.contains("a", na=False),"rule"]) if not cld_time.empty else set()
                                            disp_time = d_time.groupby("rule")["value"].mean().rename("Time_mean(orig)")

                                        # --- PDR (작을수록 A; logit 분석, 표시는 원척도 평균) ---
                                        d_pdr = _prep_metric(dfraw, "PDR")
                                        if d_pdr.empty:
                                            st.info("No PDR data.")
                                            A_pdr, disp_pdr = set(), pd.Series(dtype=float)
                                        else:
                                            d_pdr_tr, y_pdr, _ = _transform_for_metric(d_pdr, "PDR")
                                            means_pdr, cld_pdr, _ = _rcbd_posthoc_cld(d_pdr_tr, y_pdr, alpha=alpha_int, prefer_small_is_A=True)
                                            A_pdr = set(cld_pdr.loc[cld_pdr["CLD"].str.contains("a", na=False),"rule"]) if not cld_pdr.empty else set()
                                            disp_pdr = d_pdr.groupby("rule")["value"].mean().rename("PDR_mean(orig)")

                                        # --- 집합 & 교집합 결과 표시 ---
                                        st.markdown(f"- **A(Reward)**: {len(A_rew)}, **A(Time)**: {len(A_time)}, **A(PDR)**: {len(A_pdr)}")

                                        inter_RT  = sorted(A_rew.intersection(A_time))
                                        inter_RP  = sorted(A_rew.intersection(A_pdr))
                                        inter_TP  = sorted(A_time.intersection(A_pdr))
                                        inter_RTP = sorted(A_rew.intersection(A_time).intersection(A_pdr))

                                        def _show_table(title, rules):
                                            st.markdown(f"**{title}** — {len(rules)} rules")
                                            if len(rules) == 0:
                                                st.caption("N/A")
                                                return
                                            out = (pd.DataFrame({"rule": rules})
                                                    .merge(disp_rew, on="rule", how="left")
                                                    .merge(disp_time, on="rule", how="left")
                                                    .merge(disp_pdr, on="rule", how="left"))
                                            # 정렬: 3중 교집합은 Reward↓(내림차순), tie-breaker로 Time↑, PDR↑
                                            if "3중" in title:
                                                out = out.sort_values(["Reward_mean(orig)", "Time_mean(orig)", "PDR_mean(orig)"],
                                                                    ascending=[False, True, True], kind="mergesort")
                                            elif "Reward∩Time" in title:
                                                out = out.sort_values(["Reward_mean(orig)", "Time_mean(orig)"],
                                                                    ascending=[False, True], kind="mergesort")
                                            elif "Reward∩PDR" in title:
                                                out = out.sort_values(["Reward_mean(orig)", "PDR_mean(orig)"],
                                                                    ascending=[False, True], kind="mergesort")
                                            elif "Time∩PDR" in title:
                                                out = out.sort_values(["Time_mean(orig)", "PDR_mean(orig)"],
                                                                    ascending=[True, True], kind="mergesort")
                                            st.dataframe(out, width='stretch')

                                        _show_table("Triple Intersection (Reward ∩ Time ∩ PDR)", inter_RTP)
                                        _show_table("Double Intersection (Reward∩Time)", inter_RT)
                                        _show_table("Double Intersection (Reward∩PDR)", inter_RP)
                                        _show_table("Double Intersection (Time∩PDR)", inter_TP)

                            else:
                                st.caption("No post-hoc test results.")


# ------------------------------
# Data Tables 탭 (편집/읽기 분리 + 파일명 라벨)
# ------------------------------
with tabs[3]:
    st.subheader("CSV Tables (Edit/Save)")
    bp = st.session_state.base_path
    exp = st.session_state.selected_exp
    coord = st.session_state.selected_coord
    if not (bp and exp and coord):
        st.info("Select a scenario from the sidebar first.")
    else:
        coord_folder = Path(bp) / "scenarios" / exp / coord
        st.caption(str(coord_folder))
        csvs = list_coord_csvs(bp, exp, coord)
        # 편집 대상에서 안전센터/소방서 원본 제외
        csvs_editable = [p for p in csvs if os.path.basename(p) != "안전센터와 소방서.csv"]
        if not csvs_editable:
            st.info("No editable CSV files found.")
        else:
            labels = {p: os.path.basename(p) for p in csvs_editable}
            target = st.selectbox("CSV to Edit", options=list(labels.keys()), format_func=lambda p: labels[p])
            df = read_csv_smart(target)
            edit = st.data_editor(df, width='stretch', num_rows="dynamic", height=400)
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("💾 Save (auto backup)"):
                    write_csv_smart(edit, target)
                    st.success("Save complete")
            with c2:
                if st.button("🔄 Refresh"):
                    st.rerun()
            with c3:
                yaml_path = find_yaml_in_coord(bp, exp, coord)
                if yaml_path and st.button("▶️ Re-run with Modified Values"):
                    try:
                        from orchestrator import Orchestrator
                        with st.spinner("Running simulation..."):
                            orc = Orchestrator(base_path=bp)
                            result = orc.run_simulation(config_path=yaml_path)
                        if result["ok"]:
                            st.success("✅ Simulation complete!")
                            st.write(f"• Log file: `{result['log_file']}`")
                        else:
                            st.error(f"❌ Execution failed (code: {result['returncode']})")
                            with st.expander("stdout"):
                                st.text(result.get("stdout", ""))
                            with st.expander("stderr"):
                                st.text(result.get("stderr", ""))
                    except Exception as e:
                        st.error("Simulation execution error")
                        st.exception(e)

        st.markdown("#### Hospital Master (Excel, read-only)")
        hdf = read_excel_hospital(bp)
        if hdf is not None and not hdf.empty:
            st.dataframe(hdf.head(200), width='stretch', height=280)
        else:
            st.caption("Hospital Excel data not found or load failed")

        st.markdown("#### Fire Station Master (read-only)")
        global_center_csv = Path(bp) / "scenarios" / "안전센터와 소방서.csv"
        if global_center_csv.is_file():
            cdf = read_csv_smart(str(global_center_csv))
            st.dataframe(cdf.head(200), width='stretch', height=260)
        else:
            st.caption("Fire station CSV not found")

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

# ------------------------------
# Generate 탭 (독립적, 마지막 탭)
# ------------------------------
# ──────────────────────────────────────────────────────────────────────────────
# Rerun 탭 (기존 시나리오 재실행)
# ──────────────────────────────────────────────────────────────────────────────
with tabs[4]:
    st.subheader("🔄 Re-run Existing Scenario")
    st.info("💡 This tab operates **independently** from the sidebar. Select an existing scenario to modify parameters and re-run.")

    # ─────────────────────────────────────────────────────────────────
    # Rerun 탭 전용 base_path 입력
    # ─────────────────────────────────────────────────────────────────
    if "rerun_base_path" not in st.session_state:
        st.session_state.rerun_base_path = CLOUD_BASE_PATH if IS_CLOUD else DEFAULT_LOCAL_BASE_PATH
    else:
        if IS_CLOUD and st.session_state.rerun_base_path != CLOUD_BASE_PATH:
            st.session_state.rerun_base_path = CLOUD_BASE_PATH


    st.markdown("---")
    st.markdown("### Project Path Setup")

    col_path, col_btn = st.columns([4, 1])
    with col_path:
        rerun_bp_input = st.text_input(
            "🗂️ Project Path (base_path)",
            value=st.session_state.rerun_base_path,
            placeholder="e.g. C:\\Users\\USER\\MCI_ADV",
            help="Enter the project root path containing the scenarios folder",
            key="rerun_bp_input",
            disabled=IS_CLOUD,
        )
        if IS_CLOUD:
            st.caption(f"☁️ Cloud: fixed to `{CLOUD_BASE_PATH}`.")

    with col_btn:
        st.write("")  # 정렬용
        st.write("")  # 정렬용
        if (not IS_CLOUD) and st.button("✅ Confirm Path", key="rerun_check_path"):
            st.session_state.rerun_base_path = rerun_bp_input


    bp_rerun = st.session_state.rerun_base_path

    # 경로 유효성 검사
    if not bp_rerun:
        st.warning("⚠️ Enter the project path above and click **✅ Confirm Path**.")
        st.stop()

    if not base_ok(bp_rerun):
        st.error(f"❌ Invalid path: `{bp_rerun}`")
        st.caption("• Check if the path exists\n• Check if the `scenarios` folder is present")
        st.stop()

    st.success(f"✅ Valid path: `{bp_rerun}`")

    # ─────────────────────────────────────────────────────────────────
    # Orchestrator 로드
    # ─────────────────────────────────────────────────────────────────
    try:
        from orchestrator import Orchestrator
    except Exception as e:
        st.error("❌ `src/sce_src/orchestrator.py` not found.")
        st.exception(e)
        st.stop()

    # ─────────────────────────────────────────────────────────────────
    # 실험 폴더 및 좌표 폴더 선택
    # ─────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Select Scenario")

    # 실험/좌표 목록 만들기
    exps_rerun = list_experiments_any(bp_rerun)
    if not exps_rerun:
        st.warning("⚠️ No experiments found in scenarios folder.")
        st.stop()

    sel_exp_rerun = st.selectbox(
        "📂 Select Experiment Folder",
        options=exps_rerun,
        key="sel_exp_rerun",
        help="Select an experiment folder from scenarios"
    )

    coords_rerun = list_coords_from_scenarios(bp_rerun, sel_exp_rerun) if sel_exp_rerun else []
    if not coords_rerun:
        st.warning(f"⚠️ No coordinate folders in experiment `{sel_exp_rerun}`.")
        st.stop()

    sel_coord_rerun = st.selectbox(
        "📍 Select Coordinate Folder",
        options=coords_rerun,
        key="sel_coord_rerun",
        help="Select a coordinate folder from the experiment"
    )

    # ─────────────────────────────────────────────────────────────────
    # YAML 파일 읽기 및 파라미터 수정 UI
    # ─────────────────────────────────────────────────────────────────
    if sel_exp_rerun and sel_coord_rerun:
        cfg_path_rerun = os.path.join(bp_rerun, "scenarios", sel_exp_rerun, sel_coord_rerun, f"config_{sel_coord_rerun}.yaml")

        if not os.path.exists(cfg_path_rerun):
            st.error(f"❌ CONFIG file not found: `{cfg_path_rerun}`")
            st.stop()

        st.success(f"✅ CONFIG file: `{os.path.basename(cfg_path_rerun)}`")

        try:
            with open(cfg_path_rerun, "r", encoding="utf-8") as f:
                yaml_data_rerun = yaml.safe_load(f)

            # ─────────────────────────────────────────────────────────────────
            # 현재 설정 표시
            # ─────────────────────────────────────────────────────────────────
            st.markdown("---")
            st.markdown("### Current Config")

            with st.expander("📋 View Current Scenario Config", expanded=False):
                st.json(yaml_data_rerun)

            # ─────────────────────────────────────────────────────────────────
            # 파라미터 수정 UI
            # ─────────────────────────────────────────────────────────────────
            st.markdown("---")
            st.markdown("### 🔧 Edit Parameters")
            st.caption("⚠️ Changing departure time, incident size, or coordinates requires scenario regeneration (API re-call)")

            col1, col2 = st.columns(2)

            # Ambulance 파라미터
            with col1:
                st.markdown("**Ambulance**")
                amb_cfg_rerun = yaml_data_rerun.get('entity_info', {}).get('ambulance', {})
                is_use_time_amb_rerun = st.checkbox(
                    "Use API Duration",
                    value=amb_cfg_rerun.get('is_use_time', True),
                    key="rerun_is_use_time",
                    help="True: use API duration. False: compute time from distance / velocity."
                )
                amb_velocity_rerun = st.number_input(
                    "Ambulance Speed (km/h)",
                    value=float(amb_cfg_rerun.get('velocity', 40)),
                    min_value=1.0,
                    step=1.0,
                    key="rerun_amb_velocity"
                )
                amb_handover_rerun = st.number_input(
                    "Patient Handover Time (min)",
                    value=float(amb_cfg_rerun.get('handover_time', 10.0)),
                    min_value=0.0,
                    step=0.5,
                    key="rerun_amb_handover"
                )
                duration_coeff_rerun = st.number_input(
                    "API Duration Weight",
                    value=float(amb_cfg_rerun.get('duration_coeff', 1.0)),
                    min_value=0.1,
                    max_value=10.0,
                    step=0.1,
                    format="%.1f",
                    key="rerun_duration_coeff",
                    help="Coefficient multiplied with the API duration (default: 1.0)."
                )

            # UAV 파라미터
            with col2:
                st.markdown("**UAV**")
                uav_cfg_rerun = yaml_data_rerun.get('entity_info', {}).get('uav', {})
                uav_velocity_rerun = st.number_input(
                    "UAV Speed (km/h)",
                    value=float(uav_cfg_rerun.get('velocity', 80)),
                    min_value=1.0,
                    step=1.0,
                    key="rerun_uav_velocity"
                )
                uav_handover_rerun = st.number_input(
                    "Patient Handover Time (min)",
                    value=float(uav_cfg_rerun.get('handover_time', 15.0)),
                    min_value=0.0,
                    step=0.5,
                    key="rerun_uav_handover"
                )

            st.markdown("**🏥 Hospital**")
            col3, col4 = st.columns(2)
            with col3:
                hosp_cfg_rerun = yaml_data_rerun.get('entity_info', {}).get('hospital', {})
                max_send_coeff_rerun = st.text_input(
                    "hospital_max_send_coeff",
                    value=str(hosp_cfg_rerun.get('max_send_coeff', [1, 1])).strip('[]'),
                    key="rerun_max_send_coeff",
                    help="e.g. 1.1, 1.0"
                )

            with col4:
                run_cfg_rerun = yaml_data_rerun.get('run_setting', {})
                total_samples_rerun = st.number_input(
                    "Simulation Iterations",
                    value=int(run_cfg_rerun.get('totalSamples', 30)),
                    min_value=1,
                    step=1,
                    key="rerun_total_samples"
                )

            # ─────────────────────────────────────────────────────────────────
            # 실행 버튼
            # ─────────────────────────────────────────────────────────────────
            st.markdown("---")
            if st.button("▶️ Apply Changes & Run Simulation", key="btn_rerun_execute"):
                try:
                    # YAML 백업 생성 (타임스탬프) - 수정 전에 백업
                    import shutil
                    backup_path_rerun = cfg_path_rerun.replace(".yaml", f"_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}.yaml")
                    shutil.copy(cfg_path_rerun, backup_path_rerun)
                    st.info(f"📦 Original YAML backup: `{os.path.basename(backup_path_rerun)}`")

                    # YAML 파일을 문자열로 읽어서 직접 수정 (주석과 형식 유지)
                    with open(cfg_path_rerun, "r", encoding="utf-8") as f:
                        yaml_text_rerun = f.read()

                    # max_send_coeff 파싱
                    try:
                        coeff_list_rerun = [float(x.strip()) for x in max_send_coeff_rerun.split(',')]
                        coeff_str_rerun = "[" + ", ".join(str(c) for c in coeff_list_rerun) + "]"
                    except:
                        st.warning("max_send_coeff format error, keeping original value")
                        coeff_str_rerun = None

                    # 정규식으로 값만 교체 (주석 및 형식 유지)
                    # ambulance velocity
                    yaml_text_rerun = re.sub(
                        r'(ambulance:.*?velocity:\s*)[\d.]+',
                        rf'\g<1>{amb_velocity_rerun}',
                        yaml_text_rerun, flags=re.DOTALL
                    )
                    # ambulance handover_time
                    yaml_text_rerun = re.sub(
                        r'(ambulance:.*?handover_time:\s*)[\d.]+',
                        rf'\g<1>{amb_handover_rerun}',
                        yaml_text_rerun, flags=re.DOTALL
                    )
                    # ambulance is_use_time
                    yaml_text_rerun = re.sub(
                        r'(ambulance:.*?is_use_time:\s*)(True|False|true|false)',
                        rf'\g<1>{"True" if is_use_time_amb_rerun else "False"}',
                        yaml_text_rerun, flags=re.DOTALL
                    )
                    # ambulance duration_coeff
                    # 기존 YAML에 duration_coeff가 있으면 업데이트, 없으면 추가
                    if re.search(r'ambulance:.*?duration_coeff:', yaml_text_rerun, flags=re.DOTALL):
                        # 기존 필드 업데이트
                        yaml_text_rerun = re.sub(
                            r'(ambulance:.*?duration_coeff:\s*)[\d.]+',
                            rf'\g<1>{duration_coeff_rerun}',
                            yaml_text_rerun, flags=re.DOTALL
                        )
                    else:
                        # 필드가 없으면 is_use_time 다음에 추가
                        yaml_text_rerun = re.sub(
                            r'(ambulance:.*?is_use_time:\s*(?:True|False|true|false)[^\n]*\n)',
                            rf'\g<1>    duration_coeff: {duration_coeff_rerun} # API duration 시간가중치 (기본값: 1.0, 환경적 요인 반영시 조정)\n',
                            yaml_text_rerun, flags=re.DOTALL
                        )
                    # uav velocity
                    yaml_text_rerun = re.sub(
                        r'(uav:.*?velocity:\s*)[\d.]+',
                        rf'\g<1>{uav_velocity_rerun}',
                        yaml_text_rerun, flags=re.DOTALL
                    )
                    # uav handover_time
                    yaml_text_rerun = re.sub(
                        r'(uav:.*?handover_time:\s*)[\d.]+',
                        rf'\g<1>{uav_handover_rerun}',
                        yaml_text_rerun, flags=re.DOTALL
                    )

                    if coeff_str_rerun:
                        yaml_text_rerun = re.sub(
                            r'max_send_coeff:\s*\[[\d.,\s]+\]',
                            f'max_send_coeff: {coeff_str_rerun}',
                            yaml_text_rerun
                        )

                    yaml_text_rerun = re.sub(
                        r'(totalSamples:\s*)[\d]+',
                        rf'\g<1>{total_samples_rerun}',
                        yaml_text_rerun
                    )

                    # YAML 저장 - 원본 형식 완벽 유지
                    with open(cfg_path_rerun, "w", encoding="utf-8") as f:
                        f.write(yaml_text_rerun)

                    st.success("✅ YAML file updated!")

                    # 시뮬레이션 실행
                    with st.spinner("Running simulation..."):
                        orc_rerun = Orchestrator(base_path=bp_rerun)
                        res_rerun = orc_rerun.run_simulation(config_path=cfg_path_rerun)

                    if res_rerun["ok"]:
                        st.success("✅ Simulation complete!")
                        st.write(f"• Exp ID: `{res_rerun['exp_id']}`")
                        st.write(f"• Coord: `{res_rerun['coord']}`")
                        st.write(f"• Log file: `{res_rerun['log_file']}`")
                        st.write(f"• Summary CSV has been auto-updated")
                        st.caption("💡 Check results in the Scenarios/Maps tabs.")
                    else:
                        st.error(f"❌ Simulation failed (code: {res_rerun['returncode']})")
                        with st.expander("stdout"):
                            st.text(res_rerun.get("stdout", ""))
                        with st.expander("stderr"):
                            st.text(res_rerun.get("stderr", ""))

                except Exception as e_rerun:
                    st.error("❌ Simulation execution error")
                    st.exception(e_rerun)

        except Exception as e_yaml_rerun:
            st.error(f"❌ YAML file read failed: {e_yaml_rerun}")
            st.exception(e_yaml_rerun)
