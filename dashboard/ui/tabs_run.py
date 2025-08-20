# ui/tabs_run.py
import os, time, subprocess, numpy as np, streamlit as st
from datetime import datetime
from paths import SCENARIOS_PATH, RESULTS_PATH
from parsers import load_simulation_results, load_experiment_logs

def render_tab(selected_location, scenario_folder, coord_str, scenario_data):
    st.subheader("📊 시뮬레이션 실행 및 모니터링")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🔧 현재 시나리오 설정**")
        cfg = {
            "항목": ["재난 지점", "좌표", "총 환자 수", "구급차 수", "UAV 수", "병원 수"],
            "값": [selected_location,
                   f"({st.session_state['latitude']}, {st.session_state['longitude']})",
                   str(st.session_state['FIXED_PARAMS']['incident_size']),
                   str(len(scenario_data.get('ambulances', []))),
                   str(len(scenario_data.get('uavs', []))),
                   str(len(scenario_data.get('hospitals', [])))],
        }
        import pandas as pd
        st.dataframe(pd.DataFrame(cfg), hide_index=True, use_container_width=True)

        st.markdown("**⚙️ 실행 설정**")
        total_samples = st.number_input("시뮬레이션 횟수", 1, 100, 10)
        _ = st.number_input("랜덤 시드", value=42)

        if st.button("🚀 시뮬레이션 실행", type="primary", use_container_width=True):
            config_path = os.path.join(SCENARIOS_PATH, scenario_folder, f"config_{coord_str}.yaml")
            if os.path.exists(config_path):
                try:
                    ps_command = f'''
                    cd "{os.path.dirname(SCENARIOS_PATH)}"
                    conda activate MCI
                    python main.py --config_path "{config_path}"
                    '''
                    progress = st.progress(0)
                    status = st.empty()
                    status.text("🔄 PowerShell 실행 중...")

                    proc = subprocess.Popen(["powershell", "-Command", ps_command],
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            text=True, cwd=os.path.dirname(SCENARIOS_PATH))
                    for i in range(total_samples):
                        progress.progress((i+1)/total_samples)
                        status.text(f"시뮬레이션 {i+1}/{total_samples} 실행 중...")
                        time.sleep(1)
                    stdout, stderr = proc.communicate()
                    if proc.returncode == 0:
                        status.text("✅ 시뮬레이션 완료!")
                        st.success("성공적으로 완료되었습니다.")
                        st.info(f"결과는 {RESULTS_PATH}/{coord_str} 폴더에 저장됩니다.")
                    else:
                        status.text("❌ 시뮬레이션 실패!")
                        st.error(f"오류: {stderr}")
                except Exception as e:
                    st.error(f"실행 중 오류: {e}")
            else:
                st.error(f"설정 파일을 찾을 수 없습니다: {config_path}")

    with c2:
        st.markdown("**📈 실시간 모니터링**")
        if st.button("📋 실행 로그 보기", type="secondary"):
            log = load_experiment_logs(coord_str)
            if log:
                st.success(f"✅ 로그 파일: {os.path.basename(log['file_path'])}")
                st.info(f"📅 실행 시간: {log['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
                with st.expander("🔍 상세 실행 로그", expanded=True):
                    st.text_area("로그 내용", value=log["content"], height=400, disabled=True)
                    st.download_button("📥 로그 파일 다운로드", data=log["content"],
                        file_name=f"execution_log_{coord_str}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
                        mime="text/plain")
            else:
                st.warning("⚠️ 실행 로그를 찾을 수 없습니다.")

        res = load_simulation_results(coord_str)
        if res and res["rules"]:
            st.success(f"✅ 결과 발견 ({len(res['rules'])}개 규칙)")
            st.info(f"📅 결과 생성: {res['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
            import plotly.graph_objects as go
            if res["survival_rates"]:
                st.metric("최고 생존율", f"{max(res['survival_rates']):.2f}")
                st.metric("평균 생존율", f"{np.mean(res['survival_rates']):.2f}")
            if res["response_times"]:
                st.metric("최단 대응시간", f"{min(res['response_times']):.1f}분")
                st.metric("평균 대응시간", f"{np.mean(res['response_times']):.1f}분")

            if len(res["rules"]) >= 5 and res["survival_rates"]:
                idx = sorted(range(len(res["survival_rates"])),
                             key=lambda i: res["survival_rates"][i], reverse=True)[:5]
                rules = [res["rules"][i] for i in idx]
                rates = [res["survival_rates"][i] for i in idx]
                fig = go.Figure([go.Bar(x=rules, y=rates, marker_color="lightblue")])
                fig.update_layout(title="상위 5개 규칙 생존율", xaxis_tickangle=-45, height=300)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("🔍 시뮬레이션 결과가 없습니다.")
