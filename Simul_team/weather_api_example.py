"""
기상청 초단기예보 API 예제 코드
Ultra Short-term Forecast Weather API Example

API 출처: 기상청_단기예보 ((구)_동네예보) 조회서비스
https://www.data.go.kr/data/15084084/openapi.do
"""

import requests
import math
from datetime import datetime, timedelta
import json

# API 인증키
API_KEY = "0429783e8e9380df65e53818f88e17505dd95235dab97f0694382332d2eccebf"

# 테스트 좌표
TEST_LAT = 37.458819
TEST_LON = 126.634031

# 격자 변환 상수 (Lambert Conformal Conic Projection)
RE = 6371.00877        # 지구 반경(km)
GRID = 5.0             # 격자 간격(km)
SLAT1 = 30.0           # 투영 위도1(degree)
SLAT2 = 60.0           # 투영 위도2(degree)
OLON = 126.0           # 기준점 경도(degree)
OLAT = 38.0            # 기준점 위도(degree)
XO = 43                # 기준점 X좌표(GRID)
YO = 136               # 기준점 Y좌표(GRID)


def lat_lon_to_grid(lat, lon):
    """
    위경도를 기상청 격자 좌표로 변환

    Args:
        lat (float): 위도
        lon (float): 경도

    Returns:
        tuple: (nx, ny) 격자 좌표
    """
    DEGRAD = math.pi / 180.0
    re = RE / GRID

    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon = OLON * DEGRAD
    olat = OLAT * DEGRAD

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = math.pow(sf, sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / math.pow(ro, sn)

    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
    ra = re * sf / math.pow(ra, sn)
    theta = lon * DEGRAD - olon

    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    nx = int(math.floor(ra * math.sin(theta) + XO + 0.5))
    ny = int(math.floor(ro - ra * math.cos(theta) + YO + 0.5))

    return nx, ny


def get_base_time(now=None):
    """
    API 호출을 위한 base_date와 base_time 계산
    초단기예보는 매 시간 30분에 발표되며, 45분 이후 조회 가능

    Args:
        now (datetime): 기준 시간 (None이면 현재 시간 사용)

    Returns:
        tuple: (base_date, base_time) - "YYYYMMDD", "HHmm" 형식
    """
    if now is None:
        now = datetime.now()

    # 현재 시각이 45분 이전이면 이전 시간 데이터 사용
    if now.minute < 45:
        now = now - timedelta(hours=1)

    base_date = now.strftime("%Y%m%d")
    base_time = now.strftime("%H") + "30"  # 매 시간 30분 발표

    return base_date, base_time


def get_weather_emoji(pty, sky):
    """
    강수형태(PTY)와 하늘상태(SKY)에 따른 날씨 이모지 반환

    Args:
        pty (int): 강수형태 (0:없음, 1:비, 2:비/눈, 3:눈, 5:빗방울, 6:빗방울눈날림, 7:눈날림)
        sky (int): 하늘상태 (1:맑음, 3:구름많음, 4:흐림)

    Returns:
        str: 날씨 이모지
    """
    if pty == 0:
        # 강수 없음
        if sky == 1:
            return "☀️"  # 맑음
        elif sky == 3:
            return "⛅"  # 구름많음
        else:
            return "☁️"  # 흐림
    elif pty == 1:
        return "🌧️"  # 비
    elif pty == 2:
        return "🌧️❄️"  # 비/눈
    elif pty == 3:
        return "❄️"  # 눈
    elif pty == 5:
        return "🌦️"  # 빗방울
    elif pty == 6:
        return "🌦️❄️"  # 빗방울눈날림
    elif pty == 7:
        return "🌨️"  # 눈날림
    else:
        return "🌈"  # 기타


def get_wind_direction_emoji(vec):
    """
    풍향에 따른 방향 이모지 반환

    Args:
        vec (float): 풍향 (degree)

    Returns:
        str: 방향 이모지와 텍스트
    """
    directions = [
        (0, 22.5, "북", "⬆️"),
        (22.5, 67.5, "북동", "↗️"),
        (67.5, 112.5, "동", "➡️"),
        (112.5, 157.5, "남동", "↘️"),
        (157.5, 202.5, "남", "⬇️"),
        (202.5, 247.5, "남서", "↙️"),
        (247.5, 292.5, "서", "⬅️"),
        (292.5, 337.5, "북서", "↖️"),
        (337.5, 360, "북", "⬆️")
    ]

    for min_deg, max_deg, direction, emoji in directions:
        if min_deg <= vec < max_deg:
            return f"{emoji} {direction}풍"

    return "💨"


def get_ultra_short_forecast(lat, lon, api_key):
    """
    초단기예보 데이터 조회

    Args:
        lat (float): 위도
        lon (float): 경도
        api_key (str): API 인증키

    Returns:
        dict: 날씨 정보 딕셔너리 또는 None (실패시)
    """
    # 위경도를 격자 좌표로 변환
    nx, ny = lat_lon_to_grid(lat, lon)

    # base_date와 base_time 계산
    base_date, base_time = get_base_time()

    # API 엔드포인트
    url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst"

    # 요청 파라미터
    params = {
        'serviceKey': api_key,
        'pageNo': '1',
        'numOfRows': '100',
        'dataType': 'JSON',
        'base_date': base_date,
        'base_time': base_time,
        'nx': str(nx),
        'ny': str(ny)
    }

    print(f"🔍 API 요청 정보:")
    print(f"   위치: ({lat}, {lon}) → 격자({nx}, {ny})")
    print(f"   발표일시: {base_date} {base_time}")
    print(f"   요청 URL: {url}")
    print(f"   파라미터: {params}\n")

    try:
        # API 호출
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()

        # 응답 헤더 확인
        result_code = data['response']['header']['resultCode']
        result_msg = data['response']['header']['resultMsg']

        if result_code != '00':
            print(f"❌ API 오류: {result_code} - {result_msg}")
            return None

        # 데이터 파싱
        items = data['response']['body']['items']['item']

        # 가장 가까운 예보시간 데이터 추출 (현재 시각 이후 첫 번째 예보)
        weather_data = {}
        fcst_time = None

        for item in items:
            if fcst_time is None:
                fcst_time = item['fcstTime']

            # 같은 예보시간의 데이터만 수집
            if item['fcstTime'] == fcst_time:
                category = item['category']
                value = item['fcstValue']
                weather_data[category] = value

        weather_data['fcstDate'] = items[0]['fcstDate']
        weather_data['fcstTime'] = fcst_time
        weather_data['baseDate'] = base_date
        weather_data['baseTime'] = base_time

        return weather_data

    except requests.exceptions.RequestException as e:
        print(f"❌ 네트워크 오류: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"❌ 데이터 파싱 오류: {e}")
        print(f"응답 데이터: {json.dumps(data, indent=2, ensure_ascii=False)}")
        return None


def display_weather(weather_data):
    """
    날씨 정보를 보기 좋게 출력

    Args:
        weather_data (dict): 날씨 정보 딕셔너리
    """
    if weather_data is None:
        print("❌ 날씨 정보를 가져올 수 없습니다.")
        return

    # 기본 정보
    fcst_date = weather_data.get('fcstDate', 'N/A')
    fcst_time = weather_data.get('fcstTime', 'N/A')
    base_date = weather_data.get('baseDate', 'N/A')
    base_time = weather_data.get('baseTime', 'N/A')

    # 날씨 파라미터
    t1h = weather_data.get('T1H', 'N/A')        # 기온
    rn1 = weather_data.get('RN1', '0')          # 1시간 강수량
    sky = int(weather_data.get('SKY', '1'))     # 하늘상태
    pty = int(weather_data.get('PTY', '0'))     # 강수형태
    reh = weather_data.get('REH', 'N/A')        # 습도
    wsd = weather_data.get('WSD', 'N/A')        # 풍속
    vec = float(weather_data.get('VEC', '0'))   # 풍향

    # 날씨 이모지
    weather_emoji = get_weather_emoji(pty, sky)
    wind_emoji = get_wind_direction_emoji(vec)

    # 하늘 상태 텍스트
    sky_text = {1: "맑음", 3: "구름많음", 4: "흐림"}.get(sky, "알 수 없음")

    # 강수형태 텍스트
    pty_text = {
        0: "없음",
        1: "비",
        2: "비/눈",
        3: "눈",
        5: "빗방울",
        6: "빗방울눈날림",
        7: "눈날림"
    }.get(pty, "알 수 없음")

    # 결과 출력
    print("=" * 60)
    print(f"🌤️  초단기예보 날씨 정보  {weather_emoji}")
    print("=" * 60)
    print(f"📅 발표일시: {base_date[:4]}-{base_date[4:6]}-{base_date[6:8]} {base_time[:2]}:{base_time[2:]}")
    print(f"🕐 예보시각: {fcst_date[:4]}-{fcst_date[4:6]}-{fcst_date[6:8]} {fcst_time[:2]}:{fcst_time[2:]}")
    print("-" * 60)
    print(f"🌡️  기온:       {t1h}°C")
    print(f"{weather_emoji}  하늘상태:   {sky_text}")
    print(f"🌧️  강수형태:   {pty_text}")

    # 강수량 표시 (비가 올 때만)
    if pty in [1, 2, 5, 6] and rn1 != '0':
        if rn1 == '1':
            print(f"💧  강수량:     1mm 미만")
        else:
            print(f"💧  강수량:     {rn1}mm")

    print(f"💧  습도:       {reh}%")
    print(f"💨  풍속:       {wsd}m/s")
    print(f"{wind_emoji.split()[0]}  풍향:       {wind_emoji.split()[1]} ({vec}°)")
    print("=" * 60)

    # 상세 데이터 (디버깅용)
    print("\n📊 상세 데이터:")
    for key, value in weather_data.items():
        if key not in ['fcstDate', 'fcstTime', 'baseDate', 'baseTime']:
            print(f"   {key}: {value}")
    print()


def main():
    """
    메인 함수
    """
    print("🌈 기상청 초단기예보 API 예제")
    print(f"📍 좌표: ({TEST_LAT}, {TEST_LON})\n")

    # 날씨 데이터 조회
    weather = get_ultra_short_forecast(TEST_LAT, TEST_LON, API_KEY)

    # 결과 출력
    display_weather(weather)


if __name__ == "__main__":
    main()
