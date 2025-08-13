import requests
from math import radians, sin, cos, sqrt, atan2

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def get_naver_route_info(start_x, start_y, end_x, end_y, client_id, client_secret):
    url = "https://maps.apigw.ntruss.com/map-direction/v1/driving"
    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
    }
    params = {
        "start": f"{start_x},{start_y}",
        "goal": f"{end_x},{end_y}",
        "option": "trafast",
        "summary": "true",
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status() 
        data = r.json()["route"]["trafast"][0]
        summary = data["summary"]
        sections = data.get("section", [])
        path = data.get("path", [])
        return summary, sections, path
    except requests.exceptions.RequestException as e:
        print(f"API 호출 오류: {e}")
        return None, None, None
    except (KeyError, IndexError) as e:
        print(f"API 응답 데이터 파싱 오류: {e}")
        return None, None, None