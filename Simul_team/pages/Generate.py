# Generate.py
# 새 시나리오 생성 전용 독립 페이지
# -------------------------------------------------------------------------------------------------
import os, re, yaml, shutil
from datetime import datetime, timezone, timedelta
import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static

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

# ─────────────────────────────────────────────────────────────────
# Session State 초기화
# ─────────────────────────────────────────────────────────────────
CLOUD_BASE_PATH = "/mount/src/mci_adv/Simul_team"
IS_CLOUD = os.path.isdir(CLOUD_BASE_PATH)

if "generate_base_path" not in st.session_state:
    st.session_state.generate_base_path = CLOUD_BASE_PATH if IS_CLOUD else ""
else:
    # Cloud에서는 항상 고정 (사용자가 바꿔도 즉시 원복)
    if IS_CLOUD and st.session_state.generate_base_path != CLOUD_BASE_PATH:
        st.session_state.generate_base_path = CLOUD_BASE_PATH

if "gen_state" not in st.session_state:
    st.session_state.gen_state = {}
if "env_txt" not in st.session_state:
    st.session_state.env_txt = ""

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
        placeholder="예: C:\\Users\\사용자명\\MCI_ADV\\Simul_team",
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
    st.error("❌ orchestrator.py를 프로젝트 루트에 두세요.")
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
    st.session_state.kakao_api_key = ""

col_key, col_save = st.columns([3, 1])

with col_key:
    api_key_input = st.text_input(
        "카카오 REST API 키",
        value=st.session_state.kakao_api_key,
        type="password",
        placeholder="MCI 앱의 REST API 키 (모빌리티 + 로컬 서비스 활성화 필요)",
        help="시나리오 생성 및 좌표 검색에 사용",
        key="api_key_input"
    )

with col_save:
    st.write("")  # 정렬용
    st.write("")  # 정렬용
    if st.button("✅ 저장", key="save_api_key"):
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

# session_state 초기화
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
    search_keyword = st.text_input(
        "🔍 장소 검색",
        placeholder="예: 인천공항, 서울역, 강남역",
        help="카카오 API로 장소를 검색합니다"
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
                    st.session_state.search_results = documents
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

# 검색 결과 표시
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
    folium_static(m, width=700, height=400)

    # 결과 테이블
    st.markdown("**장소 목록 (클릭하여 선택)**")
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

st.markdown("---")
st.caption("💡 생성된 시나리오는 메인 앱에서 확인하거나, 아래에서 기존 시나리오를 수정해서 재실행할 수 있습니다.")
