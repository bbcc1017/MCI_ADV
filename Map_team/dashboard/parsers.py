# parsers.py
import os, glob
from datetime import datetime
import streamlit as st
from paths import RESULTS_PATH, EXPERIMENT_LOGS_PATH

def load_simulation_results(coord_str: str):
    folder = os.path.join(RESULTS_PATH, coord_str)
    if not os.path.exists(folder):
        return None
    files = glob.glob(os.path.join(folder, "results_*.txt"))
    if not files:
        return None
    latest = max(files, key=os.path.getctime)

    try:
        results = {
            "rules": [], "survival_rates": [], "response_times": [], "pdr_rates": [],
            "file_path": latest, "timestamp": datetime.fromtimestamp(os.path.getctime(latest)),
        }
        current = None
        with open(latest, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s: 
                    continue
                if "outcomes_rew" in s or "생존율" in s: current = "survival"
                elif "outcomes_time" in s or "시간" in s: current = "time"
                elif "outcomes_pdr" in s or "PDR" in s: current = "pdr"
                elif s.startswith(("START", "ReSTART")):
                    parts = s.split()
                    if len(parts) >= 2:
                        rule = parts[0]
                        vals = [v for v in parts[1:] if v.replace(".","").replace("-","").isdigit()]
                        if not vals: 
                            continue
                        val = float(vals[0])
                        if current == "survival":
                            results["rules"].append(rule)
                            results["survival_rates"].append(val)
                        elif current == "time":
                            results["response_times"].append(val)
                        elif current == "pdr":
                            results["pdr_rates"].append(val)
        return results if results["rules"] else None
    except Exception as e:
        st.error(f"결과 파일 파싱 오류: {e}")
        return None

def load_experiment_logs(coord_str: str):
    if not os.path.exists(EXPERIMENT_LOGS_PATH):
        return None
    files = glob.glob(os.path.join(EXPERIMENT_LOGS_PATH, f"*{coord_str}*.log"))
    if not files:
        return None
    latest = max(files, key=os.path.getctime)
    try:
        with open(latest, "r", encoding="utf-8") as f:
            content = f.read()
        return {
            "content": content, "file_path": latest,
            "timestamp": datetime.fromtimestamp(os.path.getctime(latest)),
        }
    except Exception as e:
        st.error(f"로그 파일 읽기 오류: {e}")
        return None
