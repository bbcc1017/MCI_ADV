# app.py

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import BeautifyIcon

# 기존 모듈들을 가져옵니다.
import config
from data_processor import process_hospital_data, process_ems_data

# --- 데이터 로딩 함수 (Streamlit 캐시 기능으로 속도 향상) ---

@st.cache_data
def load_processed_data():
    """분석이 완료된 병원 및 119 안전센터 데이터를 불러옵니다."""
    df_hospitals = process_hospital_data()
    df_ems = process_ems_data()
    return df_hospitals, df_ems

@st.cache_data
def load_all_hospital_data():
    """검색 기능을 위해 전체 병원 목록 원본 데이터를 불러옵니다."""
    df = pd.read_excel(config.HOSPITAL_DATA_PATH)
    # 검색에 필요한 컬럼만 선택
    return df[['요양기관명', 'x좌표', 'y좌표']]

# --- 지도 생성 함수 ---

def create_map_with_markers(df_hospitals, df_ems, searched_hospital_info=None):
    """지도에 사고지점, 병원, 119 안전센터 및 검색된 병원 마커를 추가합니다."""
    
    # 지도 중심 및 확대 수준 설정
    map_center = [config.ACCIDENT_LOCATION['latitude'], config.ACCIDENT_LOCATION['longitude']]
    zoom_level = 11
    
    # 특정 병원이 검색된 경우, 해당 병원을 중심으로 지도 표시
    if searched_hospital_info is not None:
        map_center = [searched_hospital_info["y좌표"], searched_hospital_info["x좌표"]]
        zoom_level = 15

    # 기본 지도 생성 (배경 지도 옵션 조정)
    m = folium.Map(location=map_center, zoom_start=zoom_level, tiles=None)

    # 배경 지도를 Layer Control에는 추가하지 않고 지도에만 추가
    folium.TileLayer(
        tiles='OpenStreetMap',
        attr=' ',  # 저작권 문구를 공백으로 처리하여 숨김
        name='OpenStreetMap'
    ).add_to(m)

    # 피처 그룹 생성
    feature_groups = {
        "상급종합병원": folium.FeatureGroup(name="상급종합병원", show=True).add_to(m),
        "종합병원": folium.FeatureGroup(name="종합병원", show=True).add_to(m),
        "기타병원": folium.FeatureGroup(name="기타병원", show=True).add_to(m),
        "119 안전센터": folium.FeatureGroup(name="119 안전센터", show=True).add_to(m),
    }

    # 사고 지점 마커
    folium.Marker(
        [config.ACCIDENT_LOCATION['latitude'], config.ACCIDENT_LOCATION['longitude']],
        tooltip="사고지점",
        popup=f"<b>재난유형:</b> {config.DISASTER_TYPE}<br>"
              f"<b>긴급환자:</b> {config.TOTAL_URGENT_PATIENTS}명<br>"
              f"<b>응급환자:</b> {config.TOTAL_EMERGENT_PATIENTS}명",
        icon=BeautifyIcon(icon_shape="marker", number="!", border_color="#FF4C4C",
                          text_color="#FFFFFF", background_color="#FF4C4C", pulse=True)
    ).add_to(m)

    # 최종 선정된 병원 마커 및 경로
    for _, r in df_hospitals.iterrows():
        popup_html = f"<b>{r['요양기관명']}</b><br>이송시간: {r['이송시간(분)']:.1f}분"
        
        if r["종별코드"] == 1: group, color = feature_groups["상급종합병원"], "red"
        elif r["종별코드"] == 11: group, color = feature_groups["종합병원"], "green"
        else: group, color = feature_groups["기타병원"], "blue"

        if r["경로좌표"]:
            folium.PolyLine([(lat, lon) for lon, lat in r["경로좌표"]],
                            color="blue", weight=5, opacity=0.8).add_to(group)
        
        folium.Marker([r["y좌표"], r["x좌표"]], tooltip=r['요양기관명'],
                      popup=popup_html, icon=folium.Icon(color=color, icon="plus", prefix="fa")
        ).add_to(group)

    # 119 안전센터 마커
    for _, r in df_ems.iterrows():
        folium.Marker([r["위도"], r["경도"]], tooltip=f"{r['센터']} ({r['수량']}대)",
                      popup=f"<b>{r['센터']}</b><br>구급차: {r['수량']}대",
                      icon=folium.Icon(color="orange", icon="ambulance", prefix="fa")
        ).add_to(feature_groups["119 안전센터"])

    # 검색된 병원이 최종 목록에 없는 경우, 특별 마커 추가
    if searched_hospital_info is not None:
        name = searched_hospital_info['요양기관명']
        if name not in df_hospitals['요양기관명'].values:
            folium.Marker(
                [searched_hospital_info["y좌표"], searched_hospital_info["x좌표"]],
                tooltip=name, popup=f"<b>{name}</b><br>(선정되지 않은 병원)",
                icon=folium.Icon(color="purple", icon="search", prefix="fa")
            ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m

# --- Streamlit 앱 메인 함수 ---
# --- Streamlit 앱 메인 함수 ---
def main():
    st.set_page_config(page_title="IITP 재난 대응 시스템", layout="wide")
    st.title("IITP 재난 대응 통합 지도")

    # 데이터 로딩
    df_hospitals, df_ems = load_processed_data()
    df_all_hospitals = load_all_hospital_data()

    # --- 사이드바 (텍스트 입력으로 병원 검색) ---
    st.sidebar.header("병원 검색")

    # 1. 텍스트 입력창 생성
    searched_name = st.sidebar.text_input(
        "병원 이름으로 검색", 
        placeholder="예: 서울대학교병원"
    )

    selected_hospital_name = None

    # 2. 검색어가 입력되면, 일치하는 병원 목록을 보여줌
    if searched_name:
        matches = df_all_hospitals[
            df_all_hospitals['요양기관명'].str.contains(searched_name, na=False)
        ]

        if not matches.empty:
            # 검색 결과에서 하나를 선택할 수 있도록 라디오 버튼 생성
            selected_hospital_name = st.sidebar.radio(
                "검색 결과:",
                options=matches['요양기관명'].tolist()
            )
        else:
            st.sidebar.write("검색 결과가 없습니다.")
    else:
        # 검색어가 없을 때 기본 안내 문구
        st.sidebar.info("병원 이름을 입력하여 검색하세요.")


    # --- 지도 생성 ---
    searched_hospital_info = None
    # 라디오 버튼에서 병원이 선택된 경우, 해당 병원의 좌표 정보를 찾음
    if selected_hospital_name:
        searched_hospital_info = df_all_hospitals[
            df_all_hospitals['요양기관명'] == selected_hospital_name
        ].iloc[0]

    final_map = create_map_with_markers(df_hospitals, df_ems, searched_hospital_info)
    st_folium(final_map, width='100%', height=600, returned_objects=[])

    # --- 최종 선정 병원 목록 (기존과 동일) ---
    st.header("최종 선정 병원 목록")
    df_advanced = df_hospitals[df_hospitals['종별코드'] == 1]
    df_general = df_hospitals[df_hospitals['종별코드'] == 11]
    df_other = df_hospitals[~df_hospitals['종별코드'].isin([1, 11])]

    hospital_groups = {
        "상급종합병원": df_advanced,
        "종합병원": df_general,
        "기타병원": df_other
    }

    for group_name, group_df in hospital_groups.items():
        if not group_df.empty:
            with st.expander(f"{group_name} ({len(group_df)}곳)"):
                st.write(f"총 {len(group_df)}개의 병원이 선정되었습니다.")
                for name in group_df['요양기관명']:
                    st.markdown(f"- {name}")
if __name__ == "__main__":
    main()