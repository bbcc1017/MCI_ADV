# ui/components.py
import streamlit as st
import pandas as pd

def inject_css(path: str = "assets/styles.css"):
    """외부 CSS 파일을 주입"""
    try:
        with open(path, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        # CSS가 없어도 앱이 죽지 않도록 무시
        pass

def header():
    st.markdown(
        """
        <div class="main-header">
            <h1>🚨 MCI 재난대응 시뮬레이션 대시보드</h1>
            <p>적대적 재난 에이전트 생성을 활용한 복합재난 대응기술개발 | 개발자: 류연우</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_resource_summary(scenario_data: dict, fixed_params: dict):
    """탭1 오른쪽 ‘현황 표’ 그리드"""
    tier1_count = tier2_count = total_beds = 0
    avg_distance = closest_hospital = closest_dist = None

    # 병원 통계
    if "hospitals" in scenario_data and isinstance(scenario_data["hospitals"], pd.DataFrame):
        hospitals_df = scenario_data["hospitals"]
        tier1_count = len(hospitals_df[hospitals_df["종별코드"] == 1])
        tier2_count = len(hospitals_df[hospitals_df["종별코드"] != 1])
        total_beds = int(hospitals_df["병상수"].sum())

    # 거리 통계
    if "distances" in scenario_data and isinstance(scenario_data["distances"], pd.DataFrame):
        distances_df = scenario_data["distances"]
        if not distances_df.empty and "distance" in distances_df.columns:
            avg_distance = float(distances_df["distance"].mean())
            min_dist_idx = distances_df["distance"].idxmin()
            if "hospitals" in scenario_data and min_dist_idx < len(scenario_data["hospitals"]):
                closest_hospital = scenario_data["hospitals"].iloc[min_dist_idx]["요양기관명"]
                closest_dist = float(distances_df.iloc[min_dist_idx]["distance"])

    # 구급차/UAV 수
    num_ambulances = 0
    if "ambulances" in scenario_data and isinstance(scenario_data["ambulances"], pd.DataFrame):
        num_ambulances = len(scenario_data["ambulances"])

    num_uav = 0
    if "uavs" in scenario_data and isinstance(scenario_data["uavs"], pd.DataFrame):
        num_uav = len(scenario_data["uavs"])

    # 평균 출동거리
    avg_amb_km = None
    if "ambulances" in scenario_data and isinstance(scenario_data["ambulances"], pd.DataFrame):
        if "init_distance" in scenario_data["ambulances"].columns and not scenario_data["ambulances"]["init_distance"].empty:
            avg_amb_km = float(scenario_data["ambulances"]["init_distance"].mean())

    # 환자 비율 (파일이 없으면 FIXED_PARAMS 사용)
    red_r = yellow_r = green_r = black_r = None
    if "patients" in scenario_data and isinstance(scenario_data["patients"], pd.DataFrame):
        dfp = scenario_data["patients"]
        if {"type", "ratio"}.issubset(dfp.columns):
            grp = dfp.groupby("type")["ratio"].sum()
            red_r = float(grp.get("Red", 0))
            yellow_r = float(grp.get("Yellow", 0))
            green_r = float(grp.get("Green", 0))
            black_r = float(grp.get("Black", 0))

    if red_r is None:
        ratio = fixed_params.get("ratio_dict", {})
        red_r = float(ratio.get("Red", 0))
        yellow_r = float(ratio.get("Yellow", 0))
        green_r = float(ratio.get("Green", 0))
        black_r = float(ratio.get("Black", 0))

    total_patients = int(fixed_params.get("incident_size", 0))

    # 5칼럼 표 렌더
    c1, c2, c3, c4, c5 = st.columns(5, gap="small")

    with c1:
        st.markdown('<div class="summary-grid"><div class="header">📊주변 자원 현황</div><div class="body">', unsafe_allow_html=True)
        if avg_distance is not None:
            st.markdown(f"<p>평균 거리: {avg_distance:.1f} km</p>", unsafe_allow_html=True)
        if closest_hospital is not None and closest_dist is not None:
            st.markdown(f"<p>가장 가까운 병원: {closest_hospital}</p>", unsafe_allow_html=True)
            st.markdown(f"<p>가까운 병원 거리: {closest_dist:.1f} km</p>", unsafe_allow_html=True)
        st.markdown("</div></div>", unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="summary-grid"><div class="header">🏥병원 현황</div><div class="body">', unsafe_allow_html=True)
        st.markdown(f"<p>상급종합병원: {tier1_count:,} </p>", unsafe_allow_html=True)
        st.markdown(f"<p>일반병원: {tier2_count:,} </p>", unsafe_allow_html=True)
        st.markdown(f"<p>총 병상수: {total_beds:,} 병상</p>", unsafe_allow_html=True)
        st.markdown("</div></div>", unsafe_allow_html=True)

    with c3:
        st.markdown('<div class="summary-grid"><div class="header">🚑구급차 현황</div><div class="body">', unsafe_allow_html=True)
        st.markdown(f"<p>이용 가능한 구급차: {num_ambulances:,} 대</p>", unsafe_allow_html=True)
        if avg_amb_km is not None:
            st.markdown(f"<p>평균 출동거리: {avg_amb_km:.1f} km</p>", unsafe_allow_html=True)
        st.markdown("</div></div>", unsafe_allow_html=True)

    with c4:
        st.markdown('<div class="summary-grid"><div class="header">🚁UAV 현황</div><div class="body">', unsafe_allow_html=True)
        st.markdown(f"<p>UAV 수: {num_uav:,} 대</p>", unsafe_allow_html=True)
        st.markdown("</div></div>", unsafe_allow_html=True)

    with c5:
        st.markdown('<div class="summary-grid"><div class="header">환자 중증도 설정</div><div class="body">', unsafe_allow_html=True)
        st.markdown(f"<p>총 환자 수: {total_patients:,} 명</p>", unsafe_allow_html=True)
        st.markdown(f"<p>🔴Red 비율: {red_r*100:.0f}%</p>", unsafe_allow_html=True)
        st.markdown(f"<p>🟡Yellow 비율: {yellow_r*100:.0f}%</p>", unsafe_allow_html=True)
        st.markdown(f"<p>🟢Green 비율: {green_r*100:.0f}%</p>", unsafe_allow_html=True)
        st.markdown(f"<p>⚫Black 비율: {black_r*100:.0f}%</p>", unsafe_allow_html=True)
        st.markdown("</div></div>", unsafe_allow_html=True)
