import pandas as pd
import time
from utils import haversine, get_naver_route_info
import config

def process_hospital_data():
    df = pd.read_excel(config.HOSPITAL_DATA_PATH, engine="openpyxl")
    total_required_patients = config.TOTAL_URGENT_PATIENTS + config.TOTAL_EMERGENT_PATIENTS

    # 가용 병상수 추정 함수
    def estimate_available_beds(row):
        util = config.AVG_UTILIZATION.get(row["종별코드"], config.AVG_UTILIZATION["etc"])
        return int(row["응급실병상수"] * (1 - util))

    # 데이터 전처리 및 열 추가
    df["가용병상수"] = df.apply(estimate_available_beds, axis=1)
    df["수용가능환자수"] = df["가용병상수"]
    df["하버사인거리"] = df.apply(
        lambda r: haversine(config.ACCIDENT_LOCATION['latitude'], config.ACCIDENT_LOCATION['longitude'], r["y좌표"], r["x좌표"]),
        axis=1
    )
    df = df.sort_values(by="하버사인거리").reset_index(drop=True)

    # 1/2차 필터: 거리 + 여유율 기반 후보군 선정
    candidate, cap_tot, cap_urg = [], 0, 0
    for _, r in df.iterrows():
        candidate.append(r.copy())
        cap_tot += r["수용가능환자수"]
        if r["종별코드"] == 1:
            cap_urg += r["수용가능환자수"]
        if cap_tot >= total_required_patients * config.CANDIDATE_BUFFER_RATIO and cap_urg >= config.TOTAL_URGENT_PATIENTS:
            break
    df_candidate = pd.DataFrame(candidate)

    # 3차 필터: 가용병상수 우선 최종 후보 선정
    final_list, cap_tot, cap_urg = [], 0, 0
    for _, r in df_candidate.sort_values(by="가용병상수", ascending=False).iterrows():
        final_list.append(r.copy())
        cap_tot += r["수용가능환자수"]
        if r["종별코드"] == 1:
            cap_urg += r["수용가능환자수"]
        if cap_tot >= total_required_patients and cap_urg >= config.TOTAL_URGENT_PATIENTS:
            break
    df_candidate_final = pd.DataFrame(final_list)

    # 경로 및 정체 정보 계산
    processed = []
    for _, r in df_candidate_final.iterrows():
        summ, sections, path = get_naver_route_info(
            config.ACCIDENT_LOCATION['longitude'], config.ACCIDENT_LOCATION['latitude'],
            r["x좌표"], r["y좌표"], config.NAVER_CLIENT_ID, config.NAVER_CLIENT_SECRET
        )
        time.sleep(0.1)  # API 호출 사이의 간격
        if summ:
            info = r.copy()
            info["거리(km)"] = summ["distance"] / 1000
            info["이송시간(분)"] = summ["duration"] / 60000
            info["정체구간"] = sections
            info["정체점수"] = sum(sec["distance"] * sec["congestion"] for sec in sections)
            info["경로좌표"] = path
            processed.append(info)

    return pd.DataFrame(processed).sort_values(by="이송시간(분)").reset_index(drop=True)


def process_ems_data():
    df = pd.read_excel(config.EMS_DATA_PATH)
    df["거리(km)"] = df.apply(
        lambda r: haversine(config.ACCIDENT_LOCATION['latitude'], config.ACCIDENT_LOCATION['longitude'], r["위도"], r["경도"]),
        axis=1
    )
    df_sorted = df.sort_values(by="거리(km)").reset_index(drop=True)

    ems_sel, total_amb = [], 0
    for _, r in df_sorted.iterrows():
        ems_sel.append(r)
        total_amb += r["수량"]
        if total_amb >= config.TOTAL_URGENT_PATIENTS:
            break
    return pd.DataFrame(ems_sel)