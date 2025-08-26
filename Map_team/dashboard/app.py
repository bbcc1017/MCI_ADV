import os, sys, time
import streamlit as st

# --- 안전한 경로 삽입 (루트 실행 보장) ---
BASE_DIR = os.path.dirname(__file__)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import FIXED_PARAMS
from paths import SCENARIOS_PATH
from data_loaders import get_available_scenarios, load_scenario_data
from ui.components import inject_css, header
from ui import tabs_map, tabs_run, tabs_analysis, tabs_resources, tabs_settings

st.set_page_config(page_title="MCI 재난대응 시뮬레이션", page_icon="🚨", layout="wide", initial_sidebar_state="expanded")
inject_css("assets/styles.css")

# ----------------------------------------
# 헤더
header()

# 사이드바
with st.sidebar:
    st.header("🛠️ 시뮬레이션 설정")
    scenarios = get_available_scenarios()
    if not scenarios:
        st.error("시나리오 폴더를 찾을 수 없습니다!")
        st.stop()

    st.subheader("📍 재난 발생 지점")
    selected_location = st.selectbox("시나리오 선택", options=list(scenarios.keys()), index=0)

    current = scenarios[selected_location]
    latitude  = current['lat']
    longitude = current['lon']
    scenario_folder = current['folder']
    coord_str = current['coord_str']

    st.info(f"📌 좌표: ({latitude}, {longitude})")
    st.info(f"📁 폴더: {scenario_folder}")

    st.subheader("⚙️ 시뮬레이션 파라미터")
    st.markdown("**고정 설정값:**")
    c1, c2 = st.columns(2)
    with c1:
        st.metric("총 환자 수", FIXED_PARAMS["incident_size"])
        st.metric("구급차 수", FIXED_PARAMS["ambulance_count"])
        st.metric("UAV 수", FIXED_PARAMS["uav_size"])
    with c2:
        st.metric("Red 비율", f"{FIXED_PARAMS['ratio_dict']['Red']*100:.0f}%")
        st.metric("Yellow 비율", f"{FIXED_PARAMS['ratio_dict']['Yellow']*100:.0f}%")
        st.metric("Green 비율", f"{FIXED_PARAMS['ratio_dict']['Green']*100:.0f}%")

    st.subheader("🔮 향후 업데이트 예정")
    st.slider("총 환자 수 (업데이트 예정)", 10, 100, FIXED_PARAMS["incident_size"], disabled=True)
    st.slider("구급차 수 (업데이트 예정)", 1, 50, FIXED_PARAMS["ambulance_count"], disabled=True)
    st.slider("UAV 수 (업데이트 예정)", 1, 10, FIXED_PARAMS["uav_size"], disabled=True)

# 세션 공유 값
st.session_state["FIXED_PARAMS"] = FIXED_PARAMS
st.session_state["latitude"] = latitude
st.session_state["longitude"] = longitude
st.session_state["scenarios"] = scenarios

# 시나리오 데이터 로딩
scenario_data = load_scenario_data(scenario_folder)

# 탭 구성
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🗺️ 재난지점 분석", "📊 시뮬레이션 실행", "📈 결과 분석", "🏥 자원 분포", "⚙️ 설정 관리"
])

with tab1:
    tabs_map.render_tab(selected_location, latitude, longitude, scenario_data)

with tab2:
    tabs_run.render_tab(selected_location, scenario_folder, coord_str, scenario_data)

with tab3:
    tabs_analysis.render_tab(selected_location, coord_str)

with tab4:
    tabs_resources.render_tab(scenario_data)

with tab5:
    tabs_settings.render_tab(selected_location, scenario_folder, coord_str, scenario_data)

# 푸터
st.markdown("---")
c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("현재 시나리오", selected_location)
with c2: st.metric("전체 시나리오", f"{len(scenarios)}개")
with c3: st.metric("병원 수", len(scenario_data.get('hospitals', [])) if 'hospitals' in scenario_data else 0)
with c4: st.metric("마지막 업데이트", time.strftime('%H:%M:%S'))

st.markdown("""
<div style="text-align:center; color:#9CA3AF; padding:20px;">
  <p>🚨 MCI 재난대응 시뮬레이션 대시보드 v2.0</p>
  <p>적대적 재난 에이전트 생성을 활용한 복합재난 대응기술개발</p>
  <p>개발자: 류연우 | 인하대학교 | 실제 데이터 기반 통합 대시보드</p>
</div>
""", unsafe_allow_html=True)
