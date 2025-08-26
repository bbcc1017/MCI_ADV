# ui/tabs_settings.py
import os, pandas as pd, streamlit as st
from datetime import datetime
from paths import SCENARIOS_PATH, RESULTS_PATH

def render_tab(selected_location, scenario_folder, coord_str, scenario_data):
    st.subheader("⚙️ 설정 관리 및 파일 상태")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**📁 현재 시나리오 파일 상태**")
        p = os.path.join(SCENARIOS_PATH, scenario_folder)
        req = [
            "hospital_info_road.csv","hospital_info_euc.csv",
            "amb_info_road.csv","amb_info_euc.csv",
            "uav_info.csv","patient_info.csv",
            "distance_Hos2Site_road.csv","distance_Hos2Site_euc.csv",
            "distance_Hos2Hos_road.csv","distance_Hos2Hos_euc.csv",
            f"config_{coord_str}.yaml",
        ]
        rows = []
        for f in req:
            fp = os.path.join(p, f)
            if os.path.exists(fp):
                rows.append({"파일명":f,"상태":"✅ 존재","크기":f"{os.path.getsize(fp):,} bytes",
                             "수정일시": datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M")})
            else:
                rows.append({"파일명":f,"상태":"❌ 없음","크기":"-","수정일시":"-"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    with c2:
        st.markdown("**📊 시뮬레이션 결과 관리**")
        rf = os.path.join(RESULTS_PATH, coord_str)
        if os.path.exists(rf):
            files = [f for f in os.listdir(rf) if f.endswith(".txt")]
            st.metric("결과 파일 수", len(files))
            if files:
                latest = max([os.path.join(rf, f) for f in files], key=os.path.getctime)
                st.info(f"📅 최근 실행: {datetime.fromtimestamp(os.path.getmtime(latest)).strftime('%Y-%m-%d %H:%M:%S')}")
                st.markdown("**📁 최근 결과 5개:**")
                for f in sorted(files, reverse=True)[:5]:
                    fp = os.path.join(rf, f)
                    st.text(f"• {f} ({os.path.getsize(fp):,} bytes, {datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%m-%d %H:%M')})")
        else:
            st.info("📁 결과 폴더가 생성되지 않았습니다.")
