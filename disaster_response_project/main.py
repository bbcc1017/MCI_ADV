import time
import config
from data_processor import process_hospital_data, process_ems_data
from map_creator import create_disaster_map

def main() -> None:
    """메인 실행 함수"""
    start = time.perf_counter()                

    print("재난 대응 시스템을 시작합니다.")

    # 1. 병원 데이터 처리
    step1 = time.perf_counter()
    print("최적 병원 데이터를 분석 중입니다...")
    df_final_hospitals = process_hospital_data()
    print(f"최종 병원 {len(df_final_hospitals)}곳을 선정했습니다."
          f" (▲ {time.perf_counter() - step1:.2f}s)")

    # 2. 119 안전센터 데이터 처리
    step2 = time.perf_counter()
    print("출동 가능한 119 안전센터를 분석 중입니다...")
    df_selected_ems = process_ems_data()
    print(f"출동 119 안전센터 {len(df_selected_ems)}곳을 선정했습니다."
          f" (▲ {time.perf_counter() - step2:.2f}s)")

    # 3. 지도 생성 및 저장
    step3 = time.perf_counter()
    print("통합 재난 지도를 생성 중입니다...")
    create_disaster_map(df_final_hospitals, df_selected_ems)
    print(f"지도 생성 완료 (▲ {time.perf_counter() - step3:.2f}s)")

    total = time.perf_counter() - start        
    print(f"모든 프로세스가 완료되었습니다. 총 소요 시간: {total:.2f}초")

if __name__ == "__main__":
    main()
