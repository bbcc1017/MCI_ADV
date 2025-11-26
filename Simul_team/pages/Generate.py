# Generate.py
# 새 시나리오 생성 전용 독립 페이지
# -------------------------------------------------------------------------------------------------
import os, re, yaml, shutil
from datetime import datetime, timezone, timedelta
import streamlit as st
import pandas as pd

KST = timezone(timedelta(hours=9))

# Page config
st.set_page_config(
    page_title="새 시나리오 만들기",
    page_icon="➕",
    layout="wide"
)

# ─────────────────────────────────────────────────────────────────
# 유틸리티 함수
# ─────────────────────────────────────────────────────────────────
def base_ok(bp: str) -> bool:
    """base_path가 유효한지 확인 (scenarios 폴더 존재)"""
    if not bp:
        return False
    scenarios = os.path.join(bp, "scenarios")
    return os.path.isdir(scenarios)

def parse_env_kv(text: str):
    """환경변수 텍스트를 파싱"""
    env = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env

# ─────────────────────────────────────────────────────────────────
# Session State 초기화
# ─────────────────────────────────────────────────────────────────
if "generate_base_path" not in st.session_state:
    st.session_state.generate_base_path = ""
if "gen_state" not in st.session_state:
    st.session_state.gen_state = {}
if "env_txt" not in st.session_state:
    st.session_state.env_txt = ""

# ─────────────────────────────────────────────────────────────────
# 메인 UI
# ─────────────────────────────────────────────────────────────────
st.title("🧪 시나리오 생성 · 실행 (독립 모드)")
st.info("💡 이 페이지는 메인 앱의 사이드바 설정과 **완전히 독립적**으로 작동합니다. 기존 시나리오가 없어도 새로운 시나리오를 생성할 수 있습니다!")

# ─────────────────────────────────────────────────────────────────
# 1. 프로젝트 경로 (base_path) 입력
# ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📁 프로젝트 경로 설정")

col_path, col_btn = st.columns([4, 1])
with col_path:
    generate_bp_input = st.text_input(
        "🗂️ 프로젝트 경로 (base_path)",
        value=st.session_state.generate_base_path,
        placeholder="예: C:\\Users\\사용자명\\MCI_ADV\\Simul_team",
        help="scenarios 폴더가 있는 프로젝트 루트 경로를 입력하세요"
    )
with col_btn:
    st.write("")  # 정렬용
    st.write("")  # 정렬용
    if st.button("✅ 경로 확인", key="gen_check_path"):
        st.session_state.generate_base_path = generate_bp_input

bp = st.session_state.generate_base_path

# 경로 유효성 검사
if not bp:
    st.warning("⚠️ 위에서 프로젝트 경로를 입력하고 **✅ 경로 확인** 버튼을 클릭하세요.")
    st.stop()

if not base_ok(bp):
    st.error(f"❌ 유효하지 않은 경로입니다: `{bp}`")
    st.caption("• 경로가 존재하는지 확인하세요\n• `scenarios` 폴더가 있는지 확인하세요")
    st.stop()

st.success(f"✅ 유효한 경로: `{bp}`")

# ─────────────────────────────────────────────────────────────────
# 2. Orchestrator 로드
# ─────────────────────────────────────────────────────────────────
try:
    from orchestrator import Orchestrator
except Exception as e:
    st.error("❌ orchestrator.py를 프로젝트 루트에 두세요.")
    st.exception(e)
    st.stop()

# ─────────────────────────────────────────────────────────────────
# 3. 시나리오 생성 UI
# ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 1️⃣ 시나리오 생성")

# API 키 입력 (최상단)
kakao_api_key = st.text_input(
    "🔑 카카오 REST API 키 (필수)",
    type="password",
    placeholder="",
    help="카카오 모빌리티 API 키를 입력하세요. 브라우저가 자동완성해줍니다."
)

# 운행시간 모드 선택
st.markdown("#### 📍 운행시간 모드")
time_mode = st.radio(
    "경로 탐색 시점",
    options=["실시간 (현재 교통상황)", "미래시간 (특정 날짜/시간)"],
    index=0,
    horizontal=True
)

# 미래시간 모드일 때만 날짜/시간 선택 UI 표시
departure_time_str = None
if time_mode == "미래시간 (특정 날짜/시간)":
    # session_state에 초기값이 없으면 현재 날짜/시각으로 초기화 (한 번만)
    if "departure_date_init" not in st.session_state:
        st.session_state.departure_date_init = datetime.now(KST).date()
    if "departure_time_init" not in st.session_state:
        st.session_state.departure_time_init = datetime.now(KST).time()

    col_date, col_time = st.columns(2)
    with col_date:
        departure_date = st.date_input(
            "출발 날짜",
            value=st.session_state.departure_date_init,
            help="사고 발생 예상 날짜",
            key="departure_date_input"
        )
        # 사용자가 선택한 값을 저장
        st.session_state.departure_date_init = departure_date
    with col_time:
        departure_time = st.time_input(
            "출발 시각",
            value=st.session_state.departure_time_init,
            help="사고 발생 예상 시각",
            key="departure_time_input"
        )
        # 사용자가 선택한 값을 저장
        st.session_state.departure_time_init = departure_time
    # YYYYMMDDHHMM 형식으로 변환
    departure_time_str = f"{departure_date.strftime('%Y%m%d')}{departure_time.strftime('%H%M')}"
    st.caption(f"→ API 파라미터: `{departure_time_str}`")
else:
    # 실시간 모드: 현재 시각 사용
    departure_time_str = datetime.now(KST).strftime("%Y%m%d%H%M")

# is_use_time 플래그 및 duration_coeff
col_time1, col_time2 = st.columns(2)
with col_time1:
    is_use_time = st.checkbox(
        "✅ API 기반 이송시간 사용 (권장)",
        value=True,
        help="체크: API에서 받은 duration(분) 사용 | 미체크: 거리/속도 기반 계산"
    )
with col_time2:
    duration_coeff = st.number_input(
        "API duration 시간가중치",
        value=1.0,
        min_value=0.1,
        max_value=10.0,
        step=0.1,
        format="%.1f",
        help="API duration에 곱해지는 계수 (기본값: 1.0, 날씨/교통상황 등 환경 요인 반영)"
    )

st.markdown("---")
st.markdown("#### 🔧 시나리오 파라미터")
colA, colB, colC = st.columns(3)
with colA:
    latitude  = st.number_input("위도 (latitude)", value=37.465833, format="%.6f")
    incident_size = st.number_input("환자수 (incident_size)", value=30, min_value=1, step=1)
    amb_velocity  = st.number_input("구급차 속도 (km/h)", value=40, min_value=1, step=1)
    amb_handover_time = st.number_input("구급차 환자 인계시간 (분)", value=0.0, min_value=0.0, step=0.1, format="%.1f", help="현장에서 환자를 싣거나 병원에 내리는 시간")
    total_samples = st.number_input("시뮬레이션 반복 (totalSamples)", value=10, min_value=1, step=1)
with colB:
    longitude = st.number_input("경도 (longitude)", value=126.443333, format="%.6f")
    amb_size  = st.number_input("구급차 수 (amb_size)", value=30, min_value=1, step=1)
    uav_velocity = st.number_input("UAV 속도 (km/h)", value=80, min_value=1, step=1)
    uav_handover_time = st.number_input("UAV 환자 인계시간 (분)", value=0.0, min_value=0.0, step=0.1, format="%.1f", help="현장에서 환자를 싣거나 병원에 내리는 시간")
    random_seed  = st.number_input("랜덤시드", value=0, min_value=0, step=1)
with colC:
    uav_size = st.number_input("UAV 수 (uav_size)", value=3, min_value=0, step=1)
    hospital_max_send_coeff = st.text_input("max_send_coeff (예: 1.05,1)", value="1,1")
    buffer_ratio = st.number_input("buffer_ratio", value=1.5, min_value=1.0, step=0.1)


if st.button("📦 시나리오 생성", key="btn_generate_scenario"):
        # API 키 검증
    if not kakao_api_key or not kakao_api_key.strip():
        st.error("⚠️ 카카오 API 키를 입력하세요!")
        st.stop()

    try:
        env = parse_env_kv(st.session_state.env_txt)
        extra_args = {
            "buffer_ratio": buffer_ratio,
            "hospital_max_send_coeff": hospital_max_send_coeff.strip(),
            "kakao_api_key": kakao_api_key.strip(),
            "departure_time": departure_time_str,
            "is_use_time": str(is_use_time).lower(),  # "true" or "false"
            "amb_handover_time": float(amb_handover_time),
            "uav_handover_time": float(uav_handover_time),
            "duration_coeff": float(duration_coeff)
        }
        orc = Orchestrator(base_path=bp)
        res = orc.generate_scenario(
            latitude=latitude, longitude=longitude,
            incident_size=int(incident_size),
            amb_size=int(amb_size), uav_size=int(uav_size),
            amb_velocity=int(amb_velocity), uav_velocity=int(uav_velocity),
            total_samples=int(total_samples), random_seed=int(random_seed),
            exp_id=None,  # 항상 자동 생성
            extra_env=env, extra_args=extra_args
        )

        # 최신 상태 보관
        st.session_state.gen_state = {
            "exp_id": res["exp_id"],
            "coord": res["coord"],
            "config_path": res["config_path"],
            "summary_csv_path": res["summary_csv_path"],
            "summary_csv_path_legacy": res["summary_csv_path_legacy"],
            "log_file": res["log_file"]
        }

        st.success("✅ 시나리오 생성 완료!")
        st.write(f"• 실험ID: `{res['exp_id']}`")
        st.write(f"• 좌표: `{res['coord']}`")
        st.write(f"• CONFIG_PATH: `{res['config_path']}`")
        st.write(f"• 요약 CSV(신규): `{res['summary_csv_path']}`")
        st.write(f"• 로그 파일: `{res['log_file']}`")

    except Exception as e:
        st.error("❌ 시나리오 생성 중 오류")
        st.exception(e)

# ─────────────────────────────────────────────────────────────────
# 4. 방금 생성한 시나리오 즉시 실행
# ─────────────────────────────────────────────────────────────────
if st.session_state.gen_state and st.session_state.gen_state.get("config_path"):
    st.markdown("---")
    st.markdown("### 2️⃣ 방금 생성한 시나리오 즉시 실행")
    st.info("위에서 생성한 시나리오를 시뮬레이션 실행합니다.")
    st.code(f"CONFIG: {st.session_state.gen_state.get('config_path')}")

    if st.button("▶️ 즉시 시뮬레이션 실행", key="btn_immediate_run"):
        try:
            orc_imm = Orchestrator(base_path=bp)
            res_imm = orc_imm.run_simulation(config_path=st.session_state.gen_state["config_path"])

            # 최신 상태 업데이트
            st.session_state.gen_state.update({
                "exp_id": res_imm["exp_id"],
                "coord": res_imm["coord"],
                "config_path": res_imm["config_path"],
                "summary_csv_path": res_imm["summary_csv_path"],
                "summary_csv_path_legacy": res_imm["summary_csv_path_legacy"],
                "log_file": res_imm["log_file"]
            })

            st.success("✅ 시뮬레이션 완료!")
            st.write(f"• 로그 파일: `{res_imm['log_file']}`")
            st.caption("메인 앱의 Scenarios/Maps 탭에서 바로 확인해 보세요.")

        except Exception as e_imm:
            st.error("❌ 시뮬레이션 실행 중 오류")
            st.exception(e_imm)

st.markdown("---")
st.caption("💡 생성된 시나리오는 메인 앱에서 확인하거나, 아래에서 기존 시나리오를 수정해서 재실행할 수 있습니다.")
