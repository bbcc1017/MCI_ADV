# map_creator.py

import folium
from folium.plugins import BeautifyIcon
import config

def create_disaster_map(df_hospitals, df_ems):
    m = folium.Map(location=[config.ACCIDENT_LOCATION['latitude'], config.ACCIDENT_LOCATION['longitude']], zoom_start=11)

    # 피처 그룹 생성
    feature_groups = {
        "상급종합병원": folium.FeatureGroup(name="상급종합병원", show=True).add_to(m),
        "종합병원": folium.FeatureGroup(name="종합병원", show=True).add_to(m),
        "기타병원": folium.FeatureGroup(name="기타병원", show=True).add_to(m),
        "119 안전센터": folium.FeatureGroup(name="119 안전센터", show=True).add_to(m),
    }

    # 사고 지점 마커
    accident_popup = folium.Popup(f"""
        <div style='font-size:14px; line-height:1.6; padding:6px;'>
          <b style="font-size:15px;">사고지점</b><br>
          <b>재난 유형:</b> {config.DISASTER_TYPE}<br>
          <b>긴급환자:</b> {config.TOTAL_URGENT_PATIENTS} 명<br>
          <b>응급환자:</b> {config.TOTAL_EMERGENT_PATIENTS} 명
        </div>""", max_width=300)
    folium.Marker(
        [config.ACCIDENT_LOCATION['latitude'], config.ACCIDENT_LOCATION['longitude']],
        tooltip="사고지점", popup=accident_popup,
        icon=BeautifyIcon(icon_shape="marker", number="!", border_color="#FF4C4C", border_width=3,
                          text_color="#FFFFFF", background_color="#FF4C4C", pulse=True)
    ).add_to(m)

    # 병원 마커 및 경로
    for idx, r in df_hospitals.iterrows():
        # 팝업 HTML 생성
        cong_html = "".join([
            f"{sec['name']} ({sec['distance']/1000:.1f}km, {sec['speed']}km/h) - "
            f"{['원활','서행','정체','매우 정체'][sec['congestion']]}<br>"
            for sec in r["정체구간"]
        ])
        popup_html = f"""
        <div style='font-size:14px; line-height:1.6; padding:6px;'>
          <b style="font-size:15px;">{r['요양기관명']}</b><br>
          <b>거리:</b> {r['거리(km)']:.2f} km<br>
          <b>시간:</b> {r['이송시간(분)']:.1f} 분<br>
          <b>가용 응급실 병상수:</b> {r['가용병상수']} 개<br>
          <b>정체 정보</b><br>{cong_html if cong_html else '정보 없음'}
        </div>"""
        
        # 그룹 및 색상 선택
        if r["종별코드"] == 1:
            group, color = feature_groups["상급종합병원"], "red"
        elif r["종별코드"] == 11:
            group, color = feature_groups["종합병원"], "green"
        else:
            group, color = feature_groups["기타병원"], "blue"

        # 경로 그리기
        if r["경로좌표"]:
            folium.PolyLine([(lat, lon) for lon, lat in r["경로좌표"]],
                            color="blue", weight=5, opacity=0.8).add_to(group)
        
        # 마커 추가
        folium.Marker(
            [r["y좌표"], r["x좌표"]],
            tooltip=f"{idx+1}. {r['요양기관명']}",
            popup=folium.Popup(popup_html, max_width=400),
            icon=folium.Icon(color=color, icon="plus", prefix="fa")
        ).add_to(group)

    # 119 안전센터 마커
    for _, r in df_ems.iterrows():
        popup_html = f"""
        <div style='font-size:14px; line-height:1.6; padding:6px;'>
          <b>{r['센터']}</b><br>
          <b>구급차 수:</b> {r['수량']}대<br>
          <b>종류:</b> {r['분류명']}<br>
          <b>거리:</b> {r['거리(km)']:.2f} km
        </div>"""
        folium.Marker(
            [r["위도"], r["경도"]],
            tooltip=f"{r['센터']} ({r['수량']}대)",
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color="orange", icon="ambulance", prefix="fa")
        ).add_to(feature_groups["119 안전센터"])

    folium.LayerControl(position="topright", collapsed=False).add_to(m)
    m.save(config.OUTPUT_MAP_PATH)
    print("통합 지도 저장 완료 :", config.OUTPUT_MAP_PATH)