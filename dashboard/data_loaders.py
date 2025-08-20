# data_loaders.py
import os
import pandas as pd
import streamlit as st
from paths import SCENARIOS_PATH, EXCEL_DATA_PATH

@st.cache_data
def load_excel_hospital_data():
    try:
        if os.path.exists(EXCEL_DATA_PATH):
            return pd.read_excel(EXCEL_DATA_PATH, engine="openpyxl")
        st.warning(f"엑셀 파일을 찾을 수 없습니다: {EXCEL_DATA_PATH}")
    except Exception as e:
        st.error(f"엑셀 파일 로드 오류: {e}")
    return None

def get_location_name(lat: float, lon: float) -> str:
    mapping = {
        (37.530653, 126.976079): "용산 대통령실",
        (37.465833, 126.443333): "인천국제공항",
        (35.147568, 129.130187): "부산 광안대교",
        (36.962409, 127.031143): "평택 주한미군 비행장",
        (36.369885, 128.597904): "의성 산불지점",
        (36.504827, 127.265393): "정부세종청사",
    }
    for (r_lat, r_lon), name in mapping.items():
        if abs(lat - r_lat) < 0.001 and abs(lon - r_lon) < 0.001:
            return name
    return f"기타지역 ({lat:.3f}, {lon:.3f})"

@st.cache_data
def get_available_scenarios():
    scenarios = {}
    if os.path.exists(SCENARIOS_PATH):
        for folder in os.listdir(SCENARIOS_PATH):
            if folder.startswith("(") and folder.endswith(")"):
                coord_str = folder
                try:
                    lat, lon = map(float, coord_str.strip("()").split(","))
                    scenarios[get_location_name(lat, lon)] = {
                        "folder": folder,
                        "lat": lat, "lon": lon, "coord_str": coord_str,
                    }
                except Exception:
                    continue
    return scenarios

@st.cache_data
def load_scenario_data(scenario_folder: str):
    """시나리오 폴더 내 csv들을 읽어 dict로 반환"""
    p = os.path.join(SCENARIOS_PATH, scenario_folder)
    data = {}
    try:
        f = os.path.join
        if os.path.exists(f(p, "hospital_info_road.csv")):
            data["hospitals"] = pd.read_csv(f(p, "hospital_info_road.csv"), encoding="utf-8-sig")
        if os.path.exists(f(p, "amb_info_road.csv")):
            data["ambulances"] = pd.read_csv(f(p, "amb_info_road.csv"), encoding="utf-8-sig")
        if os.path.exists(f(p, "uav_info.csv")):
            data["uavs"] = pd.read_csv(f(p, "uav_info.csv"), encoding="utf-8-sig")
        if os.path.exists(f(p, "patient_info.csv")):
            data["patients"] = pd.read_csv(f(p, "patient_info.csv"), encoding="utf-8-sig")
        if os.path.exists(f(p, "distance_Hos2Site_road.csv")):
            data["distances"] = pd.read_csv(f(p, "distance_Hos2Site_road.csv"), encoding="utf-8-sig")
    except Exception as e:
        st.error(f"데이터 로드 중 오류: {e}")
    return data
