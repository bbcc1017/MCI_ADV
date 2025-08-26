# ui/tabs_map.py
import folium, pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from data_loaders import load_excel_hospital_data

def _render_summary(scenario_data, fixed_params):
    # 탭 내 간단 요약 (원래 render_resource_summary의 축약)
    c1, c2, c3, c4, c5 = st.columns(5, gap="small")
    hospitals = scenario_data.get("hospitals")
    distances = scenario_data.get("distances")
    ambulances = scenario_data.get("ambulances")
    uavs = scenario_data.get("uavs")

    with c1:
        st.markdown("**📊 주변 자원**")
        if isinstance(distances, pd.DataFrame) and "distance" in distances:
            avg = distances["distance"].mean()
            st.write(f"평균 거리: {avg:.1f} km")
            idx = distances["distance"].idxmin()
            if isinstance(hospitals, pd.DataFrame) and idx < len(hospitals):
                st.write(f"가까운 병원: {hospitals.iloc[idx]['요양기관명']}")

    with c2:
        st.markdown("**🏥 병원**")
        if isinstance(hospitals, pd.DataFrame):
            tier1 = (hospitals["종별코드"] == 1).sum()
            tier2 = (hospitals["종별코드"] != 1).sum()
            beds = int(hospitals["병상수"].sum())
            st.write(f"상급: {tier1} | 일반: {tier2}")
            st.write(f"총 병상: {beds:,}")

    with c3:
        st.markdown("**🚑 구급차**")
        if isinstance(ambulances, pd.DataFrame):
            st.write(f"대수: {len(ambulances)}")
            if "init_distance" in ambulances:
                st.write(f"평균 출동거리: {ambulances['init_distance'].mean():.1f} km")

    with c4:
        st.markdown("**🚁 UAV**")
        if isinstance(uavs, pd.DataFrame):
            st.write(f"대수: {len(uavs)}")

    with c5:
        st.markdown("**🧑‍⚕️ 환자 비율**")
        r = fixed_params["ratio_dict"]
        st.write(f"Red {r['Red']*100:.0f}%  Yellow {r['Yellow']*100:.0f}%")
        st.write(f"Green {r['Green']*100:.0f}%  Black {r['Black']*100:.0f}%")

def render_tab(selected_location, latitude, longitude, scenario_data):
    st.subheader(f"🗺️ {selected_location} 재난 대응 자원 분석")

    col_map, col_summary = st.columns([1, 1], gap="large")
    with col_map:
        st.subheader("지도")
        excel_df = load_excel_hospital_data()

        m = folium.Map(location=[latitude, longitude], zoom_start=11)
        folium.Marker([latitude, longitude],
                      popup=f"재난 발생지: {selected_location}",
                      tooltip=f"좌표: ({latitude}, {longitude})",
                      icon=folium.Icon(color="red", icon="warning-sign", prefix="fa")).add_to(m)

        hospitals_df = scenario_data.get("hospitals")
        distances_df = scenario_data.get("distances", pd.DataFrame())

        if isinstance(hospitals_df, pd.DataFrame) and excel_df is not None:
            # 이름 매칭 및 마커 표시
            for i, row in hospitals_df.iterrows():
                name = row["요양기관명"]
                match = excel_df[excel_df["요양기관명"] == name]
                if match.empty:
                    continue
                lat, lon = match.iloc[0]["y좌표"], match.iloc[0]["x좌표"]
                tier = row["종별코드"]
                color = "blue" if tier == 1 else "green"
                tier_name = "상급종합병원" if tier == 1 else "일반병원"
                dist_html = ""
                if i < len(distances_df) and "distance" in distances_df.columns:
                    d = distances_df.iloc[i]["distance"]
                    dist_html = f"<br>거리: {d:.1f}km"
                folium.Marker([lat, lon],
                              popup=f"<b>{name}</b><br>{tier_name}<br>병상: {row['병상수']}{dist_html}",
                              tooltip=f"{name} ({tier_name})",
                              icon=folium.Icon(color=color, icon="plus", prefix="fa")).add_to(m)
        st_folium(m, height=500)

    with col_summary:
        from config import FIXED_PARAMS
        st.subheader("현황 표")
        _render_summary(scenario_data, FIXED_PARAMS)
