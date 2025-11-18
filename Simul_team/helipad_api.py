import requests
import math

VWORLD_KEY = "712D5EBF-00BB-35D8-B14F-59F82A50EF39"  # vworld API key

# 사고 위치 (위도, 경도)
ACC_LAT = 37.451287
ACC_LON = 126.655959

def haversine(lat1, lon1, lat2, lon2):
    """두 점(위도/경도) 사이 거리(km) 계산"""
    R = 6371.0  # km
    rad = math.radians
    dlat = rad(lat2 - lat1)
    dlon = rad(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def fetch_nearby_helipads(lat, lon, buffer_m=30000, max_results=5):
    """
    사고 위치(lat, lon) 주변 헬기장 조회 후
    거리 가까운 순서로 max_results개 반환
    """
    url = "https://api.vworld.kr/req/data"

    # vworld는 geomFilter=POINT(x y)에서 x=경도, y=위도
    geom_filter = f"POINT({lon} {lat})"

    columns = ",".join([
        "x", "y", "long", "lat", "org_nam", "str_use", "str_nam", "str_adr",
        "stt_cde", "alt_val", "int_len", "int_grd", "sht_grd",
        "lnd_siz", "pad_siz", "hor_rad", "com_dat", "use_dat",
        "use_typ", "ag_geom"
    ])

    params = {
        "service": "data",
        "request": "GetFeature",
        "data": "LT_P_AISHCSTRIP",
        "key": VWORLD_KEY,
        "format": "json",
        "size": 1000,           # 일단 넉넉히 가져온 뒤 파이썬에서 5개만 추림
        "geomFilter": geom_filter,
        "buffer": buffer_m,     # m 단위 (예: 30000m = 30km)
        "crs": "EPSG:4326",
        "columns": columns,
        "geometry": "true",
        "attribute": "true"
        # "domain": "http://localhost"  # 브라우저 직접 호출이면 필요, 서버/파이썬이면 보통 생략
    }

    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    # vworld는 실제 정보가 data["response"] 아래에 있음
    root = data.get("response", {})

    if root.get("status") != "OK":
        # 에러 내용은 root 쪽만 봐도 충분
        raise RuntimeError(f"VWorld API 오류: {root}")

    # helipad 결과는 root["result"] 안에 있음
    result = root.get("result")
    if result is None:
        raise RuntimeError("result 필드 없음")

    # 보통 featureCollection 안에 features가 들어 있음
    fc = result.get("featureCollection")
    if fc is None:
        raise RuntimeError("featureCollection 없음")

    features = fc.get("features", [])
    if not features:
        raise RuntimeError("features가 비어 있음")


    records = []
    for feat in features:
        props = feat.get("properties", {})
        x = props.get("x")
        y = props.get("y")

        # x,y가 없으면 스킵
        if x is None or y is None:
            continue

        # x=경도, y=위도 (이미 EPSG:4326)
        distance_km = haversine(lat, lon, float(y), float(x))

        record = {
            "X좌표": props.get("x"),
            "Y좌표": props.get("y"),
            "경도": props.get("long"),
            "위도": props.get("lat"),
            "제공처": props.get("org_nam"),
            "사용여부": props.get("str_use"),
            "명칭": props.get("str_nam"),
            "주소": props.get("str_adr"),
            "구분": props.get("stt_cde"),
            "표고": props.get("alt_val"),
            "진입구역길이": props.get("int_len"),
            "진입표면경사": props.get("int_grd"),
            "전이표면경사": props.get("sht_grd"),
            "착륙대": props.get("lnd_siz"),
            "패드": props.get("pad_siz"),
            "수평표면반경": props.get("hor_rad"),
            "설치허가일": props.get("com_dat"),
            "사용개시일": props.get("use_dat"),
            "운용방법": props.get("use_typ"),
            "공간정보객체": props.get("ag_geom"),
            "거리_km": distance_km,
        }
        records.append(record)

    # 거리 기준으로 정렬 후 상위 N개만
    records.sort(key=lambda r: r["거리_km"])
    return records[:max_results]

# -*- coding: utf-8 -*-

def print_helipads_pretty(records, acc_lat=ACC_LAT, acc_lon=ACC_LON):
    """헬기장 리스트를 이모지와 함께 보기 좋게 출력 (X/Y, 경도/위도 구분)"""

    if not records:
        print("🚨 주변 반경 내에 조회된 헬기장이 없습니다.")
        return

    print("======================================")
    print("🚨 사고 위치 정보")
    print("======================================")
    print(f"📌 위도(lat) : {acc_lat}")
    print(f"📌 경도(lon) : {acc_lon}")
    print()

    print("======================================")
    print(f"🚁 주변 헬기장 {len(records)}개 (거리 기준 정렬)")
    print("======================================")

    for idx, r in enumerate(records, start=1):
        # 기본 정보
        name = (r.get("명칭") or "").strip()
        addr = (r.get("주소") or "").strip()
        use_yn = (r.get("사용여부") or "").strip()
        org = (r.get("제공처") or "").strip()
        typ = (r.get("구분") or "").strip()
        alt = r.get("표고")
        dist = r.get("거리_km")

        # 좌표 관련 (둘 다 구분해서 표시)
        # 👉 X/Y는 십진수 좌표, 경도/위도는 도·분·초 문자열이라고 가정
        x = r.get("X좌표") or r.get("x")
        y = r.get("Y좌표") or r.get("y")
        lon_dms = r.get("경도") or r.get("long")
        lat_dms = r.get("위도") or r.get("lat")

        pad = r.get("패드")
        lnd = r.get("착륙대")
        use_typ = r.get("운용방법")

        print()
        print(f"----------------- 🛰️ 헬기장 #{idx} -----------------")
        print(f"🚁 명칭             : {name if name else '(이름 없음)'}")
        print(f"📍 주소             : {addr if addr else '(주소 정보 없음)'}")
        print(f"🏢 제공처           : {org if org else '-'}")
        print(f"⚙️  구분 / 사용여부   : {typ if typ else '-'} / {use_yn if use_yn else '-'}")

        # ✅ 좌표 구분해서 표시
        print("🧭 좌표(십진수 X/Y)  : ", end="")
        if x is not None and y is not None:
            print(f"X = {x},  Y = {y}")
        else:
            print("-")

        print("🗺  좌표(경도/위도 DMS): ", end="")
        if lon_dms and lat_dms:
            print(f"{lon_dms} , {lat_dms}")
        else:
            print("-")

        if dist is not None:
            print(f"📏 사고지점까지 거리   : {dist:.2f} km")
        else:
            print("📏 사고지점까지 거리   : -")

        print(f"⛰  표고               : {alt} m" if alt else "⛰  표고               : -")
        print(f"🛬 착륙대 크기         : {lnd if lnd else '-'}")
        print(f"🎯 패드 크기           : {pad if pad else '-'}")
        print(f"🕹  운용방법           : {use_typ if use_typ else '-'}")

    print()
    print("✅ 조회 완료: 주변 헬기장 정보를 위와 같이 확인할 수 있습니다.")

if __name__ == "__main__":
    helipads = fetch_nearby_helipads(ACC_LAT, ACC_LON, buffer_m=30000, max_results=5)
    print_helipads_pretty(helipads, acc_lat=ACC_LAT, acc_lon=ACC_LON)


