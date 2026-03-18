"""
generate_coords.py
한국 육지 경계(shapefile) 내 랜덤 좌표 N개 생성 → CSV + folium 지도 저장

Usage:
    python experiment_1/generate_coords.py [--n 1000] [--seed 42] \
        [--shp ctprvn.shp] [--out experiment_1/coords_korea_1000.csv]

shapefile(ctprvn.shp/.shx/.dbf)은 experiment_1/ 폴더에 위치해야 합니다.
"""

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

# 스크립트가 위치한 디렉터리 (experiment_1/)
_SCRIPT_DIR = Path(__file__).resolve().parent
# 프로젝트 루트 (MCI_ADV/)
_PROJECT_ROOT = _SCRIPT_DIR.parent


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="한국 육지 경계 내 랜덤 좌표 생성")
    parser.add_argument("--n",    type=int,   default=1000,
                        help="생성할 좌표 수 (기본: 1000)")
    parser.add_argument("--seed", type=int,   default=42,
                        help="랜덤 시드 (기본: 42)")
    parser.add_argument("--shp",  type=str,   default="ctprvn.shp",
                        help="shapefile 경로 (기본: ctprvn.shp, experiment_1/ 폴더 기준)")
    parser.add_argument("--out",  type=str,   default="experiment_1/coords_korea.csv",
                        help="출력 CSV 경로 (프로젝트 루트 기준)")
    parser.add_argument("--map",  type=str,   default="",
                        help="folium HTML 출력 경로 (기본: <out_dir>/coords_map.html)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 좌표 생성
# ---------------------------------------------------------------------------

def load_korea_boundary(shp_path: str):
    """shapefile → WGS84 단일 폴리곤 반환"""
    try:
        import geopandas as gpd
    except ImportError:
        print("[ERROR] geopandas가 설치되지 않았습니다. pip install geopandas 를 실행하세요.")
        sys.exit(1)

    shp_path = Path(shp_path)
    if not shp_path.exists():
        print(f"[ERROR] shapefile을 찾을 수 없습니다: {shp_path}")
        sys.exit(1)

    print(f"[1/4] shapefile 로드 중: {shp_path}")
    korea = gpd.read_file(str(shp_path))
    # CRS가 없는 경우(naive geometry) EPSG:5179 수동 지정
    if korea.crs is None:
        korea = korea.set_crs(epsg=5179)
    korea_wgs84 = korea.to_crs(epsg=4326)         # WGS84 변환
    korea_union = korea_wgs84.geometry.union_all() # 남한 전체 경계 단일 폴리곤
    print(f"      CRS: {korea_wgs84.crs} → EPSG:4326 변환 완료")
    print(f"      bounds: {korea_union.bounds}")
    return korea_union


def generate_points(korea_union, n: int, seed: int) -> list:
    """Rejection Sampling으로 경계 내 좌표 n개 생성"""
    try:
        import numpy as np
        from shapely.geometry import Point
    except ImportError as e:
        print(f"[ERROR] 필요 패키지 없음: {e}")
        sys.exit(1)

    rng = np.random.default_rng(seed)
    minx, miny, maxx, maxy = korea_union.bounds
    pts = []
    batch = max(n * 4, 10_000)  # bounding box 내 hit rate ≈ 25~30%

    print(f"[2/4] 좌표 생성 중 (n={n}, seed={seed}) ...")
    while len(pts) < n:
        lons = rng.uniform(minx, maxx, batch)
        lats = rng.uniform(miny, maxy, batch)
        for lat, lon in zip(lats, lons):
            if korea_union.contains(Point(lon, lat)):
                pts.append((lat, lon))
                if len(pts) % 100 == 0:
                    print(f"      {len(pts)}/{n}")
                if len(pts) >= n:
                    break

    print(f"      {n}개 생성 완료")
    return pts[:n]


# ---------------------------------------------------------------------------
# CSV 저장
# ---------------------------------------------------------------------------

def save_csv(pts: list, out_path: str):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"[3/4] CSV 저장: {out_path}")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["coord_id", "latitude", "longitude", "generated_at"])
        for i, (lat, lon) in enumerate(pts, start=1):
            writer.writerow([i, round(lat, 8), round(lon, 8), generated_at])
    print(f"      {len(pts)}행 저장 완료")


# ---------------------------------------------------------------------------
# folium 시각화
# ---------------------------------------------------------------------------

def save_map(pts: list, map_path: str):
    try:
        import folium
    except ImportError:
        print("[WARN] folium이 없어 지도 생성을 건너뜁니다. pip install folium")
        return

    map_path = Path(map_path)
    map_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[4/4] folium 지도 저장: {map_path}")
    center_lat = sum(p[0] for p in pts) / len(pts)
    center_lon = sum(p[1] for p in pts) / len(pts)

    m = folium.Map(location=[center_lat, center_lon], zoom_start=7,
                   tiles="OpenStreetMap")

    for i, (lat, lon) in enumerate(pts, start=1):
        folium.CircleMarker(
            location=[lat, lon],
            radius=3,
            color="#1f77b4",
            fill=True,
            fill_color="#1f77b4",
            fill_opacity=0.7,
            popup=f"coord_id={i}<br>({lat:.6f}, {lon:.6f})",
            tooltip=f"{i}",
        ).add_to(m)

    m.save(str(map_path))
    print(f"      {len(pts)}개 마커 저장 완료")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # shapefile 경로 해석: experiment_1/ → 프로젝트 루트 순서로 탐색
    shp_path = Path(args.shp)
    if not shp_path.is_absolute() and not shp_path.exists():
        for base in (_SCRIPT_DIR, _PROJECT_ROOT):
            candidate = base / args.shp
            if candidate.exists():
                shp_path = candidate
                break

    # 출력 CSV 경로: 상대경로면 프로젝트 루트 기준
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = _PROJECT_ROOT / args.out

    # folium 지도 경로
    map_path: Path
    if not args.map:
        map_path = out_path.parent / "coords_map.html"
    else:
        mp = Path(args.map)
        map_path = mp if mp.is_absolute() else _PROJECT_ROOT / mp

    print("=" * 50)
    print("  한국 육지 경계 내 좌표 생성기")
    print("=" * 50)
    print(f"  n={args.n}, seed={args.seed}")
    print(f"  shp  : {shp_path}")
    print(f"  out  : {out_path}")
    print(f"  map  : {map_path}")
    print("=" * 50)

    korea_union = load_korea_boundary(str(shp_path))
    pts = generate_points(korea_union, args.n, args.seed)
    save_csv(pts, str(out_path))
    save_map(pts, str(map_path))

    print()
    print("=" * 50)
    print(f"  완료! 좌표 {args.n}개 생성")
    print(f"  CSV : {out_path}")
    print(f"  지도 : {map_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
