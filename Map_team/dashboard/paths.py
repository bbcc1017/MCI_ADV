import os

# 프로젝트 루트의 다른 경로와 맞춰
BASE_PATH = r"C:\Users\kimyo\Downloads\MCI_UAM_v250703\MCI_UAM_v250703"

# dashboard 하위에서 실행하므로 아래 폴더는 BASE_PATH 기준
SCENARIOS_PATH = os.path.join(BASE_PATH, "scenarios")
RESULTS_PATH = os.path.join(BASE_PATH, "results")
EXPERIMENT_LOGS_PATH = os.path.join(BASE_PATH, "experiment_logs")
EXCEL_DATA_PATH = os.path.join(BASE_PATH, "scenarios", "엑셀 결합 데이터.xlsx")
