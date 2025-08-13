# -*- coding: utf-8 -*-
import random
import requests
import pandas as pd
import geopandas as gpd
import numpy as np
from typing import List, Tuple, Dict, Optional
import time
import os
from datetime import datetime
from shapely.geometry import Point

class CoordinateGenerator:
    """대한민국 내 랜덤 좌표 생성 및 주소 변환 클래스 (SHP 기반)"""
    
    def __init__(self, client_id: str = None, client_secret: str = None, shp_path: str = None):
        """
        Args:
            client_id: Naver API Client ID (없으면 환경변수에서 읽음)
            client_secret: Naver API Client Secret (없으면 환경변수에서 읽음)
            shp_path: 시도 경계 SHP 파일 경로 (None이면 자동 탐지)
        """
        # 네이버 API 키 설정
        self.client_id = client_id or os.environ.get('NAVER_CLIENT_ID', "4aofuofs1i")
        self.client_secret = client_secret or os.environ.get('NAVER_CLIENT_SECRET', "YcN7r37Irvjx7iOx4CqKlXP8dxG56veUv5GvJEgf")
        
        # SHP 파일 경로 자동 탐지
        if shp_path is None:
            shp_path = self._find_shp_file()
        
        # SHP 파일 로드
        self.gdf = None
        self.sido_column = None
        
        if shp_path and os.path.exists(shp_path):
            try:
                self.gdf = gpd.read_file(shp_path, encoding='cp949')
                
                # 좌표계 정보 확인 및 설정
                if self.gdf.crs is None:
                    # prj 파일이 없는 경우 한국측지계로 기본 설정
                    self.gdf.set_crs(epsg=5179, inplace=True)
                
                print(f"원본 좌표계: {self.gdf.crs}")
                
                # WGS84 좌표계로 변환
                if self.gdf.crs.to_epsg() != 4326:
                    print("🔄 WGS84 좌표계로 변환 중...")
                    self.gdf = self.gdf.to_crs('EPSG:4326')
                    print("✅ 좌표계 변환 완료")
                
                # 시도명 컬럼 자동 탐지 (한국어 이름 우선)
                possible_columns = ['CTP_KOR_NM', '시도명', 'NAME_KOR', 'CTP_ENG_NM', 'NAME', 'name', 'CTPRVN_CD']
                for col in possible_columns:
                    if col in self.gdf.columns:
                        self.sido_column = col
                        break
                
                if self.sido_column is None:
                    # 첫 번째 문자열 컬럼을 시도명으로 사용
                    string_cols = self.gdf.select_dtypes(include=['object']).columns
                    if len(string_cols) > 0:
                        self.sido_column = string_cols[0]
                
                # 면적 기반 가중치 계산 (투영 좌표계에서 정확한 면적 계산)
                # 한국 중부원점 좌표계로 임시 변환하여 면적 계산
                gdf_projected = self.gdf.to_crs('EPSG:5179')  # 한국측지계로 다시 변환
                gdf_projected['area'] = gdf_projected.geometry.area
                total_area = gdf_projected['area'].sum()
                self.gdf['area'] = gdf_projected['area']
                self.gdf['weight'] = self.gdf['area'] / total_area
                
                print(f"SHP 파일 로드 완료: {len(self.gdf)}개 시도")
                if self.sido_column:
                    print(f"시도명 컬럼: {self.sido_column}")
                    sidos = list(self.gdf[self.sido_column].unique())
                    print(f"사용 가능한 시도: {sidos}")
                else:
                    print("시도명 컬럼을 찾을 수 없습니다.")
                    
            except Exception as e:
                print(f"SHP 파일 로드 실패: {e}")
                self.gdf = None
        else:
            if shp_path:
                print(f"SHP 파일을 찾을 수 없습니다: {shp_path}")
            else:
                print("SHP 파일을 자동으로 찾을 수 없습니다.")
            print("SHP 파일 없이는 전국랜덤과 수동입력만 가능합니다.")
    
    def _find_shp_file(self) -> str:
        """scenarios 폴더에서 SHP 파일 자동 탐지"""
        # 현재 스크립트 위치 기준으로 scenarios 폴더 찾기
        current_dir = os.path.dirname(os.path.abspath(__file__))
        scenarios_dir = os.path.join(current_dir, "scenarios")
        
        if not os.path.exists(scenarios_dir):
            print(f"scenarios 폴더를 찾을 수 없습니다: {scenarios_dir}")
            return None
        
        # SHP 파일들 찾기
        shp_files = []
        for file in os.listdir(scenarios_dir):
            if file.endswith('.shp'):
                shp_files.append(os.path.join(scenarios_dir, file))
        
        if not shp_files:
            print(f"scenarios 폴더에서 SHP 파일을 찾을 수 없습니다: {scenarios_dir}")
            return None
        
        # ctprvn.shp 우선 선택, 없으면 첫 번째 SHP 파일
        for shp_file in shp_files:
            if 'ctprvn' in os.path.basename(shp_file).lower():
                print(f"SHP 파일 자동 탐지: {shp_file}")
                return shp_file
        
        # ctprvn이 없으면 첫 번째 파일 사용
        selected_shp = shp_files[0]
        print(f"SHP 파일 자동 선택: {selected_shp}")
        return selected_shp
    
    def _find_shp_file(self) -> str:
        """scenarios 폴더에서 SHP 파일 자동 탐지"""
        # 현재 스크립트 위치 기준으로 scenarios 폴더 찾기
        current_dir = os.path.dirname(os.path.abspath(__file__))
        scenarios_dir = os.path.join(current_dir, "scenarios")
        
        if not os.path.exists(scenarios_dir):
            print(f"📁 scenarios 폴더를 찾을 수 없습니다: {scenarios_dir}")
            return None
        
        # SHP 파일들 찾기
        shp_files = []
        for file in os.listdir(scenarios_dir):
            if file.endswith('.shp'):
                shp_files.append(os.path.join(scenarios_dir, file))
        
        if not shp_files:
            print(f"📁 scenarios 폴더에서 SHP 파일을 찾을 수 없습니다: {scenarios_dir}")
            return None
        
        # ctprvn.shp 우선 선택, 없으면 첫 번째 SHP 파일
        for shp_file in shp_files:
            if 'ctprvn' in os.path.basename(shp_file).lower():
                print(f"📍 SHP 파일 자동 탐지: {shp_file}")
                return shp_file
        
        # ctprvn이 없으면 첫 번째 파일 사용
        selected_shp = shp_files[0]
        print(f"📍 SHP 파일 자동 선택: {selected_shp}")
        return selected_shp
    
    def get_available_sidos(self) -> List[str]:
        """사용 가능한 시도 목록 반환"""
        if self.gdf is not None and self.sido_column:
            return sorted(list(self.gdf[self.sido_column].unique()))
        else:
            return []
    
    def is_shp_available(self) -> bool:
        """SHP 파일 사용 가능 여부"""
        return self.gdf is not None and self.sido_column is not None
    
    def generate_korea_random_coordinates(self, count: int = 1, weighted: bool = False) -> List[Tuple[float, float]]:
        """
        대한민국 전체에서 랜덤 좌표 생성 (SHP 기반)
        
        Args:
            count: 생성할 좌표 개수
            weighted: True면 면적 비례, False면 균등 확률
        
        Returns:
            [(위도, 경도), ...] 리스트
        """
        if not self.is_shp_available():
            # SHP 없으면 전국 바운딩 박스에서 생성
            print("SHP 파일이 없어 전국 바운딩 박스에서 생성합니다.")
            return self._generate_bbox_coordinates(count, 33.1, 38.6, 124.6, 131.0)
        
        coordinates = []
        max_attempts = count * 100  # 과도한 시도 방지
        attempts = 0
        
        while len(coordinates) < count and attempts < max_attempts:
            attempts += 1
            
            # 시도 선택 (가중치 또는 균등)
            if weighted:
                sido_idx = np.random.choice(len(self.gdf), p=self.gdf['weight'])
            else:
                sido_idx = np.random.choice(len(self.gdf))
            
            sido_geometry = self.gdf.iloc[sido_idx].geometry
            
            # 해당 시도에서 랜덤 좌표 생성
            coord = self._generate_point_in_polygon(sido_geometry)
            if coord:
                coordinates.append(coord)
        
        if len(coordinates) < count:
            print(f"{count}개 중 {len(coordinates)}개만 생성됨")
        
        return coordinates
    
    def generate_sido_coordinates(self, sido_name: str, count: int = 1) -> List[Tuple[float, float]]:
        """
        특정 시도 내에서 랜덤 좌표 생성
        
        Args:
            sido_name: 시도명
            count: 생성할 좌표 개수
        
        Returns:
            [(위도, 경도), ...] 리스트
        """
        if not self.is_shp_available():
            print(f"SHP 파일이 없어 시도별 생성이 불가능합니다: {sido_name}")
            return []
        
        # 해당 시도 찾기
        sido_mask = self.gdf[self.sido_column].str.contains(sido_name, na=False, case=False)
        if not sido_mask.any():
            print(f"시도를 찾을 수 없습니다: {sido_name}")
            available = self.get_available_sidos()
            print(f"사용 가능한 시도: {available}")
            return []
        
        sido_geometry = self.gdf[sido_mask].iloc[0].geometry
        coordinates = []
        max_attempts = count * 200
        attempts = 0
        
        while len(coordinates) < count and attempts < max_attempts:
            attempts += 1
            coord = self._generate_point_in_polygon(sido_geometry)
            if coord:
                coordinates.append(coord)
        
        if len(coordinates) < count:
            print(f"{sido_name}에서 {count}개 중 {len(coordinates)}개만 생성됨")
        
        return coordinates
    
    def _generate_point_in_polygon(self, geometry) -> Optional[Tuple[float, float]]:
        """폴리곤 내부에서 랜덤 포인트 생성"""
        minx, miny, maxx, maxy = geometry.bounds
        
        # 바운딩 박스에서 랜덤 포인트 생성 후 내부 검증
        for _ in range(100):  # 최대 100번 시도
            lon = random.uniform(minx, maxx)
            lat = random.uniform(miny, maxy)
            point = Point(lon, lat)
            
            if geometry.contains(point):
                return (round(lat, 6), round(lon, 6))
        
        return None
    
    def _generate_bbox_coordinates(self, count: int, lat_min: float, lat_max: float, 
                                  lon_min: float, lon_max: float) -> List[Tuple[float, float]]:
        """바운딩 박스에서 랜덤 좌표 생성 (SHP 없을 때 대체)"""
        coordinates = []
        for _ in range(count):
            lat = random.uniform(lat_min, lat_max)
            lon = random.uniform(lon_min, lon_max)
            coordinates.append((round(lat, 6), round(lon, 6)))
        return coordinates
    
    def reverse_geocode(self, lat: float, lon: float, max_retries: int = 3) -> Dict:
        """
        좌표를 주소로 변환 (Naver Reverse Geocoding API)
        """
        url = "https://maps.apigw.ntruss.com/map-reversegeocode/v2/gc"
        headers = {
            "X-NCP-APIGW-API-KEY-ID": self.client_id,
            "X-NCP-APIGW-API-KEY": self.client_secret
        }
        params = {
            "coords": f"{lon},{lat}",
            "orders": "legalcode,admcode,addr,roadaddr",
            "output": "json"
        }
        
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get("status", {}).get("code") == 0:
                        results = data.get("results", [])
                        if results:
                            addr_info = results[0]
                            region = addr_info.get("region", {})
                            
                            # 주소 구성
                            area1 = region.get("area1", {}).get("name", "")  # 시/도
                            area2 = region.get("area2", {}).get("name", "")  # 시/군/구
                            area3 = region.get("area3", {}).get("name", "")  # 읍/면/동
                            area4 = region.get("area4", {}).get("name", "")  # 리
                            
                            # 도로명 주소
                            road_addr = ""
                            if len(results) > 1:
                                for result in results[1:]:
                                    if result.get("name") == "roadaddr":
                                        road_land = result.get("land", {})
                                        road_addr = f"{road_land.get('name', '')} {road_land.get('number1', '')}"
                                        break
                            
                            return {
                                "full_address": f"{area1} {area2} {area3} {area4}".strip(),
                                "road_address": road_addr,
                                "area1": area1,
                                "area2": area2,
                                "area3": area3,
                                "is_valid": True
                            }
                    
                    # 주소를 찾을 수 없는 경우 (해상 등)
                    return {
                        "full_address": "주소 정보 없음",
                        "road_address": "",
                        "area1": "미상",
                        "area2": "",
                        "area3": "",
                        "is_valid": False
                    }
                    
                elif response.status_code == 429:
                    print(f"API 요청 한도 초과. {attempt + 1}/{max_retries} 재시도...")
                    time.sleep(2)
                else:
                    print(f"API 오류: {response.status_code}")
                    
            except Exception as e:
                print(f"Reverse geocoding 오류: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
        
        return {
            "full_address": "API 오류",
            "road_address": "",
            "area1": "오류",
            "area2": "",
            "area3": "",
            "is_valid": False
        }
    
    def generate_valid_coordinate(self, mode: str = "korea_random", sido_name: str = None, 
                                 max_attempts: int = 5) -> Optional[Tuple[float, float, Dict]]:
        """
        유효한 좌표 하나를 생성 (API 검증 포함)
        
        Args:
            mode: "korea_random", "sido", "manual"
            sido_name: 시도명 (mode="sido"일 때 필요)
            max_attempts: 최대 시도 횟수
        
        Returns:
            (위도, 경도, 주소정보) 또는 None
        """
        for attempt in range(max_attempts):
            # 좌표 생성
            if mode == "sido" and sido_name:
                coords = self.generate_sido_coordinates(sido_name, 1)
                if not coords:
                    return None
                lat, lon = coords[0]
            elif mode == "korea_random":
                coords = self.generate_korea_random_coordinates(1, weighted=False)
                if not coords:
                    return None
                lat, lon = coords[0]
            else:
                return None
            
            # API로 검증
            addr_info = self.reverse_geocode(lat, lon)
            
            if addr_info.get("is_valid", False):
                return lat, lon, addr_info
            else:
                print(f"  재생성 시도 {attempt + 1}/{max_attempts}: ({lat}, {lon}) - 해상 또는 무효 지역")
        
        return None
    
    def generate_coordinate_info(self, 
                                 count: int = 1, 
                                 mode: str = "korea_random",
                                 sido_name: str = None,
                                 save_path: str = None,
                                 show_progress: bool = True) -> pd.DataFrame:
        """
        좌표 생성 및 주소 정보 수집
        
        Args:
            count: 생성할 좌표 개수
            mode: "korea_random", "sido", "manual"
            sido_name: 시도명 (mode="sido"일 때 필요)
            save_path: CSV 저장 경로
            show_progress: 진행상황 출력 여부
        
        Returns:
            좌표 정보 DataFrame
        """
        if show_progress:
            if mode == "sido" and sido_name:
                print(f"[{sido_name}] {count}개의 랜덤 좌표 생성 중...")
            else:
                print(f"[대한민국] {count}개의 랜덤 좌표 생성 중...")
        
        coord_info = []
        successful = 0
        total_attempts = 0
        
        while successful < count:
            total_attempts += 1
            
            # 무한 루프 방지
            if total_attempts > count * 10:
                print(f"너무 많은 시도 ({total_attempts}회). {successful}개 좌표로 종료합니다.")
                break
            
            # 유효한 좌표 생성
            result = self.generate_valid_coordinate(mode, sido_name)
            
            if result:
                lat, lon, addr_info = result
                successful += 1
                
                if show_progress:
                    print(f"[{successful}/{count}] 유효한 좌표 발견: ({lat}, {lon}) - {addr_info['area1']} {addr_info['area2']}")
                
                coord_info.append({
                    "순번": successful,
                    "좌표": f"({lat},{lon})",
                    "위도": lat,
                    "경도": lon,
                    "주소": addr_info["full_address"],
                    "도로명주소": addr_info["road_address"],
                    "시도": addr_info["area1"],
                    "시군구": addr_info["area2"],
                    "읍면동": addr_info["area3"],
                    "생성시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                
                # API 호출 간격
                time.sleep(0.3)
        
        df = pd.DataFrame(coord_info)
        
        if save_path:
            df.to_csv(save_path, index=False, encoding='utf-8-sig')
            if show_progress:
                print(f"좌표 정보 저장 완료: {save_path}")
        
        return df


# CLI 실행용
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="대한민국 내 랜덤 좌표 생성")
    parser.add_argument("--count", type=int, default=1, help="생성할 좌표 개수")
    parser.add_argument("--mode", choices=["korea_random", "sido"], default="korea_random", help="생성 모드")
    parser.add_argument("--sido", type=str, help="시도명 (mode=sido일 때 필요)")
    parser.add_argument("--output", type=str, help="출력 CSV 파일 경로")
    parser.add_argument("--client-id", type=str, help="Naver API Client ID")
    parser.add_argument("--client-secret", type=str, help="Naver API Client Secret")
    parser.add_argument("--shp-path", type=str, help="시도 경계 SHP 파일 경로")
    
    args = parser.parse_args()
    
    # 생성기 초기화
    generator = CoordinateGenerator(
        client_id=args.client_id,
        client_secret=args.client_secret,
        shp_path=args.shp_path
    )
    
    # 좌표 생성
    df = generator.generate_coordinate_info(
        count=args.count,
        mode=args.mode,
        sido_name=args.sido,
        save_path=args.output
    )
    
    # 결과 출력
    print("\n=== Generated Coordinates ===")
    print(df.to_string(index=False))