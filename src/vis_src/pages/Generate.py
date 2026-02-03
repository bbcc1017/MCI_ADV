# Generate.py
# 새 시나리오 생성 전용 독립 페이지
# -------------------------------------------------------------------------------------------------
import os, re, yaml, shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium


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

KST = timezone(timedelta(hours=9))

# Page config
st.set_page_config(
    page_title="새 시나리오 만들기",
    page_icon="➕",
    layout="wide"
)

# ─────────────────────────────────────────────────────────────────
# 유틸리티 함수
# ─────────────────────────────────────────────────────────────────
def base_ok(bp: str) -> bool:
    """base_path가 유효한지 확인 (scenarios 폴더 존재)"""
    if not bp:
        return False
    scenarios = os.path.join(bp, "scenarios")
    return os.path.isdir(scenarios)

def parse_env_kv(text: str):
    """환경변수 텍스트를 파싱"""
    env = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env

def get_kakao_key_from_secrets():
    """Streamlit Cloud Secrets(TOML) / 환경변수에서 카카오 키를 읽어옴"""
    # 1) Streamlit Secrets (권장)
    try:
        # 최우선: TOP-LEVEL 키
        for k in ("KAKAO_REST_API_KEY", "KAKAO_API_KEY", "KAKAO_KEY"):
            if k in st.secrets:
                return str(st.secrets[k]).strip()

        # 섹션 방식도 지원: [kakao] rest_api_key="..."
        if "kakao" in st.secrets:
            sec = st.secrets["kakao"]
            for k in ("rest_api_key", "api_key", "key"):
                if k in sec:
                    return str(sec[k]).strip()
    except Exception:
        pass

    # 2) 환경변수 fallback (원하면 쓸 수 있게)
    return (os.getenv("KAKAO_REST_API_KEY") or os.getenv("KAKAO_API_KEY") or "").strip()

def normalize_search_result(doc, search_type):
    """Normalize API response to unified format for both keyword and address searches"""
    if search_type == "키워드 검색":
        return {
            "place_name": doc.get("place_name", ""),
            "address_name": doc.get("address_name", ""),
            "x": float(doc["x"]),
            "y": float(doc["y"]),
            "search_type": "keyword"
        }
    else:  # 주소 검색
        # Prefer building name for display
        building_name = ""
        if "road_address" in doc and doc["road_address"]:
            building_name = doc["road_address"].get("building_name", "")

        display_name = building_name if building_name else doc.get("address_name", "")

        return {
            "place_name": f"{display_name} (주소검색)",
            "address_name": doc.get("address_name", ""),
            "x": float(doc["x"]),
            "y": float(doc["y"]),
            "search_type": "address"
        }


def perform_address_search(search_query, api_key):
    """
    Perform address search using Kakao Local API
    API Doc: https://developers.kakao.com/docs/latest/ko/local/dev-guide#address-coord

    Returns: (success: bool, documents: list, error_msg: str, status_code: int)
    """
    try:
        url = "https://dapi.kakao.com/v2/local/search/address.json"
        headers = {"Authorization": f"KakaoAK {api_key.strip()}"}

        st.caption(f"🔍 디버깅: API 요청 URL = {url}")
        st.caption(f"🔍 디버깅: 검색어 = {search_query}")

        params = {
            "query": search_query,
            "analyze_type": "similar",  # Allow partial matches
            "size": 10
        }

        response = requests.get(url, headers=headers, params=params, timeout=10)
        st.caption(f"🔍 디버깅: 응답 상태 코드 = {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            documents = data.get("documents", [])
            st.caption(f"🔍 디버깅: 결과 개수 = {len(documents)}")

            # Normalize results to match keyword search format
            normalized = [normalize_search_result(doc, "주소 검색") for doc in documents]
            return (True, normalized, "", 200)

        elif response.status_code == 401:
            return (False, [], "API 키 인증 실패 (401 Unauthorized)", 401)

        elif response.status_code == 403:
            return (False, [], "접근 거부됨 (403 Forbidden)", 403)

        else:
            try:
                error_data = response.json()
                error_msg = str(error_data)
            except:
                error_msg = response.text
            return (False, [], f"API 오류 (상태 코드: {response.status_code})", response.status_code)

    except requests.exceptions.Timeout:
        return (False, [], "요청 시간 초과. 네트워크 연결을 확인하세요.", -1)

    except requests.exceptions.RequestException as e:
        error_msg = f"검색 실패: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_msg += f" (상태 코드: {e.response.status_code})"
        return (False, [], error_msg, -1)

    except Exception as e:
        return (False, [], f"예상치 못한 오류: {e}", -1)

# ─────────────────────────────────────────────────────────────────
# Session State 초기화
# ─────────────────────────────────────────────────────────────────
CLOUD_BASE_PATH = _detect_cloud_base_path()
IS_CLOUD = bool(CLOUD_BASE_PATH)
DEFAULT_LOCAL_BASE_PATH = str(REPO_ROOT) if (REPO_ROOT / "scenarios").is_dir() else ""

if "generate_base_path" not in st.session_state:
    st.session_state.generate_base_path = CLOUD_BASE_PATH if IS_CLOUD else DEFAULT_LOCAL_BASE_PATH
else:
    # Cloud에서는 항상 고정 (사용자가 바꿔도 즉시 원복)
    if IS_CLOUD and st.session_state.generate_base_path != CLOUD_BASE_PATH:
        st.session_state.generate_base_path = CLOUD_BASE_PATH

if "gen_state" not in st.session_state:
    st.session_state.gen_state = {}
if "env_txt" not in st.session_state:
    st.session_state.env_txt = ""
# 일괄 생성용 상태
if "batch_coord_rows" not in st.session_state:
    st.session_state.batch_coord_rows = []
if "batch_preset_rows" not in st.session_state:
    st.session_state.batch_preset_rows = []
if "batch_run_log" not in st.session_state:
    st.session_state.batch_run_log = []
# 프리셋 목록 (행 추가 시 사용할 기본 세트)
if "batch_presets" not in st.session_state:
    st.session_state.batch_presets = [{
        "name": "기본",
        "incident_size": 30,
        "amb_size": 30,
        "uav_size": 3,
        "amb_velocity": 40,
        "uav_velocity": 80,
        "amb_handover": 0.0,
        "uav_handover": 0.0,
        "total_samples": 10,
        "random_seed": 0,
        "buffer_ratio": 1.5,
        "max_send_coeff": "1,1",
        "is_use_time": True,
        "duration_coeff": 1.0,
    }]

# 헬퍼: 프리셋 조회/좌표 행 추가
def _get_preset_by_name(name: str):
    for p in st.session_state.batch_presets:
        if str(p.get("name")) == str(name):
            return p
    return st.session_state.batch_presets[0] if st.session_state.batch_presets else {}

def _append_coord_row(label: str, lat: float, lon: float, address: str = "", preset_name: str = "기본", search_source: str = "manual"):
    p = _get_preset_by_name(preset_name)
    row = {
        "label": label or address or f"{lat},{lon}",
        "lat": lat,
        "lon": lon,
        "address": address,
        "incident_size": p.get("incident_size", 30),
        "amb_size": p.get("amb_size", 30),
        "uav_size": p.get("uav_size", 3),
        "amb_velocity": p.get("amb_velocity", 40),
        "uav_velocity": p.get("uav_velocity", 80),
        "amb_handover": p.get("amb_handover", 0.0),
        "uav_handover": p.get("uav_handover", 0.0),
        "total_samples": p.get("total_samples", 10),
        "random_seed": p.get("random_seed", 0),
        "buffer_ratio": p.get("buffer_ratio", 1.5),
        "max_send_coeff": p.get("max_send_coeff", "1,1"),
        "is_use_time": p.get("is_use_time", True),
        "duration_coeff": p.get("duration_coeff", 1.0),
        "preset": preset_name,
        "source": search_source,
    }
    st.session_state.batch_coord_rows.append(row)


def _write_label_map(base_path: str, rows: list[dict]):
    """
    rows: [{exp_id, coord, label, source}]
    scenarios/label_map.csv 에 누적 저장 (exp_id+coord 중복 시 최신 우선)
    """
    if not rows:
        return
    path = Path(base_path) / "scenarios" / "label_map.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["exp_id", "coord", "label", "source"]
    df_new = pd.DataFrame(rows, columns=cols)
    if path.exists():
        try:
            df_old = pd.read_csv(path, encoding="utf-8")
        except Exception:
            df_old = pd.DataFrame(columns=cols)
        df = pd.concat([df_old, df_new], ignore_index=True)
        df = df.drop_duplicates(subset=["exp_id", "coord"], keep="last")
    else:
        df = df_new
    df.to_csv(path, index=False, encoding="utf-8-sig")

# ─────────────────────────────────────────────────────────────────
# 메인 UI
# ─────────────────────────────────────────────────────────────────
st.title("🧪 시나리오 생성 · 실행 (독립 모드)")
st.info("💡 이 페이지는 메인 앱의 사이드바 설정과 **완전히 독립적**으로 작동합니다. 기존 시나리오가 없어도 새로운 시나리오를 생성할 수 있습니다!")

# ─────────────────────────────────────────────────────────────────
# 1. 프로젝트 경로 (base_path) 입력
# ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📁 프로젝트 경로 설정")

col_path, col_btn = st.columns([4, 1])
with col_path:
    generate_bp_input = st.text_input(
        "🗂️ 프로젝트 경로 (base_path)",
        value=st.session_state.generate_base_path,
        placeholder="예: C:\\Users\\사용자명\\MCI_ADV",
        help="scenarios 폴더가 있는 프로젝트 루트 경로를 입력하세요",
        disabled=IS_CLOUD,
    )
    if IS_CLOUD:
        st.caption(f"☁️ Streamlit Cloud에서는 base_path가 `{CLOUD_BASE_PATH}` 로 자동 고정됩니다.")

with col_btn:
    st.write("")  # 정렬용
    st.write("")  # 정렬용
    if (not IS_CLOUD) and st.button("✅ 경로 확인", key="gen_check_path"):
        st.session_state.generate_base_path = generate_bp_input


bp = st.session_state.generate_base_path

# 경로 유효성 검사
if not bp:
    st.warning("⚠️ 위에서 프로젝트 경로를 입력하고 **✅ 경로 확인** 버튼을 클릭하세요.")
    st.stop()

if not base_ok(bp):
    st.error(f"❌ 유효하지 않은 경로입니다: `{bp}`")
    st.caption("• 경로가 존재하는지 확인하세요\n• `scenarios` 폴더가 있는지 확인하세요")
    st.stop()

st.success(f"✅ 유효한 경로: `{bp}`")

# ─────────────────────────────────────────────────────────────────
# 2. Orchestrator 로드
# ─────────────────────────────────────────────────────────────────
try:
    from orchestrator import Orchestrator
except Exception as e:
    st.error("❌ `src/sce_src/orchestrator.py`를 찾지 못했습니다.")
    st.exception(e)
    st.stop()

# ─────────────────────────────────────────────────────────────────
# 3. 시나리오 생성 UI
# ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 1️⃣ 시나리오 생성")

# API 키 입력 및 저장
st.markdown("#### 🔑 카카오 REST API 키")

# session_state 초기화
if "kakao_api_key" not in st.session_state:
    if IS_CLOUD:
        st.session_state.kakao_api_key = get_kakao_key_from_secrets() or ""
    else:
        st.session_state.kakao_api_key = ""
else:
    # Cloud에서는 Secrets 값이 있으면 항상 그 값으로 동기화
    if IS_CLOUD:
        sec = get_kakao_key_from_secrets()
        if sec and st.session_state.kakao_api_key != sec:
            st.session_state.kakao_api_key = sec


col_key, col_save = st.columns([3, 1])

cloud_secret_key = get_kakao_key_from_secrets() if IS_CLOUD else ""
has_cloud_key = bool(cloud_secret_key)

with col_key:
    api_key_input = st.text_input(
        "카카오 REST API 키",
        value=st.session_state.kakao_api_key,
        type="password",
        placeholder="MCI 앱의 REST API 키 (모빌리티 + 로컬 서비스 활성화 필요)",
        help="시나리오 생성 및 좌표 검색에 사용",
        key="api_key_input",
        disabled=IS_CLOUD and has_cloud_key,   # ✅ Cloud+Secrets면 입력 잠금
    )
    if IS_CLOUD and has_cloud_key:
        st.caption("☁️ Cloud Secrets에서 API 키를 자동으로 불러왔습니다.")


with col_save:
    st.write("")  # 정렬용
    st.write("")  # 정렬용

    # ✅ 로컬은 기존 그대로 "저장" 사용
    # ✅ Cloud는 Secrets가 없을 때만 수동 입력 허용(예외 케이스)
    if ((not IS_CLOUD) or (IS_CLOUD and not has_cloud_key)) and st.button("✅ 저장", key="save_api_key"):
        if api_key_input and api_key_input.strip():
            st.session_state.kakao_api_key = api_key_input.strip()
            st.success("✅ API 키가 저장되었습니다!")
        else:
            st.error("⚠️ API 키를 입력하세요!")


# 상태 표시
if st.session_state.kakao_api_key:
    st.caption(f"✅ API 키 저장됨 ({len(st.session_state.kakao_api_key)}자)")
else:
    st.caption("⚠️ API 키 없음")

# 모든 용도에 동일한 키 사용
kakao_api_key = st.session_state.kakao_api_key

# 운행시간 모드 선택
st.markdown("#### 📍 출발 시각 설정")

# session_state 초기화 (한 번만)
if "departure_date_value" not in st.session_state:
    st.session_state.departure_date_value = datetime.now(KST).date()
if "departure_time_value" not in st.session_state:
    st.session_state.departure_time_value = datetime.now(KST).time()

col_date, col_time = st.columns(2)
with col_date:
    departure_date = st.date_input(
        "출발 날짜",
        value=st.session_state.departure_date_value,
        help="사고 발생 예상 날짜",
        key="departure_date_input"
    )
with col_time:
    departure_time = st.time_input(
        "출발 시각",
        value=st.session_state.departure_time_value,
        help="사고 발생 예상 시각",
        key="departure_time_input"
    )

# 값이 변경되면 즉시 session_state에 저장 (한 번 클릭으로 업데이트)
if departure_date != st.session_state.departure_date_value:
    st.session_state.departure_date_value = departure_date
if departure_time != st.session_state.departure_time_value:
    st.session_state.departure_time_value = departure_time

# YYYYMMDDHHMM 형식으로 변환
departure_time_str = f"{st.session_state.departure_date_value.strftime('%Y%m%d')}{st.session_state.departure_time_value.strftime('%H%M')}"
st.caption(f"→ API 파라미터: `{departure_time_str}`")

# is_use_time 플래그 및 duration_coeff
col_time1, col_time2 = st.columns(2)
with col_time1:
    is_use_time = st.checkbox(
        "✅ API 기반 이송시간 사용 (권장)",
        value=True,
        help="체크: API에서 받은 duration(분) 사용 | 미체크: 거리/속도 기반 계산"
    )
with col_time2:
    duration_coeff = st.number_input(
        "API duration 시간가중치",
        value=1.0,
        min_value=0.1,
        max_value=10.0,
        step=0.1,
        format="%.1f",
        help="API duration에 곱해지는 계수 (기본값: 1.0, 날씨/교통상황 등 환경 요인 반영)"
    )

st.markdown("---")
st.markdown("### 2️⃣ 좌표 검색하기")

# Search type selector
search_type = st.radio(
    "검색 방식 선택",
    ["키워드 검색", "주소 검색"],
    horizontal=True,
    key="search_type_radio",
    help="키워드: 장소명으로 검색 (예: 인천공항) | 주소: 도로명/지번주소로 검색"
)

# session_state 초기화
if "search_type" not in st.session_state:
    st.session_state.search_type = "키워드 검색"

# Clear results when switching search types
if st.session_state.search_type != search_type:
    st.session_state.search_type = search_type
    st.session_state.search_results = []
    st.session_state.selected_place_index = -1

if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "selected_lat" not in st.session_state:
    st.session_state.selected_lat = 37.465833
if "selected_lon" not in st.session_state:
    st.session_state.selected_lon = 126.443333
if "selected_place_name" not in st.session_state:
    st.session_state.selected_place_name = ""
if "selected_place_index" not in st.session_state:
    st.session_state.selected_place_index = -1  # -1은 선택 안 됨

col_search, col_search_btn = st.columns([3, 1])
with col_search:
    # Dynamic placeholder and help text based on search type
    if search_type == "키워드 검색":
        placeholder = "예: 인천공항, 서울역, 강남역"
        help_text = "카카오 API로 장소를 검색합니다"
        label = "🔍 장소 검색"
    else:
        placeholder = "예: 서울특별시 강남구 테헤란로 152"
        help_text = "카카오 API로 주소를 검색합니다 (도로명주소, 지번주소 모두 가능)"
        label = "🔍 주소 검색"

    search_keyword = st.text_input(
        label,
        placeholder=placeholder,
        help=help_text,
        key="search_input"
    )
with col_search_btn:
    st.write("")  # 정렬용
    st.write("")  # 정렬용
    search_button = st.button("🔎 검색", key="search_place")

# 검색 실행
if search_button and search_keyword:
    # REST API 키 확인
    if not kakao_api_key or not kakao_api_key.strip():
        st.error("⚠️ 먼저 카카오 REST API 키를 입력하고 '✅ 저장' 버튼을 클릭하세요!")
    else:
        # Route to appropriate search based on selected type
        if search_type == "키워드 검색":
            # ─────────────────────────────────────────────────────────────────
            # 키워드 검색
            # ─────────────────────────────────────────────────────────────────
            try:
                # 카카오 로컬 API - 키워드 검색
                # 공식 문서: https://developers.kakao.com/docs/latest/ko/local/dev-guide#search-by-keyword
                url = "https://dapi.kakao.com/v2/local/search/keyword.json"

                # 헤더: Authorization: KakaoAK {REST_API_KEY}
                headers = {
                    "Authorization": f"KakaoAK {kakao_api_key.strip()}"
                }

                # 디버깅: 요청 정보 출력
                st.caption(f"🔍 디버깅: API 요청 URL = {url}")
                st.caption(f"🔍 디버깅: 헤더 = Authorization: KakaoAK {kakao_api_key[:4]}...{kakao_api_key[-4:]}")
                st.caption(f"🔍 디버깅: 검색어 = {search_keyword}")

                params = {
                    "query": search_keyword,
                    "size": 10  # 최대 10개 결과
                }

                # API 요청
                response = requests.get(url, headers=headers, params=params, timeout=10)

                # 상태 코드 디버깅
                st.caption(f"🔍 디버깅: 응답 상태 코드 = {response.status_code}")

                # 응답 확인
                if response.status_code == 200:
                    data = response.json()
                    documents = data.get("documents", [])

                    st.caption(f"🔍 디버깅: 응답 데이터 키 = {list(data.keys())}")
                    st.caption(f"🔍 디버깅: 결과 개수 = {len(documents)}")

                    if documents:
                        # Normalize keyword results
                        normalized = [normalize_search_result(doc, "키워드 검색") for doc in documents]
                        st.session_state.search_results = normalized
                        st.success(f"✅ {len(documents)}개 장소를 찾았습니다!")
                    else:
                        st.warning("⚠️ 검색 결과가 없습니다.")
                        st.session_state.search_results = []
                elif response.status_code == 401:
                    st.error("❌ API 키 인증 실패 (401 Unauthorized)")
                    st.caption("REST API 키가 올바른지 확인하세요.")
                    try:
                        error_data = response.json()
                        st.code(error_data, language="json")
                    except:
                        st.code(response.text)
                elif response.status_code == 403:
                    st.error("❌ 접근 거부됨 (403 Forbidden)")
                    st.caption("플랫폼 설정 및 API 키 권한을 확인하세요.")
                    try:
                        error_data = response.json()
                        st.code(error_data, language="json")
                    except:
                        st.code(response.text)
                else:
                    st.error(f"❌ API 오류 (상태 코드: {response.status_code})")
                    try:
                        error_data = response.json()
                        st.code(error_data, language="json")
                    except:
                        st.code(response.text)

            except requests.exceptions.Timeout:
                st.error("❌ 요청 시간 초과. 네트워크 연결을 확인하세요.")
            except requests.exceptions.RequestException as e:
                st.error(f"❌ 검색 실패: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    st.caption(f"상태 코드: {e.response.status_code}")
                    try:
                        st.code(e.response.json(), language="json")
                    except:
                        st.code(e.response.text)
            except Exception as e:
                st.error(f"❌ 예상치 못한 오류: {e}")
                import traceback
                st.code(traceback.format_exc())

        else:  # 주소 검색
            # ─────────────────────────────────────────────────────────────────
            # 주소 검색
            # ─────────────────────────────────────────────────────────────────
            success, documents, error_msg, status_code = perform_address_search(search_keyword, kakao_api_key)

            if success:
                if documents:
                    st.session_state.search_results = documents
                    st.success(f"✅ {len(documents)}개 주소를 찾았습니다!")
                else:
                    st.warning("⚠️ 검색 결과가 없습니다. 주소를 확인해주세요.")
                    st.info("""💡 **주소 검색 팁:**
- 도로명주소: `서울특별시 강남구 테헤란로 152`
- 지번주소: `서울특별시 강남구 역삼동 737`
- 간단하게: `강남구 테헤란로 152` (시도명 생략 가능)
                    """)
                    st.session_state.search_results = []
            else:
                # Display error based on status code
                if status_code == 401:
                    st.error(f"❌ {error_msg}")
                    st.caption("REST API 키가 올바른지 확인하세요.")
                elif status_code == 403:
                    st.error(f"❌ {error_msg}")
                    st.caption("플랫폼 설정 및 API 키 권한을 확인하세요.")
                else:
                    st.error(f"❌ {error_msg}")

# ─────────────────────────────────────────────────────────────────
# 검색 결과 표시
# ─────────────────────────────────────────────────────────────────
if st.session_state.search_results:
    st.markdown("#### 검색 결과")

    # 지도 생성 (중심: 첫 번째 결과)
    first = st.session_state.search_results[0]
    center_lat = float(first["y"])
    center_lon = float(first["x"])

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles="OpenStreetMap"
    )

    # 마커 추가
    for idx, place in enumerate(st.session_state.search_results):
        place_name = place.get("place_name", "")
        address = place.get("address_name", "")
        lat = float(place["y"])
        lon = float(place["x"])

        # 팝업 내용
        popup_html = f"""
        <div style="width: 200px;">
            <b>{place_name}</b><br>
            {address}<br>
            <small>위도: {lat:.6f}</small><br>
            <small>경도: {lon:.6f}</small>
        </div>
        """

        # 선택된 장소는 빨간색, 나머지는 파란색
        is_selected = (st.session_state.selected_place_index == idx)
        marker_color = "red" if is_selected else "blue"

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=place_name,
            icon=folium.Icon(color=marker_color, icon="info-sign")
        ).add_to(m)

    # 지도 표시
    st_folium(m, width=700, height=400, returned_objects=[])

    # 결과 테이블
    preset_options = [p.get("name","") for p in st.session_state.batch_presets]
    add_preset_choice = st.selectbox("선택 시 적용할 프리셋", options=preset_options, key="search_add_preset")
    st.markdown("**장소 목록 (클릭하여 선택 / 리스트 추가)**")
    for idx, place in enumerate(st.session_state.search_results):
        place_name = place.get("place_name", "")
        address = place.get("address_name", "")
        lat = float(place["y"])
        lon = float(place["x"])

        col1, col2 = st.columns([4, 1])
        with col1:
            st.write(f"**{idx+1}. {place_name}**")
            st.caption(f"📍 {address}")
            st.caption(f"좌표: ({lat:.6f}, {lon:.6f})")
        with col2:
            if st.button("선택", key=f"select_{idx}"):
                st.session_state.selected_lat = lat
                st.session_state.selected_lon = lon
                st.session_state.selected_place_name = place_name
                st.session_state.selected_place_index = idx  # 선택된 인덱스 저장
                st.success(f"✅ '{place_name}' 선택됨!")
                st.rerun()
            if st.button("리스트 추가", key=f"addlist_{idx}"):
                disp_label = place_name or address or f"{lat:.5f},{lon:.5f}"
                _append_coord_row(disp_label, lat, lon, address, add_preset_choice, place.get("search_type", "manual"))
                st.success(f"📌 리스트에 추가됨: {disp_label}")

        if idx < len(st.session_state.search_results) - 1:
            st.markdown("---")

# 선택된 좌표 표시
if st.session_state.selected_place_name:
    st.info(f"📌 선택된 장소: **{st.session_state.selected_place_name}** ({st.session_state.selected_lat:.6f}, {st.session_state.selected_lon:.6f})")

st.markdown("---")
st.markdown("### 3️⃣ 시나리오 파라미터")
colA, colB, colC = st.columns(3)
with colA:
    latitude  = st.number_input("위도 (latitude)", value=st.session_state.selected_lat, format="%.6f")
    incident_size = st.number_input("환자수 (incident_size)", value=30, min_value=1, step=1)
    amb_velocity  = st.number_input("구급차 속도 (km/h)", value=40, min_value=1, step=1)
    amb_handover_time = st.number_input("구급차 환자 인계시간 (분)", value=0.0, min_value=0.0, step=0.1, format="%.1f", help="현장에서 환자를 싣거나 병원에 내리는 시간")
    total_samples = st.number_input("시뮬레이션 반복 (totalSamples)", value=10, min_value=1, step=1)
with colB:
    longitude = st.number_input("경도 (longitude)", value=st.session_state.selected_lon, format="%.6f")
    amb_size  = st.number_input("구급차 수 (amb_size)", value=30, min_value=1, step=1)
    uav_velocity = st.number_input("UAV 속도 (km/h)", value=80, min_value=1, step=1)
    uav_handover_time = st.number_input("UAV 환자 인계시간 (분)", value=0.0, min_value=0.0, step=0.1, format="%.1f", help="현장에서 환자를 싣거나 병원에 내리는 시간")
    random_seed  = st.number_input("랜덤시드", value=0, min_value=0, step=1)
with colC:
    uav_size = st.number_input("UAV 수 (uav_size)", value=3, min_value=0, step=1)
    hospital_max_send_coeff = st.text_input("max_send_coeff (예: 1.05,1)", value="1,1")
    buffer_ratio = st.number_input("buffer_ratio", value=1.5, min_value=1.0, step=0.1)


if st.button("📦 시나리오 생성", key="btn_generate_scenario"):
        # API 키 검증
    if not kakao_api_key or not kakao_api_key.strip():
        st.error("⚠️ 카카오 API 키를 입력하세요!")
        st.stop()

    try:
        env = parse_env_kv(st.session_state.env_txt)
        extra_args = {
            "buffer_ratio": buffer_ratio,
            "hospital_max_send_coeff": hospital_max_send_coeff.strip(),
            "kakao_api_key": kakao_api_key.strip(),
            "departure_time": departure_time_str,
            "is_use_time": str(is_use_time).lower(),  # "true" or "false"
            "amb_handover_time": float(amb_handover_time),
            "uav_handover_time": float(uav_handover_time),
            "duration_coeff": float(duration_coeff)
        }
        orc = Orchestrator(base_path=bp)
        res = orc.generate_scenario(
            latitude=latitude, longitude=longitude,
            incident_size=int(incident_size),
            amb_size=int(amb_size), uav_size=int(uav_size),
            amb_velocity=int(amb_velocity), uav_velocity=int(uav_velocity),
            total_samples=int(total_samples), random_seed=int(random_seed),
            exp_id=None,  # 항상 자동 생성
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

        label_text = (st.session_state.selected_place_name or "").strip()
        if label_text:
            try:
                _write_label_map(bp, [{
                    "exp_id": res["exp_id"],
                    "coord": str(res["coord"]),
                    "label": label_text,
                    "source": "single",
                }])
            except Exception as lm_err:
                st.warning(f"label_map update failed: {lm_err}")

        st.success("✅ 시나리오 생성 완료!")
        st.write(f"• 실험ID: `{res['exp_id']}`")
        st.write(f"• 좌표: `{res['coord']}`")
        st.write(f"• CONFIG_PATH: `{res['config_path']}`")
        st.write(f"• 요약 CSV(신규): `{res['summary_csv_path']}`")
        st.write(f"• 로그 파일: `{res['log_file']}`")

    except Exception as e:
        st.error("❌ 시나리오 생성 중 오류")
        st.exception(e)

# ─────────────────────────────────────────────────────────────────
# 4. 방금 생성한 시나리오 즉시 실행
# ─────────────────────────────────────────────────────────────────
if st.session_state.gen_state and st.session_state.gen_state.get("config_path"):
    st.markdown("---")
    st.markdown("### 4️⃣ 방금 생성한 시나리오 즉시 실행")
    st.info("위에서 생성한 시나리오를 시뮬레이션 실행합니다.")
    st.code(f"CONFIG: {st.session_state.gen_state.get('config_path')}")

    if st.button("▶️ 즉시 시뮬레이션 실행", key="btn_immediate_run"):
        try:
            orc_imm = Orchestrator(base_path=bp)
            res_imm = orc_imm.run_simulation(config_path=st.session_state.gen_state["config_path"])

            # 최신 상태 업데이트
            st.session_state.gen_state.update({
                "exp_id": res_imm["exp_id"],
                "coord": res_imm["coord"],
                "config_path": res_imm["config_path"],
                "summary_csv_path": res_imm["summary_csv_path"],
                "summary_csv_path_legacy": res_imm["summary_csv_path_legacy"],
                "log_file": res_imm["log_file"]
            })

            st.success("✅ 시뮬레이션 완료!")
            st.write(f"• 로그 파일: `{res_imm['log_file']}`")
            st.caption("메인 앱의 Scenarios/Maps 탭에서 바로 확인해 보세요.")

        except Exception as e_imm:
            st.error("❌ 시뮬레이션 실행 중 오류")
            st.exception(e_imm)

# ------------------------------
# 5. 일괄(멀티) 시나리오 생성/실행
# ------------------------------
st.markdown("---")
st.markdown("### 4️⃣ 일괄(여러 좌표 × 파라미터) 시나리오 생성/실행")
st.caption("검색/주소에서 추가한 리스트를 한 번에 생성하고, 필요 시 바로 시뮬레이션까지 실행합니다.")

# 프리셋 편집
st.markdown("#### 프리셋 편집 (기본값 세트)")
default_preset = [{
    "name": "기본",
    "incident_size": 30,
    "amb_size": 30,
    "uav_size": 3,
    "amb_velocity": 40,
    "uav_velocity": 80,
    "amb_handover": 0.0,
    "uav_handover": 0.0,
    "total_samples": 10,
    "random_seed": 0,
    "buffer_ratio": 1.5,
    "max_send_coeff": "1,1",
    "is_use_time": True,
    "duration_coeff": 1.0,
}]
preset_df = pd.DataFrame(st.session_state.batch_presets)
if preset_df.empty:
    preset_df = pd.DataFrame(default_preset)
if isinstance(st.session_state.get("preset_editor"), pd.DataFrame):
    preset_df = st.session_state.preset_editor
preset_edited = st.data_editor(
    preset_df,
    num_rows="dynamic",
    hide_index=True,
    width='stretch',
    column_config={
        "name": st.column_config.TextColumn("프리셋 이름", required=True),
        "incident_size": st.column_config.NumberColumn("incident_size", step=1, format="%d"),
        "amb_size": st.column_config.NumberColumn("amb_size", step=1, format="%d"),
        "uav_size": st.column_config.NumberColumn("uav_size", step=1, format="%d"),
        "amb_velocity": st.column_config.NumberColumn("AMB 속도", step=1, format="%d"),
        "uav_velocity": st.column_config.NumberColumn("UAV 속도", step=1, format="%d"),
        "amb_handover": st.column_config.NumberColumn("AMB 핸드오버(분)", step=0.1, format="%.1f"),
        "uav_handover": st.column_config.NumberColumn("UAV 핸드오버(분)", step=0.1, format="%.1f"),
        "total_samples": st.column_config.NumberColumn("totalSamples", step=1, format="%d"),
        "random_seed": st.column_config.NumberColumn("random_seed", step=1, format="%d"),
        "buffer_ratio": st.column_config.NumberColumn("buffer_ratio", step=0.1, format="%.2f"),
        "max_send_coeff": st.column_config.TextColumn("max_send_coeff"),
        "is_use_time": st.column_config.CheckboxColumn("API duration 사용"),
        "duration_coeff": st.column_config.NumberColumn("duration_coeff", step=0.1, format="%.1f"),
    },
    key="preset_editor"
)
if isinstance(st.session_state.get("preset_editor"), pd.DataFrame):
    preset_edited = st.session_state.preset_editor
presets_clean = preset_edited.dropna(how="all").to_dict(orient="records")
st.session_state.batch_presets = presets_clean if presets_clean else default_preset
preset_names = [p.get("name", "") for p in st.session_state.batch_presets]

# 좌표 + 파라미터 통합 테이블
st.markdown("#### 좌표 + 파라미터 테이블 (행 추가/수정)")
coord_columns = [
    "label", "lat", "lon", "address", "preset",
    "incident_size", "amb_size", "uav_size",
    "amb_velocity", "uav_velocity",
    "amb_handover", "uav_handover",
    "total_samples", "random_seed",
    "buffer_ratio", "max_send_coeff",
    "is_use_time", "duration_coeff",
    "source"
]
if st.session_state.batch_coord_rows:
    coord_df = pd.DataFrame(st.session_state.batch_coord_rows)
else:
    coord_df = pd.DataFrame(columns=coord_columns)
coord_df = coord_df.reindex(columns=coord_columns)
if isinstance(st.session_state.get("batch_coord_editor_v2"), pd.DataFrame):
    coord_df = st.session_state.batch_coord_editor_v2
coord_edited = st.data_editor(
    coord_df,
    num_rows="dynamic",
    hide_index=True,
    width='stretch',
    column_config={
        "label": st.column_config.TextColumn("라벨", help="결과 비교 시 표시될 이름"),
        "lat": st.column_config.NumberColumn("위도", format="%.6f"),
        "lon": st.column_config.NumberColumn("경도", format="%.6f"),
        "address": st.column_config.TextColumn("주소", required=False),
        "preset": st.column_config.SelectboxColumn("프리셋", options=preset_names or ["기본"]),
        "incident_size": st.column_config.NumberColumn("incident_size", step=1, format="%d"),
        "amb_size": st.column_config.NumberColumn("amb_size", step=1, format="%d"),
        "uav_size": st.column_config.NumberColumn("uav_size", step=1, format="%d"),
        "amb_velocity": st.column_config.NumberColumn("AMB 속도", step=1, format="%d"),
        "uav_velocity": st.column_config.NumberColumn("UAV 속도", step=1, format="%d"),
        "amb_handover": st.column_config.NumberColumn("AMB 핸드오버(분)", step=0.1, format="%.1f"),
        "uav_handover": st.column_config.NumberColumn("UAV 핸드오버(분)", step=0.1, format="%.1f"),
        "total_samples": st.column_config.NumberColumn("totalSamples", step=1, format="%d"),
        "random_seed": st.column_config.NumberColumn("random_seed", step=1, format="%d"),
        "buffer_ratio": st.column_config.NumberColumn("buffer_ratio", step=0.1, format="%.2f"),
        "max_send_coeff": st.column_config.TextColumn("max_send_coeff"),
        "is_use_time": st.column_config.CheckboxColumn("API duration 사용"),
        "duration_coeff": st.column_config.NumberColumn("duration_coeff", step=0.1, format="%.1f"),
        "source": st.column_config.TextColumn("출처(검색/수동)", disabled=True),
    },
    key="batch_coord_editor_v2"
)
if isinstance(st.session_state.get("batch_coord_editor_v2"), pd.DataFrame):
    coord_edited = st.session_state.batch_coord_editor_v2
st.session_state.batch_coord_rows = coord_edited.dropna(how="all").to_dict(orient="records")

# 실행 설정
st.markdown("**일괄 실행 설정**")
col_b1, col_b2 = st.columns(2)
with col_b1:
    batch_prefix = st.text_input("exp_id 접두어", value="batch")
    st.caption("exp_ 뒤에 붙는 접두어 설정으로 영어 단어로만 설정 권장")
    add_ts = st.checkbox("타임스탬프 자동 부여", value=True)
    if re.search(r"\s", batch_prefix or "") or any(ord(ch) > 127 for ch in batch_prefix):
        st.warning("exp_id ???? ??? ????, ????? ?????.")
with col_b2:
    do_run = st.radio("실행 모드", ["생성만", "생성 + 시뮬"], horizontal=True)

if st.button("일괄 실행", type="primary", key="btn_batch_run"):
    rows = [r for r in st.session_state.batch_coord_rows if pd.notna(r.get("lat")) and pd.notna(r.get("lon"))]
    if not rows:
        st.error("좌표/파라미터 테이블에 위도·경도를 입력하거나 '리스트 추가'로 채워주세요.")
    elif not kakao_api_key:
        st.error("카카오 REST API 키를 먼저 입력하세요.")
    else:
        prefix = batch_prefix.strip() or "batch"
        if add_ts:
            prefix = f"{prefix}_{datetime.now(KST).strftime('%Y%m%d_%H%M%S')}"
        env = parse_env_kv(st.session_state.env_txt)
        run_log = []
        label_records = []
        orc = Orchestrator(base_path=bp)
        preset_lookup = {p.get("name"): p for p in st.session_state.batch_presets}

        for ridx, row in enumerate(rows, start=1):
            preset_name = row.get("preset") or (preset_names[0] if preset_names else "기본")
            preset = preset_lookup.get(preset_name) or _get_preset_by_name(preset_name)

            def pick(key, default):
                val = row.get(key)
                return preset.get(key, default) if pd.isna(val) else val

            lat_val = float(row.get("lat"))
            lon_val = float(row.get("lon"))
            label_val = row.get("label") or f"coord{ridx}"
            exp_id = f"{prefix}_c{ridx}"
            extra_args = {
                "buffer_ratio": float(pick("buffer_ratio", 1.5)),
                "hospital_max_send_coeff": str(pick("max_send_coeff", "1,1")).strip(),
                "kakao_api_key": kakao_api_key.strip(),
                "departure_time": departure_time_str,
                "is_use_time": str(bool(pick("is_use_time", True))).lower(),
                "amb_handover_time": float(pick("amb_handover", 0)),
                "uav_handover_time": float(pick("uav_handover", 0)),
                "duration_coeff": float(pick("duration_coeff", 1.0)),
            }
            rec = {
                "exp_id": exp_id,
                "label": label_val,
                "coord": (lat_val, lon_val),
                "preset": preset_name,
                "status": "pending",
                "config_path": None,
                "log_file": None,
                "error": "",
            }


            try:
                gen = orc.generate_scenario(
                    latitude=lat_val,
                    longitude=lon_val,
                    incident_size=int(pick("incident_size", 30)),
                    amb_size=int(pick("amb_size", 30)),
                    uav_size=int(pick("uav_size", 3)),
                    amb_velocity=int(pick("amb_velocity", 40)),
                    uav_velocity=int(pick("uav_velocity", 80)),
                    total_samples=int(pick("total_samples", 10)),
                    random_seed=int(pick("random_seed", 0)),
                    exp_id=exp_id,
                    extra_env=env,
                    extra_args=extra_args,
                )
                rec["status"] = "generated"
                rec["config_path"] = gen.get("config_path")
                rec["log_file"] = gen.get("log_file")
                exp_id_actual = gen.get("exp_id", exp_id)
                coord_str = str(gen.get("coord") or f"({lat_val},{lon_val})")
                label_records.append({
                    "exp_id": exp_id_actual,
                    "coord": coord_str,
                    "label": label_val,
                    "source": row.get("source") or ("keyword" if row.get("source") == "keyword" else "manual"),
                })

                if do_run == "생성 + 시뮬" and gen.get("config_path"):
                    sim = orc.run_simulation(config_path=gen["config_path"], extra_env=env)
                    rec["status"] = "simulated" if sim.get("ok") else f"sim fail ({sim.get('returncode')})"
                    rec["log_file"] = sim.get("log_file") or rec["log_file"]
                run_log.append(rec)
            except Exception as e:
                rec["status"] = "error"
                rec["error"] = str(e)
                run_log.append(rec)

        st.session_state.batch_run_log = run_log
        try:
            _write_label_map(bp, label_records)
        except Exception as lm_err:
            st.warning(f"라벨 기록 저장 중 경고: {lm_err}")
        st.success(f"일괄 실행 완료 ({len(run_log)}개)")

if st.session_state.batch_run_log:
    st.markdown("**일괄 실행 로그**")
    st.dataframe(pd.DataFrame(st.session_state.batch_run_log), width='stretch', hide_index=True)

st.markdown("---")
st.caption("💡 생성된 시나리오는 메인 앱에서 확인하거나, 아래에서 기존 시나리오를 수정해서 재실행할 수 있습니다.")
