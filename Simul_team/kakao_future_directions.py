import requests
from datetime import datetime, timedelta
import json

# API 설정
REST_API_KEY = "3b91fc5ac9a331ee70cc707e56760b57"
API_URL = "https://apis-navi.kakaomobility.com/v1/future/directions"

# 출발지: 인하대후문 (경도, 위도 순서)
origin = "126.655959,37.451287"

# 도착지: 구로중앙하이츠 (경도, 위도 순서)
destination = "126.879946,37.498529"

# 오늘 오후 6시 (18:00)
today = datetime.now()
departure_datetime = today.replace(hour=12, minute=0, second=0, microsecond=0)

# 만약 현재 시각이 이미 오후 6시를 넘었다면, 내일 오후 6시로 설정
if datetime.now() >= departure_datetime:
    departure_datetime = departure_datetime + timedelta(days=1)

# YYYYMMDDHHMM 형식으로 변환
departure_time = departure_datetime.strftime("%Y%m%d%H%M")

print(f"출발 시간: {departure_datetime.strftime('%Y년 %m월 %d일 %H시 %M분')}")
print(f"출발지: 인하대후문 (37.451287, 126.655959)")
print(f"도착지: 구로중앙하이츠 (37.498529, 126.879946)")
print("-" * 60)

# 헤더 설정
headers = {
    "Authorization": f"KakaoAK {REST_API_KEY}",
    "Content-Type": "application/json"
}

# 요청 파라미터
params = {
    "origin": origin,
    "destination": destination,
    "departure_time": departure_time,
    "priority": "RECOMMEND",  # 추천 경로
    "car_fuel": "GASOLINE",   # 휘발유
    "car_hipass": "false",    # 하이패스 없음
    "alternatives": "false",   # 대체 경로 미제공
    "road_details": "false"   # 상세 도로 정보 미제공
}

# API 요청
try:
    print("API 요청 중...")
    response = requests.get(API_URL, headers=headers, params=params)

    # 응답 확인
    if response.status_code == 200:
        data = response.json()

        # 응답 전체 저장 (참고용)
        with open('kakao_future_directions_response.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("✓ 전체 응답이 'kakao_future_directions_response.json' 파일로 저장되었습니다.\n")

        # 주요 정보 출력
        if 'routes' in data and len(data['routes']) > 0:
            route = data['routes'][0]  # 첫 번째 경로 정보
            summary = route.get('summary', {})

            print("=" * 60)
            print("📍 미래 운행 경로 정보")
            print("=" * 60)

            # 거리
            distance = summary.get('distance', 0)
            print(f"🚗 총 거리: {distance:,} m ({distance/1000:.2f} km)")

            # 소요 시간
            duration = summary.get('duration', 0)
            hours = duration // 3600
            minutes = (duration % 3600) // 60
            print(f"⏱️  예상 소요 시간: {hours}시간 {minutes}분 ({duration}초)")

            # 요금 정보
            fare = summary.get('fare', {})
            if fare:
                toll = fare.get('toll', 0)
                taxi = fare.get('taxi', 0)
                print(f"💰 통행료: {toll:,}원")
                print(f"🚕 택시 예상 요금: {taxi:,}원")

            # 출발/도착 시간
            origin_info = route.get('summary', {}).get('origin', {})
            destination_info = route.get('summary', {}).get('destination', {})

            print(f"\n🏁 출발 시각: {departure_datetime.strftime('%Y-%m-%d %H:%M')}")
            arrival_time = departure_datetime + timedelta(seconds=duration)
            print(f"🏁 도착 예상 시각: {arrival_time.strftime('%Y-%m-%d %H:%M')}")

            print("=" * 60)

    else:
        print(f"❌ API 요청 실패")
        print(f"상태 코드: {response.status_code}")
        print(f"응답: {response.text}")

except Exception as e:
    print(f"❌ 오류 발생: {str(e)}")
