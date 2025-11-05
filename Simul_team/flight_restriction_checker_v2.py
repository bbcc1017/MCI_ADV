"""
V-World 비행금지/제한구역 조회 스크립트 (API 2.0 버전)

================================================================================
API 1.0 vs 2.0 비교 및 버전 구분 이유
================================================================================

【구조적 차이】
1. 엔드포인트 구조
   - 1.0: 데이터셋별 개별 URL (/2ddata/aisresc/, /2ddata/aisprhc/)
   - 2.0: 통합 엔드포인트 (/req/data) + data 파라미터로 구분

2. 파라미터 명명 규칙
   - 1.0: apiKey, geometry, output
   - 2.0: key, geomFilter, format, request (오퍼레이션 개념 도입)

3. 응답 구조
   - 1.0: 단순 데이터 배열 형태
   - 2.0: 메타데이터 포함 (service, status, record, page 정보)

4. 페이지 크기 제한
   - 1.0: 최대 100건/페이지
   - 2.0: 최대 1000건/페이지

【기능적 차이】
1. 2.0의 주요 개선사항
   - 대용량 데이터 조회 가능 (최대 10배 증가)
   - 명확한 상태 코드 제공 (OK/NOT_FOUND/ERROR)
   - 메타데이터로 페이징 정보 명확화
   - RESTful 오퍼레이션 개념 도입 (GetFeature, GetFeatureType)

2. 두 버전을 구분하는 이유
   - 하위 호환성: 기존 1.0 사용 시스템 지원
   - 점진적 마이그레이션: 사용자가 필요에 따라 선택 가능
   - 기능 확장성: 2.0에서 새로운 기능 추가 용이

【사용 권장】
- 기존 시스템 유지보수: 1.0 사용
- 신규 개발 또는 대용량 데이터 처리: 2.0 사용
- 상태 정보가 필요한 경우: 2.0 사용 (status 코드 활용)

================================================================================
"""

import requests
import json
from datetime import datetime

# 설정
API_KEY = "712D5EBF-00BB-35D8-B14F-59F82A50EF39"
TEST_LAT = 37.458819
TEST_LON = 126.634031

# API 2.0 통합 엔드포인트
BASE_URL = "https://api.vworld.kr/req/data"

# 데이터셋 이름
DATA_RESTRICTED = "LT_C_AISRESC"  # 비행제한구역
DATA_PROHIBITED = "LT_C_AISPRHC"  # 비행금지구역


def call_vworld_api_v2(data_name, lon, lat):
    """
    V-World API 2.0 호출

    Args:
        data_name: 데이터셋 이름 (LT_C_AISRESC 또는 LT_C_AISPRHC)
        lon: 경도
        lat: 위도

    Returns:
        dict: API 응답 데이터
    """
    # POINT geometry 필터 생성
    geom_filter = f"POINT({lon} {lat})"

    params = {
        'key': API_KEY,
        'service': 'data',
        'version': '2.0',
        'request': 'GetFeature',
        'data': data_name,
        'geomFilter': geom_filter,
        'format': 'json',
        'size': 1000,  # 최대값
        'page': 1,
        'geometry': 'true',
        'attribute': 'true',
        'crs': 'EPSG:4326'  # WGS84
    }

    try:
        response = requests.get(BASE_URL, params=params, timeout=10)
        response.raise_for_status()

        result = response.json()

        # API 2.0 상태 코드 확인
        status = result.get('response', {}).get('status', 'UNKNOWN')

        if status == 'ERROR':
            error_msg = result.get('response', {}).get('error', {}).get('text', 'Unknown error')
            print(f"❌ API 에러 발생: {error_msg}")
            print(f"   전체 응답: {json.dumps(result, indent=2, ensure_ascii=False)}")
            exit(1)

        return result

    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP 에러 발생: {e}")
        print(f"   상태 코드: {response.status_code}")
        print(f"   응답 내용: {response.text}")
        exit(1)

    except requests.exceptions.RequestException as e:
        print(f"❌ 네트워크 에러 발생: {e}")
        exit(1)

    except json.JSONDecodeError as e:
        print(f"❌ JSON 파싱 에러: {e}")
        print(f"   응답 내용: {response.text}")
        exit(1)


def parse_restricted_area_v2(data):
    """비행제한구역 데이터 파싱 (API 2.0)"""
    if not data:
        return None

    response = data.get('response', {})
    status = response.get('status', 'UNKNOWN')

    # NOT_FOUND는 해당 구역에 포함되지 않음을 의미
    if status == 'NOT_FOUND':
        return None

    # OK인 경우 데이터 추출
    if status != 'OK':
        return None

    result = response.get('result', {})
    features = result.get('featureCollection', {}).get('features', [])

    if not features:
        return None

    results = []
    for feature in features:
        props = feature.get('properties', {})
        results.append({
            '전체라벨': props.get('restricted', 'N/A'),
            '라벨1': props.get('res_lbl_1', 'N/A'),
            '라벨2': props.get('res_lbl_2', 'N/A'),
            '라벨3': props.get('res_lbl_3', 'N/A'),
            '지오메트리타입': feature.get('geometry', {}).get('type', 'N/A')
        })

    # 메타데이터 추가
    record_info = {
        'total_count': response.get('record', {}).get('total', 0),
        'current_count': response.get('record', {}).get('current', 0)
    }

    return {
        'areas': results,
        'metadata': record_info
    }


def parse_prohibited_area_v2(data):
    """비행금지구역 데이터 파싱 (API 2.0)"""
    if not data:
        return None

    response = data.get('response', {})
    status = response.get('status', 'UNKNOWN')

    # NOT_FOUND는 해당 구역에 포함되지 않음을 의미
    if status == 'NOT_FOUND':
        return None

    # OK인 경우 데이터 추출
    if status != 'OK':
        return None

    result = response.get('result', {})
    features = result.get('featureCollection', {}).get('features', [])

    if not features:
        return None

    results = []
    for feature in features:
        props = feature.get('properties', {})
        results.append({
            '전체라벨': props.get('prohibited', 'N/A'),
            '라벨1': props.get('prh_lbl_1', 'N/A'),
            '라벨2': props.get('prh_lbl_2', 'N/A'),
            '라벨3': props.get('prh_lbl_3', 'N/A'),
            '금지타입': props.get('prh_typ', 'N/A'),
            '지오메트리타입': feature.get('geometry', {}).get('type', 'N/A')
        })

    # 메타데이터 추가
    record_info = {
        'total_count': response.get('record', {}).get('total', 0),
        'current_count': response.get('record', {}).get('current', 0)
    }

    return {
        'areas': results,
        'metadata': record_info
    }


def main():
    print("="*80)
    print("V-World 비행금지/제한구역 조회 (API 2.0)")
    print("="*80)
    print(f"조회 좌표: 위도 {TEST_LAT}, 경도 {TEST_LON}")
    print(f"조회 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    print()

    # 1. 비행제한구역 조회
    print("🔍 비행제한구역 조회 중...")
    restricted_data = call_vworld_api_v2(DATA_RESTRICTED, TEST_LON, TEST_LAT)
    restricted_result = parse_restricted_area_v2(restricted_data)

    # 2. 비행금지구역 조회
    print("🔍 비행금지구역 조회 중...")
    prohibited_data = call_vworld_api_v2(DATA_PROHIBITED, TEST_LON, TEST_LAT)
    prohibited_result = parse_prohibited_area_v2(prohibited_data)

    print("✅ API 호출 완료\n")

    # 3. 결과 통합
    combined_result = {
        'metadata': {
            'api_version': '2.0',
            'query_time': datetime.now().isoformat(),
            'coordinates': {
                'latitude': TEST_LAT,
                'longitude': TEST_LON
            }
        },
        'restricted_areas': {
            'raw_response': restricted_data,
            'parsed_data': restricted_result
        },
        'prohibited_areas': {
            'raw_response': prohibited_data,
            'parsed_data': prohibited_result
        }
    }

    # 4. JSON 저장
    json_filename = 'flight_check_result_v2.json'
    with open(json_filename, 'w', encoding='utf-8') as f:
        json.dump(combined_result, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON 파일 저장: {json_filename}")

    # 5. 텍스트 결과 생성
    txt_content = generate_text_report(restricted_result, prohibited_result)

    # 6. TXT 저장
    txt_filename = 'flight_check_result_v2.txt'
    with open(txt_filename, 'w', encoding='utf-8') as f:
        f.write(txt_content)
    print(f"💾 TXT 파일 저장: {txt_filename}")
    print()

    # 7. 콘솔 출력
    print(txt_content)


def generate_text_report(restricted_result, prohibited_result):
    """텍스트 보고서 생성"""
    lines = []
    lines.append("="*80)
    lines.append("비행금지/제한구역 조회 결과 (API 2.0)")
    lines.append("="*80)
    lines.append(f"조회 좌표: 위도 {TEST_LAT}, 경도 {TEST_LON}")
    lines.append(f"조회 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("="*80)
    lines.append("")

    # 비행금지구역 결과
    lines.append("【비행금지구역 (Prohibited Areas)】")
    lines.append("-" * 80)
    if prohibited_result and prohibited_result.get('areas'):
        areas = prohibited_result['areas']
        metadata = prohibited_result['metadata']
        lines.append(f"✋ 발견된 비행금지구역 수: {len(areas)}개")
        lines.append(f"   (전체: {metadata['total_count']}개, 현재 페이지: {metadata['current_count']}개)")
        lines.append("")
        for i, area in enumerate(areas, 1):
            lines.append(f"  [{i}] {area['전체라벨']}")
            lines.append(f"      - 라벨1: {area['라벨1']}")
            lines.append(f"      - 라벨2: {area['라벨2']}")
            lines.append(f"      - 라벨3: {area['라벨3']}")
            lines.append(f"      - 금지타입: {area['금지타입']}")
            lines.append(f"      - 지오메트리: {area['지오메트리타입']}")
            lines.append("")
    else:
        lines.append("✅ 비행금지구역에 해당하지 않습니다.")
        lines.append("")

    # 비행제한구역 결과
    lines.append("【비행제한구역 (Restricted Areas)】")
    lines.append("-" * 80)
    if restricted_result and restricted_result.get('areas'):
        areas = restricted_result['areas']
        metadata = restricted_result['metadata']
        lines.append(f"⚠️  발견된 비행제한구역 수: {len(areas)}개")
        lines.append(f"   (전체: {metadata['total_count']}개, 현재 페이지: {metadata['current_count']}개)")
        lines.append("")
        for i, area in enumerate(areas, 1):
            lines.append(f"  [{i}] {area['전체라벨']}")
            lines.append(f"      - 라벨1: {area['라벨1']}")
            lines.append(f"      - 라벨2: {area['라벨2']}")
            lines.append(f"      - 라벨3: {area['라벨3']}")
            lines.append(f"      - 지오메트리: {area['지오메트리타입']}")
            lines.append("")
    else:
        lines.append("✅ 비행제한구역에 해당하지 않습니다.")
        lines.append("")

    # 최종 결론
    lines.append("="*80)
    lines.append("【최종 결론】")
    lines.append("="*80)

    prohibited_areas = prohibited_result.get('areas') if prohibited_result else None
    restricted_areas = restricted_result.get('areas') if restricted_result else None

    if prohibited_areas:
        lines.append("🚫 이 지역은 비행금지구역입니다.")
        lines.append("   드론 비행이 전면 금지됩니다.")
    elif restricted_areas:
        lines.append("⚠️  이 지역은 비행제한구역입니다.")
        lines.append("   특정 조건 하에서만 비행이 가능하며, 사전 승인이 필요할 수 있습니다.")
    else:
        lines.append("✅ 이 지역은 비행 가능 구역입니다.")
        lines.append("   비행금지/제한구역에 해당하지 않으나, 기타 법규를 준수하시기 바랍니다.")

    lines.append("="*80)

    return "\n".join(lines)


if __name__ == "__main__":
    main()
