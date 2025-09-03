# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import yaml
import argparse
import pandas as pd
import numpy as np
import requests
from haversine import haversine
from random_coordinate_generator import CoordinateGenerator
# [ADD] ──────────────────────────────────────────────────────────────
import re
from datetime import timezone, timedelta, datetime
from typing import Optional

KST = timezone(timedelta(hours=9))

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def slugify(name: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^\w\-\s]", "", str(name))
    s = re.sub(r"\s+", "_", s).strip("_")
    return (s[:maxlen] or "noname")

def save_route_json(meta: dict, payload: Optional[dict], out_path: str):
    ensure_dir(os.path.dirname(out_path))
    data = {"meta": meta, "payload": {"naver_response": payload} if payload else None}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
# [ADD END] ─────────────────────────────────────────────────────────


def parse_util_map(text: str):
    """
    "1:0.90,11:0.75,etc:0.60" -> {1:0.9, 11:0.75, "etc":0.6}
    """
    if not text:
        return None
    m = {}
    for part in str(text).split(","):
        if not part.strip():
            continue
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k = k.strip()
        v = v.strip()
        try:
            val = float(v)
        except Exception:
            continue
        if k.lower() == "etc":
            m["etc"] = val
        else:
            try:
                m[int(k)] = val
            except Exception:
                pass
    return m if m else None

class ScenarioGenerator:
    """동적 파라미터 기반 시나리오 생성 클래스 (크로스 환경 호환)"""
    
    def __init__(self, base_path, experiment_id=None, client_id=None, client_secret=None):
        # 프로젝트 경로 절대화
        self.base_path = os.path.abspath(base_path)
        self.experiment_id = experiment_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # API 키 설정
        self.client_id = client_id or os.environ.get('NAVER_CLIENT_ID')
        self.client_secret = client_secret or os.environ.get('NAVER_CLIENT_SECRET')
        
        # 데이터 파일 경로들 (절대경로로 설정)
        self.scenarios_path = os.path.join(self.base_path, "scenarios")
        self.fire_data_path = os.path.join(self.scenarios_path, "안전센터와 소방서.csv")
        self.hospital_data_path = os.path.join(self.scenarios_path, "엑셀 결합 데이터.xlsx")
        self.shp_path = os.path.join(self.scenarios_path, "ctprvn.shp")
        
        # 파일 존재성 검증
        self._validate_data_files()
        
        # 좌표 생성기 초기화
        self.coord_generator = CoordinateGenerator(
            client_id=self.client_id,
            client_secret=self.client_secret,
            shp_path=self.shp_path
        )
        
        # Patient 정보 (하드코딩)
        self.patient_config = {
            "ratio": {"Red": 0.1, "Yellow": 0.3, "Green": 0.5, "Black": 0.1},
            "rescue_param": {"Red": (6, 5), "Yellow": (2, 13), "Green": (1, 22), "Black": (0, 0)},
            "treat_tier1": {"Red": True, "Yellow": True, "Green": True, "Black": True},
            "treat_tier2": {"Red": False, "Yellow": True, "Green": True, "Black": True},
            "treat_tier1_mean": {"Red": 40, "Yellow": 20, "Green": 10, "Black": 0},
            "treat_tier2_mean": {"Red": 60, "Yellow": 30, "Green": 15, "Black": 0}
        }
        
        # 후보군 확장 배수 (AMB road distance 호출 수 완화)
        self.multiplier = 1.5

        # --- ENV 주입(PS에서 전달) ---
        # util_by_tier: 예) "1:0.656,11:0.461,etc:0.461"
        env_util = parse_util_map(os.environ.get("MCI_UTIL_BY_TIER", ""))
        self.util_by_tier = env_util or {1: 0.656, 11: 0.461, "etc": 0.461}

        # queue_policy: "0" | "capa/2" | "0.5" 등
        # self.queue_policy = os.environ.get("MCI_QUEUE_POLICY", "0")

        # buffer_ratio: float
        try:
            self.buffer_ratio = float(os.environ.get("MCI_BUFFER_RATIO", "1.5"))
        except Exception:
            self.buffer_ratio = 1.5
        
        # (추가) max_send_coeff 기본 입력경로: ENV → 기본값
        self.max_send_coeff_text = os.environ.get("MCI_MAX_SEND_COEFF", "1,1")
        
        print(f"📁 프로젝트 경로: {self.base_path}")
        print(f"🆔 실험 ID: {self.experiment_id}")
        print(f"buffer_ratio={self.buffer_ratio}")

    def _validate_data_files(self):
        """필수 데이터 파일들의 존재성 검증"""
        required_files = [
            (self.fire_data_path, "소방서 데이터"),
            (self.hospital_data_path, "병원 데이터"),
            (self.shp_path, "시도 경계 SHP 파일")
        ]
        missing_files = []
        for file_path, description in required_files:
            if not os.path.exists(file_path):
                missing_files.append(f"{description}: {file_path}")
        if missing_files:
            print("❌ 다음 필수 파일들이 없습니다:")
            for missing in missing_files:
                print(f"   • {missing}")
            raise FileNotFoundError("필수 데이터 파일들을 확인해주세요.")
        print("✅ 모든 필수 데이터 파일 확인 완료")

    def get_road_distance(self, start, end, max_retries=3, save_json_dir=None, route_type=None, source_index=None, name=None, start_label="start", goal_label="goal"):
        """도로 거리 계산 (재시도 로직 포함)"""
        if not self.client_id or not self.client_secret:
            # API 키 없으면 유클리드로 대체
            return haversine(start, end)
        
        url = "https://maps.apigw.ntruss.com/map-direction/v1/driving"
        headers = {
            "X-NCP-APIGW-API-KEY-ID": self.client_id,
            "X-NCP-APIGW-API-KEY": self.client_secret
        }
        params = {
            "start": f"{start[1]},{start[0]}",
            "goal": f"{end[1]},{end[0]}",
            "option": "trafast",
            "car_type": 0,
            "fuel_type": "DIESEL",
            "summary": "true"               # [ADD]
        }

        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, params=params, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    # --- 기존 반환용 거리(km)
                    summary = data["route"]["trafast"][0]["summary"]
                    distance_km = summary["distance"] / 1000.0

                    # --- [ADD] 저장 메타
                    if save_json_dir:
                        now = datetime.now(KST).isoformat()
                        meta = {
                            "route_type": route_type,
                            "source_index": source_index,
                            "name": name,
                            # 좌표는 경량/호환 목적상 [lon,lat]로 저장
                            start_label: [start[1], start[0]],
                            goal_label:  [end[1],   end[0]],
                            "option": params.get("option"),
                            "car_type": params.get("car_type"),
                            "fuel_type": params.get("fuel_type"),
                            "saved_at": now,
                            # 요약 필드
                            "distance_km": distance_km,
                            "duration_sec": summary.get("duration"),
                            "tollFare": summary.get("tollFare"),
                            "taxiFare": summary.get("taxiFare"),
                            "fuelPrice": summary.get("fuelPrice"),
                            # 참고: 현재 방향 (site→hospital 여부)도 명시 가능
                            "direction_note": f"{start_label}->{goal_label}"
                        }
                        fname = f"{(source_index if source_index is not None else 0):03d}_{slugify(name)}.json"
                        out_path = os.path.join(save_json_dir, fname)
                        save_route_json(meta, data, out_path)
                        print(f"  📦 [{route_type}] idx={source_index:03d} {name} → saved: {out_path}")
                    return distance_km
                elif response.status_code == 401:
                    time.sleep(1)
                elif response.status_code == 429:
                    time.sleep(3)
                else:
                    break
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(2)
        
        # API 실패 시 유클리드 거리로 대체
        return haversine(start, end)

    def generate_coordinate_for_scenario(self, mode="korea_random", sido_name=None):
        """
        시나리오용 좌표 생성 (JSON 형태로 상세 정보 출력)
        Args:
            mode: "korea_random", "sido", "manual"
            sido_name: 시도명 (mode="sido"일 때 필요)
        Returns:
            (latitude, longitude) 또는 None
        """
        try:
            if mode == "manual":
                return None  # 수동은 외부에서 값 제공
            
            result = self.coord_generator.generate_valid_coordinate(mode, sido_name)
            if result:
                lat, lon, addr_info = result
                output_info = {
                    "latitude": lat,
                    "longitude": lon,
                    "full_address": addr_info.get("full_address", ""),
                    "road_address": addr_info.get("road_address", ""),
                    "area1": addr_info.get("area1", ""),
                    "area2": addr_info.get("area2", ""),
                    "area3": addr_info.get("area3", ""),
                    "area4": addr_info.get("area4", ""),
                    "is_valid": addr_info.get("is_valid", False)
                }
                print(f"COORDINATE_INFO:{json.dumps(output_info, ensure_ascii=False)}")
                print(f"  📍 좌표 생성: ({lat}, {lon}) - {addr_info.get('area1','')} {addr_info.get('area2','')}")
                return lat, lon
            else:
                print("  ❌ 유효한 좌표 생성 실패")
                return None
        except Exception as e:
            print(f"  💥 좌표 생성 오류: {e}")
            return None

    def make_amb_info(self, latitude, longitude, incident_size, save_folder):
        """구급차 정보 생성"""
        print(f"  🚑 구급차 정보 생성 중...")
        try:
            df = pd.read_csv(self.fire_data_path, encoding="cp949")
        except Exception as e:
            print(f"❌ 소방서 데이터 로드 실패: {e}")
            return
        
        coords = list(zip(df["y좌표"], df["x좌표"]))
        euc_distances = [haversine(coord, (latitude, longitude)) for coord in coords]
        df["euclidean_distance"] = euc_distances

        # EUC 저장
        df_sorted_euc = df.sort_values("euclidean_distance").head(incident_size).copy()
        df_sorted_euc = df_sorted_euc.rename(columns={
            "euclidean_distance": "init_distance",
            "기관명": "안전센터/소방서이름"
        })
        df_sorted_euc = df_sorted_euc.reset_index(drop=True)
        df_sorted_euc = df_sorted_euc[["init_distance", "안전센터/소방서이름"]]
        euc_save_path = os.path.join(save_folder, "amb_info_euc.csv")
        df_sorted_euc.to_csv(euc_save_path, index=True, index_label="Index", encoding="utf-8-sig")
        
        # [ADD] center2site 저장 폴더
        routes_dir = os.path.join(save_folder, "routes", "center2site")
        ensure_dir(routes_dir)

        # 후보군 확장 및 도로 거리 계산
        df_candidates = df.sort_values("euclidean_distance").head(int(incident_size * self.multiplier)).copy()
        road_distances = []
        for j, (_, row) in enumerate(df_candidates.iterrows()):
            coord = (row["y좌표"], row["x좌표"])  # (lat,lon) of center
            dist = self.get_road_distance(
                start=coord, end=(latitude, longitude),           # center → site
                save_json_dir=routes_dir, route_type="center2site",
                source_index=j, name=row.get("기관명", f"center_{j}"),
                start_label="center", goal_label="site"
            )
            road_distances.append(dist)
            time.sleep(0.05)
        df_candidates["road_distance"] = road_distances

        # ROAD 저장
        df_sorted_road = df_candidates.sort_values("road_distance").head(incident_size).copy()
        df_sorted_road = df_sorted_road.rename(columns={
            "road_distance": "init_distance",
            "기관명": "안전센터/소방서이름"
        })
        df_sorted_road = df_sorted_road.reset_index(drop=True)
        df_sorted_road = df_sorted_road[["init_distance", "안전센터/소방서이름"]]
        road_save_path = os.path.join(save_folder, "amb_info_road.csv")
        df_sorted_road.to_csv(road_save_path, index=True, index_label="Index", encoding="utf-8-sig")
        
        print(f"  ✅ 구급차 정보 생성 완료")

    def make_hospital_info(self, latitude, longitude, incident_size, save_folder):
        """병원 정보 생성 (capa/큐 정책 + 상급 보장 강화 + 최소 집합)"""
        print(f"  🏥 병원 정보 생성 중...")

        # ---------- (0) 데이터 로드 ----------
        try:
            df_full = pd.read_excel(self.hospital_data_path, engine='openpyxl')
        except Exception as e:
            print(f"❌ 병원 데이터 로드 실패: {e}")
            return

        # 필요한 열만 사용 (이름 유지)
        cols_needed = ["요양기관명", "종별코드", "응급실병상수", "x좌표", "y좌표"]
        for c in cols_needed:
            if c not in df_full.columns:
                raise KeyError(f"필수 컬럼 누락: {c}")
        df = df_full[cols_needed].copy()

        # ---------- (1) 유클리드 거리 계산 ----------
        coords = list(zip(df["y좌표"], df["x좌표"]))  # (lat, lon)
        df["euclidean_distance"] = [haversine((lat, lon), (latitude, longitude)) for (lat, lon) in coords]

        # ---------- (2) 파라미터 ----------
        util_by_tier = getattr(self, "util_by_tier", {1: 0.656, 11: 0.461, "etc": 0.461})
        # queue_policy = str(getattr(self, "queue_policy", "0")).strip()
        try:
            buffer_ratio = float(getattr(self, "buffer_ratio", 1.5))
        except Exception:
            buffer_ratio = 1.5

        ratio = self.patient_config.get("ratio", {"Red":0.1,"Yellow":0.3,"Green":0.5,"Black":0.1})
        U = int(round(incident_size * float(ratio.get("Red", 0))))   # Red(긴급) 수
        N = int(incident_size)

        import math
        def _get_util(code):
            try:
                icode = int(code)
                return util_by_tier.get(icode, util_by_tier.get("etc", 0.461))
            except Exception:
                return util_by_tier.get("etc", 0.461)
        # ========== [수정 1] capa 계산 (기존과 동일) ==========    
        df["util"] = df["종별코드"].apply(_get_util)
        df["capa"] = (df["응급실병상수"] * (1 - df["util"])).apply(lambda x: int(max(0, math.floor(x))))
        
        # ========== [수정 2] '수술실 수' 계산 (새로운 a 컴포넌트) ==========
        conditions = [
            df['종별코드'] == 1,  # 상급종합병원
            df['종별코드'] == 11  # 종합병원
        ]
        values = [4, 3] # 상급종합병원: 4, 종합병원: 3
        df['operating_rooms'] = np.select(conditions, values, default=2)

        # =========== [수정 3] 새로운 '실효 수용력(eff)' 계산 (기존 queue_capa 계산은 삭제) ==========
        df["eff"] = df["operating_rooms"] + df["capa"] # a * 수술실수 + b * 병상수 (a=1, b=1로 가정)
        
        # def _queue_from_policy(capa):
        #     if queue_policy in ("0", "none", "None"):
        #         return 0
        #     if isinstance(queue_policy, str) and queue_policy.startswith("capa/"):
        #         try:
        #             denom = float(queue_policy.split("/", 1)[1])
        #             if denom > 0:
        #                 return int(max(0, math.floor(capa / denom)))
        #         except Exception:
        #             return 0
        #     try:
        #         frac = float(queue_policy)
        #         if 0 < frac <= 1:
        #             return int(max(0, math.floor(capa * frac)))
        #     except Exception:
        #         pass
        #     return 0

        # # capa(now) 계산 = 응급실병상수 × (1-util)
        # df["util"] = df["종별코드"].apply(_get_util)
        # df["capa"] = (df["응급실병상수"] * (1 - df["util"])).apply(lambda x: int(max(0, math.floor(x))))
        # df["queue_capa"] = df["capa"].apply(_queue_from_policy)
        # df["eff"] = df["capa"] + df["queue_capa"]
        df["is_tier1"] = (df["종별코드"].astype(str).astype(float).astype(int) == 1).astype(int)

        # ---------- (3) 전역 상급 용량 점검 (불가능 사전 감지) ----------
        total_tier1_capa_all = int(df.loc[df["is_tier1"]==1, "capa"].sum())
        total_capa_all = int(df["capa"].sum())
        if total_tier1_capa_all < U:
            print(f"  ⚠️ 전역 상급 용량 부족: Tier1_capa_all={total_tier1_capa_all} < U={U}. 최선 선택으로 진행(전원 실패 가능).")

        # ---------- (4) 후보군 확장(거리순) — 버퍼는 capa 기준, 상급 보장 조건 포함 ----------
        df_sorted = df.sort_values("euclidean_distance").reset_index(drop=True)
        sum_capa = 0
        sum_capa_tier1 = 0
        cand_idx = []
        for i, row in df_sorted.iterrows():
            cand_idx.append(i)
            c = int(row["eff"])
            sum_capa += c
            if row["is_tier1"] == 1:
                sum_capa_tier1 += c
            # 버퍼(총 capa) AND 상급 보장(긴급 커버) 동시 만족해야 stop
            if (sum_capa >= N * buffer_ratio) and (sum_capa_tier1 >= U):
                break

        if not cand_idx:
            cand_idx = list(range(len(df_sorted)))
        df_cand = df_sorted.loc[cand_idx].copy()

        # ---------- (5) 최소 집합 선택 — 상급 먼저 채우고, 이후 총 capa 채우기 ----------
        # 5-1) 상급(Tier1) 우선 선택 (capa 내림차순)
        sel_names = []
        acc_capa = 0
        acc_tier1 = 0

        tier1_cand = df_cand[df_cand["is_tier1"] == 1].sort_values("capa", ascending=False)
        for _, r in tier1_cand.iterrows():
            sel_names.append(r.name)
            acc_capa += int(r["capa"])
            acc_tier1 += int(r["capa"])
            if acc_tier1 >= U:
                break



        # 5-2) 나머지에서 총 capa를 N까지 채우기 (capa 내림차순)
        rest_cand = df_cand.drop(index=sel_names, errors="ignore").sort_values("capa", ascending=False)
        for _, r in rest_cand.iterrows():
            # 제안: 최종 리스트에도 여유를 남김
            tier1_keep = float(os.environ.get("MCI_TIER1_KEEP", "5"))  # 상급 여유
            total_keep = float(os.environ.get("MCI_TOTAL_KEEP", "5"))  # 전체 여유

            if (acc_tier1 >= U * tier1_keep) and (acc_capa >= N * total_keep):
                break

            sel_names.append(r.name)
            acc_capa += int(r["capa"])
            # (상급이면 함께 증가)
            if int(r["is_tier1"]) == 1:
                acc_tier1 += int(r["capa"])

        # 5-3) 여전히 조건 미충족이면 후보군을 전체로 확대해 한 번 더 시도
        if (acc_capa < N) or (acc_tier1 < U):
            # 전체 데이터에서 재시도 (최대한 충족)
            df_cand2 = df_sorted  # 전체
            sel_names = []
            acc_capa = 0
            acc_tier1 = 0
            tier1_all = df_cand2[df_cand2["is_tier1"] == 1].sort_values("capa", ascending=False)
            for _, r in tier1_all.iterrows():
                sel_names.append(r.name)
                acc_capa += int(r["capa"])
                acc_tier1 += int(r["capa"])
                if acc_tier1 >= U:
                    break
            rest_all = df_cand2.drop(index=sel_names, errors="ignore").sort_values("capa", ascending=False)
            for _, r in rest_all.iterrows():
                if (acc_capa >= N) and (acc_tier1 >= U):
                    break
                sel_names.append(r.name)
                acc_capa += int(r["capa"])
                if int(r["is_tier1"]) == 1:
                    acc_tier1 += int(r["capa"])

            if (acc_capa < N) or (acc_tier1 < U):
                print("  ⚠️ 상급 보장/총 용량 조건을 전역에서도 충족하지 못했습니다. 가능한 최대 집합 사용.")
                df_selected = df_sorted.copy()
            else:
                df_selected = df_cand2.loc[sel_names].copy()
        else:
            df_selected = df_cand.loc[sel_names].copy()

        # 결과는 euc 기준 가까운 순으로 다시 정렬(다운스트림 일관성)
        df_euc = df_selected.sort_values("euclidean_distance").reset_index(drop=True).copy()

        # ---------- (6) EUC 파일 저장 ----------
        dist_euc_df = pd.DataFrame({"distance": df_euc["euclidean_distance"]})
        dist_euc_path = os.path.join(save_folder, "distance_Hos2Site_euc.csv")
        dist_euc_df.to_csv(dist_euc_path, index=True, index_label="Index", encoding="utf-8-sig")

        # euc_info = df_euc[["capa", "queue_capa", "종별코드", "요양기관명"]].copy()
        # euc_info.columns = ["병상수", "queue_capa", "종별코드", "요양기관명"]
        euc_info = df_euc[["operating_rooms", "capa", "종별코드", "요양기관명"]].copy()
        euc_info.columns = ["수술실수", "병상수", "종별코드", "요양기관명"]
        euc_info_path = os.path.join(save_folder, "hospital_info_euc.csv")
        euc_info.to_csv(euc_info_path, index=True, index_label="Index", encoding="utf-8-sig")

        # [ADD] hos2site 저장 폴더
        routes_dir_hos = os.path.join(save_folder, "routes", "hos2site")
        ensure_dir(routes_dir_hos)

        # ---------- (7) ROAD 거리 계산 & 저장 (선정 병원만) ----------
        road_distances = []
        for j, (_, row) in enumerate(df_euc.iterrows()):
            end = (row["y좌표"], row["x좌표"])   # (lat,lon) of hospital
            road_km = self.get_road_distance(
                start=(latitude, longitude), end=end,            # 현재: site → hospital
                save_json_dir=routes_dir_hos, route_type="hos2site",
                source_index=j, name=row.get("요양기관명", f"hospital_{j}"),
                start_label="site", goal_label="hospital"
            )
            road_distances.append(road_km)
            time.sleep(0.05)
        df_euc = df_euc.copy()
        df_euc["road_distance"] = road_distances
        df_road = df_euc.sort_values("road_distance").reset_index(drop=True).copy()

        dist_road_df = pd.DataFrame({"distance": df_road["road_distance"]})
        dist_road_path = os.path.join(save_folder, "distance_Hos2Site_road.csv")
        dist_road_df.to_csv(dist_road_path, index=True, index_label="Index", encoding="utf-8-sig")

        road_info = df_road[["operating_rooms", "capa", "종별코드", "요양기관명"]].copy()
        road_info.columns = ["수술실수", "병상수", "종별코드", "요양기관명"]
        road_info_path = os.path.join(save_folder, "hospital_info_road.csv")
        road_info.to_csv(road_info_path, index=True, index_label="Index", encoding="utf-8-sig")

        print(f"  ✅ 병원 정보 생성 완료")


    
    def make_uav_info(self, latitude, longitude, incident_size, uav_size, save_folder):
        """UAV 정보 생성
        - 선정된 병원(euc 정렬 결과) 중 상급종합병원(종별코드=1)만 사용
        - 각 상급종합병원의 '사고지점↔병원 유클리드 거리'를 uav_size배 복제
        - 최종 길이 = (Tier1_병원_개수 * uav_size)
        - (옵션) MCI_UAV_MODE=compat 일 때 incident_size 길이로 확장본(uav_info_expanded.csv)도 저장
        """
        print(f"  🚁 UAV 정보 생성 중...")

        import os
        import numpy as np
        import pandas as pd
        from haversine import haversine

        # 0) 파라미터 정리
        try:
            uav_n = int(max(0, int(uav_size)))
        except Exception:
            uav_n = 0
        if uav_n <= 0:
            print("⚠️ UAV 대수가 0입니다. UAV 정보 생성 생략.")
            return

        # 1) 선정 병원(euc) & 거리 파일 로드
        hos_info_path = os.path.join(save_folder, "hospital_info_euc.csv")
        dist_euc_path = os.path.join(save_folder, "distance_Hos2Site_euc.csv")

        try:
            hos_df = pd.read_csv(hos_info_path, encoding="utf-8-sig")
            dist_df = pd.read_csv(dist_euc_path, encoding="utf-8-sig")
        except Exception as e:
            print(f"❌ UAV 생성 실패: 선정 병원 파일 로드 오류: {e}")
            return

        if ("종별코드" not in hos_df.columns) or ("distance" not in dist_df.columns):
            print("❌ UAV 생성 실패: hospital_info_euc.csv / distance_Hos2Site_euc.csv 포맷 확인 필요")
            return

        # 2) 길이/정렬 일치 보정
        L = min(len(hos_df), len(dist_df))
        if L == 0:
            print("⚠️ 선정 병원이 비어 있어 UAV 생성 불가.")
            return
        if len(hos_df) != len(dist_df):
            print(f"⚠️ 병원/거리 길이 불일치: hos={len(hos_df)}, dist={len(dist_df)} → {L}로 정렬")
        hos_df = hos_df.iloc[:L].reset_index(drop=True)
        dist_df = dist_df.iloc[:L].reset_index(drop=True)

        # 3) Tier1(종별코드=1) 인덱스 추출 (euc 정렬 순서 유지)
        try:
            tier1_idx = hos_df.index[hos_df["종별코드"].astype(int) == 1].tolist()
        except Exception:
            # 혹시 문자열/float 섞임 대비
            tier1_idx = []
            for i, v in enumerate(hos_df["종별코드"].tolist()):
                try:
                    if int(v) == 1:
                        tier1_idx.append(i)
                except Exception:
                    continue

        distances = []

        if len(tier1_idx) > 0:
            # 4) 각 Tier1의 euc 거리값을 uav_size번 복제
            for idx in tier1_idx:
                d = float(dist_df.loc[idx, "distance"])
                distances.extend([round(d, 3)] * uav_n)
        else:
            # 5) 폴백: 선정 병원에 Tier1이 없을 때 전체 데이터에서 가장 가까운 Tier1 1곳 사용
            print("⚠️ 선정 병원 중 상급종합병원(종별코드=1)이 없습니다. 폴백으로 전체 데이터에서 생성합니다.")
            try:
                df_full = pd.read_excel(self.hospital_data_path, engine="openpyxl")
                df_high = df_full[df_full["종별코드"] == 1].copy()
                if df_high.empty:
                    print("⚠️ 전체 데이터에도 상급종합병원이 없습니다. UAV 생성 불가.")
                    return
                # 사건지점↔병원 유클리드 거리 계산 후 가장 가까운 1곳 선택
                df_high["거리"] = df_high.apply(
                    lambda row: haversine((row["y좌표"], row["x좌표"]), (latitude, longitude)), axis=1
                )
                df_high = df_high.sort_values("거리").reset_index(drop=True)
                d = float(df_high.loc[0, "거리"])
                distances = [round(d, 3)] * uav_n
            except Exception as e:
                print(f"⚠️ 폴백 생성에서도 오류 발생: {e}")
                return

        # 6) 기본 파일 저장: 길이 = (Tier1 수 × uav_size)
        result_df = pd.DataFrame({
            "Index": range(len(distances)),
            "init_distance": distances
        })
        save_path = os.path.join(save_folder, "uav_info.csv")
        result_df.to_csv(save_path, index=False, encoding="utf-8-sig")
        print(f"  ✅ UAV 정보 생성 완료")



    def make_patient_info(self, save_folder):
        """환자 정보 생성 (하드코딩된 값 사용)"""
        print(f"  👥 환자 정보 생성 중...")
        types = self.patient_config["ratio"].keys()
        rows = []
        for t in types:
            α, β = self.patient_config["rescue_param"][t]
            rows.append({
                "type": t,
                "ratio": self.patient_config["ratio"][t],
                "rescue_param_alpha": α,
                "rescue_param_beta": β,
                "treat_tier1": self.patient_config["treat_tier1"][t],
                "treat_tier2": self.patient_config["treat_tier2"][t],
                "treat_tier1_mean": self.patient_config["treat_tier1_mean"][t],
                "treat_tier2_mean": self.patient_config["treat_tier2_mean"][t]
            })
        df = pd.DataFrame(rows)
        save_path = os.path.join(save_folder, "patient_info.csv")
        df.to_csv(save_path, index=False, encoding="utf-8-sig")
        print(f"  ✅ 환자 정보 생성 완료")

    def make_distance_Hos2Hos(self, save_folder):
        """병원 간 거리 행렬 생성"""
        print(f"  📐 병원간 거리 행렬 생성 중...")
        try:
            df_full = pd.read_excel(self.hospital_data_path, engine="openpyxl")
        except Exception as e:
            print(f"❌ 병원 데이터 로드 실패: {e}")
            return

        # Euclidean
        try:
            file_euc = os.path.join(save_folder, "hospital_info_euc.csv")
            df_euc = pd.read_csv(file_euc, encoding="utf-8-sig")
            names_euc = df_euc["요양기관명"].tolist()
            coords_euc = []
            for name in names_euc:
                row = df_full[df_full["요양기관명"] == name]
                if not row.empty:
                    coords_euc.append((row.iloc[0]["y좌표"], row.iloc[0]["x좌표"]))
                else:
                    coords_euc.append((0, 0))
            N = len(coords_euc)
            matrix = np.zeros((N, N))
            for i in range(N):
                for j in range(i, N):
                    if i == j:
                        dist = 0
                    else:
                        dist = haversine(coords_euc[i], coords_euc[j])
                    matrix[i][j] = dist
                    matrix[j][i] = dist
            save_path_euc = os.path.join(save_folder, "distance_Hos2Hos_euc.csv")
            pd.DataFrame(matrix).to_csv(save_path_euc, index=True, encoding="utf-8-sig")
        except Exception as e:
            print(f"❌ 유클리드 거리 계산 실패: {e}")

        # Road
        try:
            file_road = os.path.join(save_folder, "hospital_info_road.csv")
            df_road = pd.read_csv(file_road, encoding="utf-8-sig")
            names_road = df_road["요양기관명"].tolist()
            coords_road = []
            for name in names_road:
                row = df_full[df_full["요양기관명"] == name]
                if not row.empty:
                    coords_road.append((row.iloc[0]["y좌표"], row.iloc[0]["x좌표"]))
                else:
                    coords_road.append((0, 0))
            N = len(coords_road)
            matrix = np.zeros((N, N))
            for i in range(N):
                for j in range(i, N):
                    if i == j:
                        dist = 0
                    else:
                        dist = self.get_road_distance(coords_road[i], coords_road[j])
                        time.sleep(0.05)
                    matrix[i][j] = dist
                    matrix[j][i] = dist
            save_path_road = os.path.join(save_folder, "distance_Hos2Hos_road.csv")
            pd.DataFrame(matrix).to_csv(save_path_road, index=True, encoding="utf-8-sig")
        except Exception as e:
            print(f"❌ 도로 거리 계산 실패: {e}")
        print(f"  ✅ 병원간 거리 행렬 생성 완료")

    def _sanitize_coeff_text(self, text: str) -> str:
        """'1.1,1' 또는 '[1.1, 1]' → '1.1, 1' 로 정리"""
        if not text:
            return "1,1"
        t = text.strip()
        if t.startswith("[") and t.endswith("]"):
            t = t[1:-1]
        parts = [p.strip() for p in t.split(",") if p.strip() != ""]
        if len(parts) != 2:
            return "1,1"
        # 숫자 검증 (실패 시 기본)
        try:
            a = float(parts[0]); b = float(parts[1])
        except Exception:
            return "1,1"
        return f"{a},{b}".replace(",", ", ")
    
    def make_config_yaml(self, latitude, longitude, incident_size, amb_velocity, 
                         uav_velocity, total_samples, random_seed, save_folder):
        """Config YAML 파일 생성"""
        print(f"  ⚙️ Config YAML 생성 중...")
        folder_name = f"({latitude},{longitude})"
        config_filename = f"config_{folder_name}.yaml"
        config_path = os.path.join(save_folder, config_filename)
        relative_folder = f"./scenarios/{self.experiment_id}/{folder_name}"
        yaml_content = f"""#incident_info:
#  incident_size: {incident_size} # 사고 규모 (총 환자 수)
#  latitude: {latitude} # 위도
#  longitude: {longitude} # 경도
#  incident_type: null # 사고 타입 설정 가능하게 추후 확장

entity_info:
  patient:
    incident_size: {incident_size} # 사고 규모 (총 환자 수)
    latitude: {latitude} # 위도
    longitude: {longitude} # 경도
    incident_type: null # 사고 타입 설정 가능하게 추후 확장
    info_path: "{relative_folder}/patient_info.csv"
  hospital:
    load_data: True
    info_path: "{relative_folder}/hospital_info_road.csv"
    dist_Hos2Hos_euc_info: "{relative_folder}/distance_Hos2Hos_euc.csv"
    dist_Hos2Hos_road_info: "{relative_folder}/distance_Hos2Hos_road.csv"
    dist_Hos2Site_euc_info: "{relative_folder}/distance_Hos2Site_euc.csv"
    dist_Hos2Site_road_info: "{relative_folder}/distance_Hos2Site_road.csv"
    max_send_coeff: [{self._sanitize_coeff_text(self.max_send_coeff_text)}]
  ambulance:
    load_data: True
    dispatch_distance_info: "{relative_folder}/amb_info_road.csv"
    velocity: {amb_velocity} # unit: km/h
    handover_time: 0 # unit: minutes
  uav:
    load_data: True
    dispatch_distance_info: "{relative_folder}/uav_info.csv"
    velocity: {uav_velocity} # unit: km/h
    handover_time: 0 # unit: minutes

event_info_path: "event_info.json"

rule_info:
  isFullFactorial: True
  priority_rule: ["START", "ReSTART"]
  hos_select_rule: ["RedOnly", "YellowHalf"]
  red_mode_rule: ["OnlyUAV", "Both_UAVFirst", "Both_AMBFirst", "OnlyAMB"]
  yellow_mode_rule: ["OnlyUAV", "Both_UAVFirst", "Both_AMBFirst", "OnlyAMB"]

run_setting:
  totalSamples: {total_samples} # number of samples
  random_seed: {random_seed} # null, if do not want to fix
  rule_test: True
  eval_mode: True
  output_path: "./results/{self.experiment_id}"
  exp_indicator: "{folder_name}"
  save_info: True # NotImplemented"""
        with open(config_path, 'w', encoding='utf-8') as file:
            file.write(yaml_content)
        print(f"  ✅ Config YAML 생성 완료")
        absolute_config_path = os.path.abspath(config_path)
        print(f"CONFIG_PATH:{absolute_config_path}")
        return absolute_config_path

    def generate_scenario(self, latitude, longitude, incident_size, amb_size, 
                          uav_size, amb_velocity, uav_velocity, 
                          total_samples, random_seed):
        """
        완전한 시나리오 생성 (모든 CSV + YAML)
        Returns: 생성된 config 파일 경로
        """
        print(f"""\n📍 좌표 ({latitude},{longitude}) 시나리오 생성 시작...""")
        start_time = time.time()
        folder_name = f"({latitude},{longitude})"
        save_folder = os.path.join(self.base_path, "scenarios", self.experiment_id, folder_name)
        os.makedirs(save_folder, exist_ok=True)

        # 수동 좌표도 역지오코딩 수행
        print(f"🔍 좌표 ({latitude},{longitude}) 주소 정보 조회 중...")
        try:
            coord_gen = CoordinateGenerator(
                client_id=self.client_id,
                client_secret=self.client_secret,
                shp_path=self.shp_path
            )
            addr_info = coord_gen.reverse_geocode(latitude, longitude)
            if addr_info.get("is_valid", False):
                coordinate_info = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "full_address": addr_info.get("full_address", ""),
                    "road_address": addr_info.get("road_address", ""),
                    "area1": addr_info.get("area1", ""),
                    "area2": addr_info.get("area2", ""),
                    "area3": addr_info.get("area3", ""),
                    "area4": addr_info.get("area4", ""),
                    "is_valid": True
                }
                print(f"COORDINATE_INFO:{json.dumps(coordinate_info, ensure_ascii=False)}")
                print(f"  📍 좌표 생성: ({latitude}, {longitude}) - {addr_info.get('full_address','')}")
            else:
                coordinate_info = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "full_address": "",
                    "road_address": "",
                    "area1": "",
                    "area2": "",
                    "area3": "",
                    "area4": "",
                    "is_valid": False
                }
                print(f"COORDINATE_INFO:{json.dumps(coordinate_info, ensure_ascii=False)}")
                print(f"  📍 좌표 생성: ({latitude}, {longitude}) - API 호출 실패")
        except Exception as e:
            print(f"⚠️ 역지오코딩 실패: {e}")
            coordinate_info = {
                "latitude": latitude,
                "longitude": longitude,
                "full_address": "API 호출 실패",
                "road_address": "",
                "area1": "",
                "area2": "",
                "area3": "",
                "area4": "",
                "is_valid": False
            }
            print(f"COORDINATE_INFO:{json.dumps(coordinate_info, ensure_ascii=False)}")
            print(f"  📍 좌표 생성: ({latitude}, {longitude}) - API 호출 실패")

        # 생성 파이프라인
        self.make_amb_info(latitude, longitude, incident_size, save_folder)
        self.make_hospital_info(latitude, longitude, incident_size, save_folder)
        self.make_uav_info(latitude, longitude, incident_size, uav_size, save_folder)
        self.make_patient_info(save_folder)
        self.make_distance_Hos2Hos(save_folder)
        config_path = self.make_config_yaml(
            latitude, longitude, incident_size, 
            amb_velocity, uav_velocity, total_samples, 
            random_seed, save_folder
        )
        
        elapsed = round(time.time() - start_time, 2)
        print(f"  ⏱️ 시나리오 생성 완료 ({elapsed}초)")
        print(f"CONFIG_PATH:{config_path}")
        return config_path

# CLI 실행용
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCI 시나리오 동적 생성 (크로스 환경 호환)")
    parser.add_argument("--base_path", required=True, help="프로젝트 루트 경로")
    parser.add_argument("--latitude", type=float, required=False, help="위도")
    parser.add_argument("--longitude", type=float, required=False, help="경도")
    parser.add_argument("--incident_size", type=int, default=30, help="환자 수")
    parser.add_argument("--amb_size", type=int, default=30, help="구급차 수")
    parser.add_argument("--uav_size", type=int, default=3, help="UAV 수")
    parser.add_argument("--amb_velocity", type=int, default=40, help="구급차 속도")
    parser.add_argument("--uav_velocity", type=int, default=80, help="UAV 속도")
    parser.add_argument("--total_samples", type=int, default=10, help="시뮬레이션 반복 수")
    parser.add_argument("--random_seed", type=int, default=0, help="랜덤 시드")
    parser.add_argument("--experiment_id", type=str, default=None, help="실험 ID")
    # 좌표 생성 관련
    parser.add_argument("--generate_coord", action="store_true", help="좌표 자동 생성")
    parser.add_argument("--coord_mode", choices=["korea_random", "sido"], default="korea_random", help="좌표 생성 모드")
    parser.add_argument("--sido_name", type=str, help="시도명 (coord_mode=sido일 때)")
    # 고급 옵션(ENV 또는 CLI 둘 다 허용)
    # parser.add_argument("--queue_policy", type=str, help='예: "0", "capa/2", "0.5"')
    parser.add_argument("--buffer_ratio", type=float, help="후보군 버퍼 배수 (기본 1.5)")
    parser.add_argument("--util_by_tier", type=str, help='예: "1:0.90,11:0.75,etc:0.60"')
    parser.add_argument("--hospital_max_send_coeff", type=str, default=None, help="전송계수 'a,b' 형식 (예: 1.1,1.0). 미입력시 ENV(MCI_MAX_SEND_COEFF) 또는 기본 1,1")

    args = parser.parse_args()
    try:
        # UTF-8 출력 설정
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    try:
        generator = ScenarioGenerator(args.base_path, args.experiment_id)

        # CLI가 주어지면 ENV 기본값을 덮어씀
        if args.hospital_max_send_coeff:
            generator.max_send_coeff_text = args.hospital_max_send_coeff
        # if args.queue_policy is not None:
        #     generator.queue_policy = args.queue_policy
        if args.buffer_ratio is not None:
            generator.buffer_ratio = float(args.buffer_ratio)
        if args.util_by_tier:
            m = parse_util_map(args.util_by_tier)
            if m:
                generator.util_by_tier = m

        # 현재 적용값 재출력
        print(f"buffer_ratio={generator.buffer_ratio}")

        # 좌표 처리
        if args.generate_coord:
            coord_result = generator.generate_coordinate_for_scenario(args.coord_mode, args.sido_name)
            if coord_result:
                latitude, longitude = coord_result
            else:
                print("❌ 좌표 생성 실패")
                sys.exit(1)
        else:
            if args.latitude is None or args.longitude is None:
                print("❌ --latitude, --longitude 인자가 필요합니다.")
                sys.exit(1)
            latitude, longitude = args.latitude, args.longitude
        
        # 시나리오 생성
        config_path = generator.generate_scenario(
            latitude, longitude,
            args.incident_size, args.amb_size, args.uav_size,
            args.amb_velocity, args.uav_velocity,
            args.total_samples, args.random_seed
        )
        
        if config_path:
            print(f"\n✅ 시나리오 생성 성공!")
            print(f"📄 Config 파일: {config_path}")
        else:
            print("❌ 시나리오 생성 실패")
            sys.exit(1)
            
    except Exception as e:
        print(f"💥 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
