"""
batch_runner.py
한국 좌표 1000개 배치 실험 러너 (시나리오 생성 + 시뮬레이션 자동 파이프라인)

파이프라인 (좌표 1개당):
    1. Orchestrator.generate_scenario()  ← Kakao API 호출 → scenario CSV + YAML 생성
    2. Orchestrator.run_simulation()     ← 시뮬레이션 실행 (API 없음)
    3. progress.json 업데이트

API 제한 처리:
    - 하루 예산(--daily-limit) 소진 전에는 처리할 좌표 수를 사전 계산하여 제한
    - generate_scenario 도중 API 오류(429, timeout 등)로 subprocess가 비정상 종료되면
      RuntimeError 또는 returncode != 0 으로 감지 → 해당 좌표 failed 처리
    - 다음 실행 시 failed 좌표는 자동으로 재시도 (--max-retries 한도 내)

Usage (매일 동일 명령, progress.json에서 자동 이어서 실행):
    python experiment_1/batch_runner.py \
        --base-path C:/Users/User/MCI_ADV \
        --coords experiment_1/coords_korea_1000.csv \
        --progress experiment_1/progress.json \
        --kakao-api-key YOUR_KEY \
        --experiment-id exp_batch_research \
        --daily-limit 4900 --calls-per-coord 55 \
        --incident-size 30 --amb-count 30 --uav-count 3 \
        --amb-velocity 40 --uav-velocity 80 \
        --total-samples 10 --random-seed 42

진행 현황만 확인:
    python experiment_1/batch_runner.py --status \
        --progress experiment_1/progress.json
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 프로젝트 경로 설정 (Orchestrator import)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCE_SRC = _PROJECT_ROOT / "src" / "sce_src"
if str(_SCE_SRC) not in sys.path:
    sys.path.insert(0, str(_SCE_SRC))

KST = timezone(timedelta(hours=9))


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="MCI 배치 실험 러너")

    # 경로
    p.add_argument("--base-path",   default=str(_PROJECT_ROOT),
                   help="프로젝트 루트 경로")
    p.add_argument("--coords",      default="experiment_1/coords_korea.csv",
                   help="좌표 CSV 경로 (기본: experiment_1/coords_korea.csv)")
    p.add_argument("--progress",    default="experiment_1/progress.json",
                   help="진행 상태 JSON 경로 (기본: experiment_1/progress.json)")

    # API
    p.add_argument("--kakao-api-key", default="", help="Kakao REST API 키")
    p.add_argument("--departure-time", default="",
                   help="Kakao 길찾기 출발시간 (YYYYMMDDHHmm, 선택)")

    # ── 실험 식별 ──────────────────────────────────────────────────────────
    p.add_argument("--experiment-id",  default="exp_batch_research",
                   help="실험 ID (scenarios/ 하위 폴더명 및 progress.json 식별자)")

    # ── 공통 시나리오/시뮬레이션 파라미터 ─────────────────────────────────
    p.add_argument("--incident-size",  type=int,   default=30,
                   help="사고 현장 환자 수 (기본: 30)")
    p.add_argument("--amb-count",      type=int,   default=30,
                   help="출동 구급차 수 (기본: 30)")
    p.add_argument("--uav-count",      type=int,   default=3,
                   help="출동 UAV 수 (기본: 3)")
    p.add_argument("--amb-velocity",   type=int,   default=40,
                   help="구급차 평균 속도 km/h (기본: 40)")
    p.add_argument("--uav-velocity",   type=int,   default=80,
                   help="UAV 평균 속도 km/h (기본: 80)")
    p.add_argument("--total-samples",  type=int,   default=10,
                   help="시뮬레이션 반복 횟수 (기본: 10)")
    p.add_argument("--random-seed",    type=int,   default=42,
                   help="랜덤 시드 (기본: 42)")

    # ── 이송 시간 파라미터 ────────────────────────────────────────────────
    p.add_argument("--amb-handover-time", type=float, default=0.0,
                   help="구급차 환자 인계시간 분 (기본: 0.0)")
    p.add_argument("--uav-handover-time", type=float, default=0.0,
                   help="UAV 환자 인계시간 분 (기본: 0.0)")
    p.add_argument("--is-use-time",    type=str,   default="true",
                   help="Kakao API duration 사용 여부 true/false (기본: true)")
    p.add_argument("--duration-coeff", type=float, default=1.0,
                   help="API duration 시간 가중치 (기본: 1.0)")

    # ── 병원 할당 파라미터 ────────────────────────────────────────────────
    p.add_argument("--hospital-max-send-coeff", type=str, default=None,
                   help="병원 전송계수 'a,b' 형식 (예: 1.1,1.0). 미입력 시 기본값 사용")
    p.add_argument("--buffer-ratio",   type=float, default=None,
                   help="후보 병원 버퍼 배수 (기본값은 make_csv_yaml_dynamic 내부 기본값 사용)")
    p.add_argument("--util-by-tier",   type=str,   default=None,
                   help="병원 등급별 이용률 '1:0.90,11:0.75,etc:0.60' 형식")

    # 배치 제어
    p.add_argument("--daily-limit",    type=int, default=4900,
                   help="하루 최대 Kakao API 호출 수 (기본: 4900)")
    p.add_argument("--calls-per-coord", type=int, default=55,
                   help="좌표 1개당 예상 API 호출 수 (기본: 55)")
    p.add_argument("--max-retries",    type=int, default=2,
                   help="좌표당 최대 재시도 횟수 (기본: 2)")

    # 모드
    p.add_argument("--dry-run",  action="store_true",
                   help="API 호출 없이 처리 예정 목록만 출력")
    p.add_argument("--status",   action="store_true",
                   help="진행 현황만 출력 후 종료")

    return p.parse_args()


# ---------------------------------------------------------------------------
# 좌표 CSV 로드
# ---------------------------------------------------------------------------

def load_coords(coords_path: str) -> dict:
    """coord_id → {latitude, longitude} 딕셔너리 반환"""
    path = _resolve_path(coords_path)
    if not path.exists():
        print(f"[ERROR] 좌표 CSV를 찾을 수 없습니다: {path}")
        sys.exit(1)

    coords = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = str(int(row["coord_id"]))
            coords[cid] = {
                "latitude":  float(row["latitude"]),
                "longitude": float(row["longitude"]),
            }
    return coords


# ---------------------------------------------------------------------------
# progress.json 관리
# ---------------------------------------------------------------------------

def _resolve_path(rel_or_abs: str) -> Path:
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p
    return _PROJECT_ROOT / p


def load_progress(progress_path: str, experiment_id: str, total: int) -> dict:
    path = _resolve_path(progress_path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data

    # 최초 생성
    return {
        "experiment_id": experiment_id,
        "total": total,
        "statuses": {str(i): {"status": "pending"} for i in range(1, total + 1)},
        "api_log": [],
    }


def save_progress(data: dict, progress_path: str):
    """Atomic write: .tmp 파일에 쓴 뒤 os.replace()"""
    path = _resolve_path(progress_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# 진행 통계
# ---------------------------------------------------------------------------

def calc_stats(progress: dict) -> dict:
    statuses = progress.get("statuses", {})
    total = progress.get("total", len(statuses))

    done        = sum(1 for v in statuses.values() if v.get("status") == "done")
    sim_ok      = sum(1 for v in statuses.values()
                      if v.get("status") == "done" and v.get("sim_ok", False))
    sim_fail    = done - sim_ok
    failed      = sum(1 for v in statuses.values() if v.get("status") == "failed")
    abandoned   = sum(1 for v in statuses.values() if v.get("status") == "abandoned")
    pending     = sum(1 for v in statuses.values()
                      if v.get("status") in ("pending", "running"))

    # 오늘 API 사용량
    today = today_kst()
    today_calls = 0
    today_processed = 0
    for entry in progress.get("api_log", []):
        if entry.get("date") == today:
            today_calls     += entry.get("calls_used", 0)
            today_processed += entry.get("coords_processed", 0)

    return dict(
        total=total, done=done, sim_ok=sim_ok, sim_fail=sim_fail,
        failed=failed, abandoned=abandoned, pending=pending,
        today_calls=today_calls, today_processed=today_processed,
    )


def print_status(progress: dict, daily_limit: int, calls_per_coord: int):
    s = calc_stats(progress)
    today = today_kst()
    print()
    print(f"=== 진행 현황 ({now_kst()}) ===")
    print(f"완료    : {s['done']} / {s['total']}  ({s['done']/s['total']*100:.1f}%)")
    print(f"  ├ 시뮬 성공 : {s['sim_ok']}")
    print(f"  └ 시뮬 실패 : {s['sim_fail']}")
    print(f"오류    : {s['failed']}")
    print(f"중단    : {s['abandoned']}")
    print(f"미처리  : {s['pending']}")
    print(f"오늘 사용 API: {s['today_calls']} / {daily_limit}")
    remaining_budget = daily_limit - s['today_calls']
    can_process = max(0, remaining_budget // calls_per_coord)
    print(f"오늘 잔여 예산: {remaining_budget}콜 → 약 {can_process}개 처리 가능")

    # 최근 처리 좌표
    last_done = None
    last_time = None
    for cid, v in progress.get("statuses", {}).items():
        if v.get("status") == "done" and v.get("finished_at"):
            if last_time is None or v["finished_at"] > last_time:
                last_time = v["finished_at"]
                last_done = cid
    if last_done:
        print(f"최근 처리: coord_id={last_done} @ {last_time}")
    print()


# ---------------------------------------------------------------------------
# 처리 대상 선택
# ---------------------------------------------------------------------------

def select_pending(progress: dict, max_retries: int) -> list:
    """pending + 재시도 가능한 failed 좌표 coord_id 목록 반환 (정렬)"""
    result = []
    for cid, v in progress.get("statuses", {}).items():
        st = v.get("status", "pending")
        if st == "pending":
            result.append(int(cid))
        elif st == "failed":
            if v.get("attempts", 0) < max_retries:
                result.append(int(cid))
    return sorted(result)


# ---------------------------------------------------------------------------
# 단일 좌표 처리
# ---------------------------------------------------------------------------

def process_coord(
    orch,
    coord_id: str,
    lat: float,
    lon: float,
    args,
    progress: dict,
    session_calls: int,
    session_idx: int,
    session_total: int,
) -> tuple:
    """
    좌표 1개에 대해 시나리오 생성 → 시뮬레이션 실행 전체 파이프라인 수행.

    Returns: (updated_progress, api_calls_used, sim_ok: bool)

    API 오류 처리:
        generate_scenario()는 make_csv_yaml_dynamic.py subprocess 실패 시
        RuntimeError를 raise한다 (CONFIG_PATH가 stdout에 없을 때).
        Kakao API 429/timeout 등으로 subprocess가 비정상 종료되면 이 경로를 탄다.
        → try/except로 잡아서 failed 처리, 다음 세션에서 자동 재시도.
    """
    statuses = progress["statuses"]
    cur = statuses.get(coord_id, {"status": "pending"})
    attempts = cur.get("attempts", 0) + 1

    # running 표시
    statuses[coord_id] = {
        "status": "running",
        "attempts": attempts,
        "started_at": now_kst(),
    }

    prefix = f"[{session_idx:3d}/{session_total}] coord_id={coord_id:>4s} ({lat:.4f}, {lon:.4f})"

    # ── 1단계: 시나리오 생성 (Kakao API 호출) ────────────────────────────
    print(f"{prefix}  시나리오 생성 중...")
    t0 = time.time()

    # make_csv_yaml_dynamic.py에 전달할 추가 인수 조립
    # (orchestrator.generate_scenario()의 직접 파라미터에 없는 것들)
    extra_args: dict = {}
    if args.kakao_api_key:
        extra_args["kakao_api_key"] = args.kakao_api_key
    if args.departure_time:
        extra_args["departure_time"] = args.departure_time
    # 이송/시간 파라미터
    extra_args["is_use_time"]       = args.is_use_time
    extra_args["amb_handover_time"] = args.amb_handover_time
    extra_args["uav_handover_time"] = args.uav_handover_time
    extra_args["duration_coeff"]    = args.duration_coeff
    # 병원 할당 파라미터 (None이면 전달하지 않음 → make_csv 내부 기본값 사용)
    if args.hospital_max_send_coeff is not None:
        extra_args["hospital_max_send_coeff"] = args.hospital_max_send_coeff
    if args.buffer_ratio is not None:
        extra_args["buffer_ratio"] = args.buffer_ratio
    if args.util_by_tier is not None:
        extra_args["util_by_tier"] = args.util_by_tier

    try:
        gen_result = orch.generate_scenario(
            latitude=lat,
            longitude=lon,
            incident_size=args.incident_size,
            amb_count=args.amb_count,
            uav_count=args.uav_count,
            amb_velocity=args.amb_velocity,
            uav_velocity=args.uav_velocity,
            total_samples=args.total_samples,
            random_seed=args.random_seed,
            exp_id=args.experiment_id,
            extra_args=extra_args,
        )
    except Exception as exc:
        # API 할당량 초과, 타임아웃, CONFIG_PATH 미출력 등 모든 예외 처리
        gen_elapsed = time.time() - t0
        err = f"{type(exc).__name__}: {str(exc)}"[:300]
        print(f"{prefix}  시나리오 생성 예외 ({gen_elapsed:.1f}초) ✗  {err}")
        statuses[coord_id] = {
            "status": "failed",
            "step": "generate",
            "attempts": attempts,
            "error": err,
            "finished_at": now_kst(),
        }
        return progress, args.calls_per_coord, False

    gen_elapsed = time.time() - t0

    # subprocess 자체는 완료됐지만 returncode != 0 인 경우
    if not gen_result.get("ok"):
        err = (gen_result.get("stderr", "") or "")[:200].strip()
        if not err:
            err = f"returncode={gen_result.get('returncode')}"
        print(f"{prefix}  시나리오 생성 실패 ({gen_elapsed:.1f}초) ✗  {err}")
        statuses[coord_id] = {
            "status": "failed",
            "step": "generate",
            "attempts": attempts,
            "error": err,
            "finished_at": now_kst(),
        }
        return progress, args.calls_per_coord, False

    config_path = gen_result.get("config_path", "")
    print(f"{prefix}  시나리오 완료 ({gen_elapsed:.1f}초) → 시뮬레이션 실행 중...")

    # ── 2단계: 시뮬레이션 실행 (API 호출 없음) ───────────────────────────
    # 시뮬레이션 파라미터(환자수, 구급차수, UAV수, 속도, 반복횟수 등)는
    # generate_scenario() 시점에 YAML에 모두 기록되므로 별도 인수 불필요.
    # main.py는 --config_path 하나만 받아 YAML에서 모든 설정을 읽는다.
    t1 = time.time()
    sim_ok = False
    sim_error = ""
    try:
        sim_result = orch.run_simulation(config_path)
        sim_ok = sim_result.get("ok", False)
        if not sim_ok:
            sim_error = (sim_result.get("stderr", "") or "")[:200].strip()
    except Exception as exc:
        sim_error = f"{type(exc).__name__}: {str(exc)}"[:200]
        print(f"{prefix}  시뮬레이션 예외 ✗  {sim_error}")

    sim_elapsed = time.time() - t1
    total_calls = session_calls + args.calls_per_coord

    status_icon = "[OK]" if sim_ok else "[시뮬 실패]"
    print(f"{prefix}  시뮬레이션 완료 ({sim_elapsed:.1f}초) {status_icon}  "
          f"누적API: {total_calls}/{args.daily_limit}")

    statuses[coord_id] = {
        "status": "done",          # 시뮬 실패여도 시나리오 생성 완료면 done
        "config_path": config_path,
        "sim_ok": sim_ok,
        "attempts": attempts,
        "gen_elapsed_sec": round(gen_elapsed, 1),
        "sim_elapsed_sec": round(sim_elapsed, 1),
        "finished_at": now_kst(),
    }
    if sim_error:
        statuses[coord_id]["sim_error"] = sim_error

    return progress, args.calls_per_coord, sim_ok


# ---------------------------------------------------------------------------
# dry-run 출력
# ---------------------------------------------------------------------------

def print_dry_run(pending_ids: list, coords: dict, daily_limit: int,
                  calls_per_coord: int, today_calls: int):
    remaining_budget = daily_limit - today_calls
    can_process = max(0, remaining_budget // calls_per_coord)
    to_run = pending_ids[:can_process]

    print()
    print("=== [DRY-RUN] 처리 예정 목록 ===")
    print(f"오늘 잔여 예산   : {remaining_budget}콜")
    print(f"처리 가능 좌표 수: {can_process}개 (전체 미처리: {len(pending_ids)}개)")
    print()
    print(f"{'#':>4}  {'coord_id':>8}  {'latitude':>10}  {'longitude':>11}")
    print("-" * 40)
    for i, cid in enumerate(to_run, start=1):
        c = coords.get(str(cid), {})
        print(f"{i:4d}  {cid:8d}  {c.get('latitude', 0):10.6f}  {c.get('longitude', 0):11.6f}")
    if len(pending_ids) > can_process:
        print(f"  ... 이후 {len(pending_ids) - can_process}개는 다음 실행 시 처리")
    print()


# ---------------------------------------------------------------------------
# 메인 배치 루프
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    # 경로 정규화
    coords_path   = _resolve_path(args.coords)
    progress_path = _resolve_path(args.progress)

    # 좌표 로드
    coords = load_coords(str(coords_path))
    total  = len(coords)

    # progress.json 로드 (없으면 신규 생성)
    progress = load_progress(str(progress_path), args.experiment_id, total)

    # ── --status 모드 ──────────────────────────────────────────────────────
    if args.status:
        print_status(progress, args.daily_limit, args.calls_per_coord)
        return

    # ── 처리 대상 선택 ─────────────────────────────────────────────────────
    pending_ids = select_pending(progress, args.max_retries)

    s = calc_stats(progress)
    today_calls = s["today_calls"]
    remaining_budget = args.daily_limit - today_calls
    can_process = max(0, remaining_budget // args.calls_per_coord)
    session_targets = pending_ids[:can_process]

    # ── --dry-run 모드 ─────────────────────────────────────────────────────
    if args.dry_run:
        print_dry_run(pending_ids, coords, args.daily_limit,
                      args.calls_per_coord, today_calls)
        return

    # ── 헤더 출력 ──────────────────────────────────────────────────────────
    est_days = (len(pending_ids) - len(session_targets))
    est_days_str = f"~{est_days // max(len(session_targets), 1) + 1}일" \
                   if session_targets else "N/A"

    print()
    print("=" * 55)
    print("  MCI Batch Runner")
    print("=" * 55)
    print(f"  총 좌표     : {total}")
    print(f"  완료        : {s['done']}  (시뮬 성공 {s['sim_ok']} / 실패 {s['sim_fail']})")
    print(f"  실패(중단)  : {s['failed'] + s['abandoned']}")
    print(f"  미처리      : {s['pending']}")
    print(f"  오늘 예산   : {remaining_budget}콜 → 약 {can_process}개 처리 가능 "
          f"({args.calls_per_coord}콜/좌표 기준)")
    print("-" * 55)

    if not session_targets:
        if remaining_budget <= 0:
            print("  오늘 API 예산 소진. 내일 다시 실행하세요.")
        else:
            print("  처리할 좌표가 없습니다. 모든 좌표가 완료되었거나 재시도 한도 초과.")
        print("=" * 55)
        return

    # ── Orchestrator 초기화 ────────────────────────────────────────────────
    try:
        from orchestrator import Orchestrator
    except ImportError as e:
        print(f"[ERROR] Orchestrator import 실패: {e}")
        print(f"        sys.path에 {_SCE_SRC} 이 포함되어 있는지 확인하세요.")
        sys.exit(1)

    orch = Orchestrator(str(_resolve_path(args.base_path)))

    # ── 배치 처리 루프 ─────────────────────────────────────────────────────
    session_calls      = today_calls
    session_done       = 0
    session_sim_ok     = 0
    session_sim_fail   = 0
    session_failed     = 0
    session_start_time = time.time()

    try:
        for idx, cid in enumerate(session_targets, start=1):
            coord_id = str(cid)
            c = coords.get(coord_id)
            if c is None:
                print(f"[WARN] coord_id={coord_id} 좌표 정보 없음. 건너뜁니다.")
                continue

            progress, calls_used, ok = process_coord(
                orch=orch,
                coord_id=coord_id,
                lat=c["latitude"],
                lon=c["longitude"],
                args=args,
                progress=progress,
                session_calls=session_calls,
                session_idx=idx,
                session_total=len(session_targets),
            )

            session_calls += calls_used
            session_done  += 1
            if progress["statuses"][coord_id]["status"] == "done":
                if ok:
                    session_sim_ok += 1
                else:
                    session_sim_fail += 1
            else:
                session_failed += 1

            # progress.json 즉시 저장 (크래시 안전)
            save_progress(progress, str(progress_path))

            # 예산 초과 체크
            if session_calls >= args.daily_limit:
                print()
                print("[WARN] 오늘 API 예산 소진. 배치 중단.")
                break

    except KeyboardInterrupt:
        print()
        print("[WARN] 사용자 중단 (Ctrl+C). 현재까지 progress.json 저장 완료.")
        save_progress(progress, str(progress_path))

    # ── api_log 업데이트 ───────────────────────────────────────────────────
    today = today_kst()
    api_log = progress.get("api_log", [])
    # 오늘 항목 찾기
    today_entry = next((e for e in api_log if e.get("date") == today), None)
    calls_this_session = session_calls - today_calls
    if today_entry:
        today_entry["calls_used"]       += calls_this_session
        today_entry["coords_processed"] += session_done
    else:
        api_log.append({
            "date":              today,
            "calls_used":        calls_this_session,
            "coords_processed":  session_done,
        })
    progress["api_log"] = api_log
    save_progress(progress, str(progress_path))

    # ── 세션 요약 출력 ─────────────────────────────────────────────────────
    session_elapsed = time.time() - session_start_time
    remaining_after = len(pending_ids) - session_done

    final_stats = calc_stats(progress)
    days_remaining = (remaining_after // max(can_process, 1)) + 1 \
                     if remaining_after > 0 else 0

    print()
    print("-" * 55)
    print(f"  세션 완료: {session_done}개 처리  "
          f"(성공 {session_sim_ok} / 실패 {session_sim_fail + session_failed})")
    print(f"  남은 좌표: {remaining_after} | 예상 잔여 일수: ~{days_remaining}일")
    print(f"  총 소요  : {session_elapsed:.0f}초")
    print(f"  누적 완료: {final_stats['done']} / {total}")
    print("=" * 55)


if __name__ == "__main__":
    main()
