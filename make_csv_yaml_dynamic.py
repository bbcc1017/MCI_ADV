# -*- coding: utf-8 -*-
from haversine import haversine
import pandas as pd
import os
import requests
import numpy as np
import time
import yaml
import argparse
import json
from datetime import datetime
from random_coordinate_generator import CoordinateGenerator

class ScenarioGenerator:
    """동적 파라미터 기반 시나리오 생성 클래스"""
    
    def __init__(self, base_path, experiment_id=None, client_id=None, client_secret=None):
        """
        Args:
            base_path: 프로젝트 루트 경로
            experiment_id: 실험 ID (폴더명에 사용)
            client_id: Naver API Client ID
            client_secret: Naver API Client Secret
        """
        self.base_path = base_path
        self.experiment_id = experiment_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # API 키 설정
        self.client_id = client_id or os.environ.get('NAVER_CLIENT_ID', "4aofuofs1i")
        self.client_secret = client_secret or os.environ.get('NAVER_CLIENT_SECRET', "YcN7r37Irvjx7iOx4CqKlXP8dxG56veUv5GvJEgf")
        
        # 좌표 생성기 초기화 (SHP 파일 자동 탐지)
        shp_path = os.path.join(base_path, "scenarios", "ctprvn.shp")
        self.coord_generator = CoordinateGenerator(
            client_id=self.client_id,
            client_secret=self.client_secret,
            shp_path=shp_path
        )
        
        # Patient 정보 (하드코딩)
        self.ratio_dict = {"Red": 0.1, "Yellow": 0.3, "Green": 0.5, "Black": 0.1}
        self.rescue_param_dict = {"Red": (6, 5), "Yellow": (2, 13), "Green": (1, 22), "Black": (0, 0)}
        self.treat_tier1_dict = {"Red": True, "Yellow": True, "Green": True, "Black": True}
        self.treat_tier2_dict = {"Red": False, "Yellow": True, "Green": True, "Black": True}
        self.treat_tier1_mean_dict = {"Red": 40, "Yellow": 20, "Green": 10, "Black": 0}
        self.treat_tier2_mean_dict = {"Red": 60, "Yellow": 30, "Green": 15, "Black": 0}
        
        # 후보군 확장 배수 (2로 수정)
        self.multiplier = 2

    def get_road_distance(self, start, end, max_retries=2):
        """도로 거리 계산"""
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
            "fuel_type": "DIESEL"
        }

        for attempt in range(max_retries):
            try:
                res = requests.get(url, headers=headers, params=params, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    return data["route"]["trafast"][0]["summary"]["distance"] / 1000  # m → km
                elif res.status_code == 401:
                    print(f"[401 인증 실패] 재시도 {attempt + 1}")
                else:
                    print(f"[API 오류] {res.status_code}: {res.text}")
                    break
            except Exception as e:
                print(f"[예외] {e}")
        return float("inf")

    def generate_coordinate_for_scenario(self, mode="korea_random", sido_name=None):
        """
        시나리오용 좌표 생성 (새로운 좌표 생성기 사용)
        
        Args:
            mode: "korea_random", "sido", "manual"
            sido_name: 시도명 (mode="sido"일 때 필요)
        
        Returns:
            (latitude, longitude) 또는 None
        """
        try:
            if mode == "manual":
                # 수동 입력은 파워쉘에서 처리
                return None
            
            result = self.coord_generator.generate_valid_coordinate(mode, sido_name)
            if result:
                lat, lon, addr_info = result
                print(f"  📍 좌표 생성: ({lat}, {lon}) - {addr_info['area1']} {addr_info['area2']}")
                return lat, lon
            else:
                print(f"  ❌ 유효한 좌표 생성 실패")
                return None
                
        except Exception as e:
            print(f"  ❌ 좌표 생성 오류: {e}")
            return None

    def make_amb_info(self, latitude, longitude, incident_size, save_folder):
        """구급차 정보 생성"""
        # 소방서 데이터 로드
        fire_path = os.path.join(self.base_path, "scenarios", "안전센터와 소방서.csv")
        df = pd.read_csv(fire_path, encoding="cp949")
        coords = list(zip(df["y좌표"], df["x좌표"]))

        # 유클리드 거리 계산
        euc_distances = []
        for coord in coords:
            euc_distances.append(haversine(coord, (latitude, longitude)))
        df["euclidean_distance"] = euc_distances

        # euc 저장
        df_sorted_euc = df.sort_values("euclidean_distance").head(incident_size).copy()
        df_sorted_euc = df_sorted_euc.rename(columns={
            "euclidean_distance": "init_distance",
            "기관명": "안전센터/소방서 이름"
        })
        df_sorted_euc = df_sorted_euc.reset_index(drop=True)
        df_sorted_euc = df_sorted_euc[["init_distance", "안전센터/소방서 이름"]]
        euc_save_path = os.path.join(save_folder, "amb_info_euc.csv")
        df_sorted_euc.to_csv(euc_save_path, index=True, index_label="Index", encoding="utf-8-sig")

        # 후보군 확장 및 도로 거리 계산
        df_candidates = df.sort_values("euclidean_distance").head(incident_size * self.multiplier).copy()
        road_distances = []
        for idx, row in df_candidates.iterrows():
            coord = (row["y좌표"], row["x좌표"])
            dist = self.get_road_distance(coord, (latitude, longitude))
            road_distances.append(dist)
            time.sleep(0.1)  # API 호출 간격
        df_candidates["road_distance"] = road_distances

        # road 저장
        df_sorted_road = df_candidates.sort_values("road_distance").head(incident_size).copy()
        df_sorted_road = df_sorted_road.rename(columns={
            "road_distance": "init_distance",
            "기관명": "안전센터/소방서 이름"
        })
        df_sorted_road = df_sorted_road.reset_index(drop=True)
        df_sorted_road = df_sorted_road[["init_distance", "안전센터/소방서 이름"]]
        road_save_path = os.path.join(save_folder, "amb_info_road.csv")
        df_sorted_road.to_csv(road_save_path, index=True, index_label="Index", encoding="utf-8-sig")
        
        print(f"  ✅ amb_info 생성 완료")

    def make_hospital_info(self, latitude, longitude, incident_size, save_folder):
        """병원 정보 생성 (상급종합병원 보장 로직 포함)"""
        excel_path = os.path.join(self.base_path, "scenarios", "엑셀 결합 데이터.xlsx")
        df = pd.read_excel(excel_path, engine='openpyxl')
        coords = list(zip(df["y좌표"], df["x좌표"]))

        # 유클리드 거리 계산
        euc_distances = [haversine(coord, (latitude, longitude)) for coord in coords]
        df["euclidean_distance"] = euc_distances

        # euc 기준 정렬
        df_sorted = df.sort_values("euclidean_distance").reset_index(drop=True)
        df_euc = df_sorted.head(incident_size).copy()
        
        # 상급종합병원 보장 로직 (euc)
        tier1_in_selected = df_euc[df_euc["종별코드"] == 1]
        if tier1_in_selected.empty:
            print(f"  ⚠️ 거리순 {incident_size}개에 상급종합병원 없음. 가장 가까운 상급종합병원으로 교체")
            # 전체에서 가장 가까운 상급종합병원 찾기
            tier1_hospitals = df_sorted[df_sorted["종별코드"] == 1]
            if not tier1_hospitals.empty:
                closest_tier1 = tier1_hospitals.iloc[0]
                # 마지막 병원과 교체
                df_euc.iloc[-1] = closest_tier1
                print(f"    → {df_euc.iloc[-1]['요양기관명']} (상급종합병원)로 교체")
        
        df_candidates = df_sorted.head(incident_size * self.multiplier).copy()

        # distance_Hos2Site_euc.csv 저장
        dist_euc_df = pd.DataFrame({"distance": df_euc["euclidean_distance"]})
        dist_euc_path = os.path.join(save_folder, "distance_Hos2Site_euc.csv")
        dist_euc_df.to_csv(dist_euc_path, index=True, index_label="Index", encoding="utf-8-sig")

        # hospital_info_euc.csv 저장
        df_euc["queue_capa"] = 0
        df_euc = df_euc[["응급실병상수", "queue_capa", "종별코드", "요양기관명"]]
        df_euc.columns = ["병상수", "queue_capa", "종별코드", "요양기관명"]
        euc_info_path = os.path.join(save_folder, "hospital_info_euc.csv")
        df_euc.to_csv(euc_info_path, index=True, index_label="Index", encoding="utf-8-sig")

        # 도로 거리 계산
        road_distances = []
        for idx, row in df_candidates.iterrows():
            coord = (row["y좌표"], row["x좌표"])
            dist = self.get_road_distance(coord, (latitude, longitude))
            road_distances.append(dist)
            time.sleep(0.1)
        df_candidates["road_distance"] = road_distances

        # road 기준 정렬
        df_road = df_candidates.sort_values("road_distance").reset_index(drop=True).head(incident_size).copy()
        
        # 상급종합병원 보장 로직 (road)
        tier1_in_selected_road = df_road[df_road["종별코드"] == 1]
        if tier1_in_selected_road.empty:
            print(f"  ⚠️ 도로거리순 {incident_size}개에 상급종합병원 없음. 가장 가까운 상급종합병원으로 교체")
            # 전체에서 가장 가까운 상급종합병원 찾기 (도로거리 기준)
            tier1_candidates = df_candidates[df_candidates["종별코드"] == 1]
            if not tier1_candidates.empty:
                closest_tier1_road = tier1_candidates.sort_values("road_distance").iloc[0]
                # 마지막 병원과 교체
                df_road.iloc[-1] = closest_tier1_road
                print(f"    → {df_road.iloc[-1]['요양기관명']} (상급종합병원)로 교체")

        # distance_Hos2Site_road.csv 저장
        dist_road_df = pd.DataFrame({"distance": df_road["road_distance"]})
        dist_road_path = os.path.join(save_folder, "distance_Hos2Site_road.csv")
        dist_road_df.to_csv(dist_road_path, index=True, index_label="Index", encoding="utf-8-sig")

        # hospital_info_road.csv 저장
        df_road["queue_capa"] = 0
        df_road = df_road[["응급실병상수", "queue_capa", "종별코드", "요양기관명"]]
        df_road.columns = ["병상수", "queue_capa", "종별코드", "요양기관명"]
        road_info_path = os.path.join(save_folder, "hospital_info_road.csv")
        df_road.to_csv(road_info_path, index=True, index_label="Index", encoding="utf-8-sig")
        
        print(f"  ✅ hospital_info 생성 완료")

    def make_uav_info(self, latitude, longitude, incident_size, uav_size, save_folder):
        """UAV 정보 생성"""
        excel_path = os.path.join(self.base_path, "scenarios", "엑셀 결합 데이터.xlsx")
        df = pd.read_excel(excel_path, engine="openpyxl")

        # 상급종합병원만 필터
        df_high = df[df["종별코드"] == 1].copy()
        if df_high.empty:
            print("[경고] 종별코드 1 병원이 없습니다. UAV 생성 불가.")
            return None

        # 거리 계산
        df_high["거리"] = df_high.apply(
            lambda row: haversine((row["y좌표"], row["x좌표"]), (latitude, longitude)), axis=1
        )

        # 거리순 정렬
        df_sorted = df_high.sort_values("거리").reset_index(drop=True)

        # 거리값을 uav_size배 복제
        uav_distances = []
        for _, row in df_sorted.iterrows():
            uav_distances.extend([row["거리"]] * uav_size)

        # incident_size만큼 자르기
        uav_distances = uav_distances[:incident_size]

        # 저장
        result_df = pd.DataFrame({
            "Index": range(len(uav_distances)),
            "init_distance": [round(d, 3) for d in uav_distances]
        })
        save_path = os.path.join(save_folder, "uav_info.csv")
        result_df.to_csv(save_path, index=False, encoding="utf-8-sig")
        
        print(f"  ✅ uav_info 생성 완료")

    def make_patient_info(self, save_folder):
        """환자 정보 생성 (하드코딩된 값 사용)"""
        types = self.ratio_dict.keys()
        rows = []
        for t in types:
            α, β = self.rescue_param_dict[t]
            rows.append({
                "type": t,
                "ratio": self.ratio_dict[t],
                "rescue_param_alpha": α,
                "rescue_param_beta": β,
                "treat_tier1": self.treat_tier1_dict[t],
                "treat_tier2": self.treat_tier2_dict[t],
                "treat_tier1_mean": self.treat_tier1_mean_dict[t],
                "treat_tier2_mean": self.treat_tier2_mean_dict[t]
            })

        df = pd.DataFrame(rows)
        save_path = os.path.join(save_folder, "patient_info.csv")
        df.to_csv(save_path, index=False, encoding="utf-8-sig")
        
        print(f"  ✅ patient_info 생성 완료")

    def make_distance_Hos2Hos(self, save_folder):
        """병원 간 거리 행렬 생성"""
        excel_path = os.path.join(self.base_path, "scenarios", "엑셀 결합 데이터.xlsx")
        df_full = pd.read_excel(excel_path, engine="openpyxl")

        # Euclidean 거리 행렬
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
            print(f"[오류] 유클리드 거리 계산 실패: {e}")

        # Road 거리 행렬
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
                        time.sleep(0.1)
                    matrix[i][j] = dist
                    matrix[j][i] = dist

            save_path_road = os.path.join(save_folder, "distance_Hos2Hos_road.csv")
            pd.DataFrame(matrix).to_csv(save_path_road, index=True, encoding="utf-8-sig")

        except Exception as e:
            print(f"[오류] 도로 거리 계산 실패: {e}")
        
        print(f"  ✅ distance_Hos2Hos 생성 완료")

    def make_config_yaml(self, latitude, longitude, incident_size, amb_velocity, 
                        uav_velocity, total_samples, random_seed, save_folder):
        """Config YAML 파일 생성"""
        folder_name = f"({latitude},{longitude})"
        config_filename = f"config_{folder_name}.yaml"
        config_path = os.path.join(save_folder, config_filename)
        
        # 실험 폴더 경로 (상대경로로 저장)
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
    max_send_coeff: [1,1]
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
        
        print(f"  ✅ config.yaml 생성 완료")
        return config_path

    def generate_scenario(self, latitude, longitude, incident_size, amb_size, 
                         uav_size, amb_velocity, uav_velocity, 
                         total_samples, random_seed):
        """
        완전한 시나리오 생성 (모든 CSV + YAML)
        
        Returns:
            생성된 config 파일 경로
        """
        print(f"\n📍 좌표 ({latitude},{longitude}) 시나리오 생성 시작...")
        start_time = time.time()
        
        # 저장 폴더 생성
        folder_name = f"({latitude},{longitude})"
        save_folder = os.path.join(self.base_path, "scenarios", self.experiment_id, folder_name)
        os.makedirs(save_folder, exist_ok=True)
        
        # 각 파일 생성
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
        print(f"Config 파일 경로: {config_path}")
        
        return config_path


# CLI 실행용
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCI 시나리오 동적 생성")
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
    
    # 좌표 생성 관련 (선택사항)
    parser.add_argument("--generate_coord", action="store_true", help="좌표 자동 생성")
    parser.add_argument("--coord_mode", choices=["korea_random", "sido"], default="korea_random", help="좌표 생성 모드")
    parser.add_argument("--sido_name", type=str, help="시도명 (coord_mode=sido일 때)")
    
    args = parser.parse_args()
    
    generator = ScenarioGenerator(args.base_path, args.experiment_id)
    
    # 좌표 처리
    if args.generate_coord:
        # 자동 좌표 생성
        coord_result = generator.generate_coordinate_for_scenario(args.coord_mode, args.sido_name)
        if coord_result:
            latitude, longitude = coord_result
        else:
            print("❌ 좌표 생성 실패")
            exit(1)
    else:
        if args.latitude is None or args.longitude is None:
            print("❌ --latitude, --longitude 인자가 필요합니다.")
            exit(1)
        latitude, longitude = args.latitude, args.longitude
    
    config_path = generator.generate_scenario(
        latitude, longitude,
        args.incident_size, args.amb_size, args.uav_size,
        args.amb_velocity, args.uav_velocity,
        args.total_samples, args.random_seed
    )
    
    print(f"\n✅ Config 파일 경로: {config_path}")