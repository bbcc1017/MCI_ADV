# ---------------- 사고지점 및 설정 ----------------
ACCIDENT_LOCATION = {"longitude": 129.130187, "latitude": 35.147568}
TOTAL_URGENT_PATIENTS = 15
TOTAL_EMERGENT_PATIENTS = 25
DISASTER_TYPE = "지진"
CANDIDATE_BUFFER_RATIO = 3.0

# ---------------- 네이버 API 키 ----------------
NAVER_CLIENT_ID = "l9kwfvdlns"      
NAVER_CLIENT_SECRET = "mDilsmtzJYJ7BWqsfu25tahVvxtqsPRWDbTLgiPa"

# ---------------- 파일 경로 ----------------
HOSPITAL_DATA_PATH = r"data/엑셀 결합 데이터.xlsx"
EMS_DATA_PATH = r"data/119안전센터_좌표추가.xlsx"
OUTPUT_MAP_PATH = r"재난통합지도.html"

# ---------------- 병원 가용률 설정 ----------------
AVG_UTILIZATION = {
    1: 0.90,     # 상급종합병원
    11: 0.75,    # 종합병원
    "etc": 0.60, # 그 외 병원
}