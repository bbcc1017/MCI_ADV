# MCI_ADV 코드 리뷰 보고서

**작성일**: 2026-04-04  
**검토 범위**: `src/sce_src/`, `src/sim_src/`, `src/vis_src/`, `experiment_1/`  
**검토 목적**: 전체 코드베이스 로직 검증, 버그/비효율/레거시 코드 식별

---

## 1. 요약 (Executive Summary)

| 구분 | Critical | Major | Minor | Info |
|------|----------|-------|-------|------|
| sce_src (시나리오 생성) | 1 | 3 | 4 | 2 |
| sim_src (시뮬레이션) | 1 | 3 | 3 | 2 |
| vis_src (대시보드) | 0 | 4 | 5 | 3 |
| experiment_1 (배치 실험) | 0 | 1 | 2 | 1 |
| **합계** | **2** | **11** | **14** | **8** |

**Critical** = 실행 중 크래시 또는 잘못된 결과 발생 가능  
**Major** = 특정 조건에서 오류 또는 유의미한 품질 저하  
**Minor** = 코드 품질/유지보수성 이슈  
**Info** = 참고 사항 (개선 권장)

---

## 2. sce_src (시나리오 생성 모듈)

### 2.1 [CRITICAL → 해결됨] `make_amb_info()` — 단일 소방서 경로 실패 시 전체 좌표 크래시
- **파일**: `make_csv_yaml_dynamic.py:287+`
- **현상**: 유클리드 거리 기준 최근접 30개 소방서 중 **1개라도** 도로 경로가 불가능하면 `RuntimeError` 발생하여 해당 좌표 전체 시나리오 생성 실패
- **영향 (최초 분석)**: `avoid=ferries` 옵션 존재 시 47개 좌표가 도로 접근 가능임에도 소방서 경로 문제로 실패
- **현재 상태**: `avoid=ferries` 제거 후 재실행하여 **전부 해결됨**. 현재 남은 223개 실패는 전부 사고지점 자체 도로 불가(rc=102)이며, 소방서 경로 문제는 **0건**
- **비고**: 소방서는 모두 건물(도로 위)이므로 소방서 좌표 자체가 도로 불가인 경우는 없음. 문제는 사고지점↔소방서 간 도로 연결(페리 포함) 여부였으며, 페리 허용 후 해소

### 2.2 [MAJOR] 병원 선택 로직 — `pd.concat` 중복 가능성
- **파일**: `make_csv_yaml_dynamic.py` 병원 필터링 로직
- **현상**: Tier별 병원 목록 생성 시 `pd.concat`으로 합칠 때 동일 병원이 중복 포함될 수 있음
- **영향**: 시뮬레이션에서 같은 병원이 2번 등장하여 용량(capacity)이 부풀려질 수 있음
- **권장**: `drop_duplicates(subset=['요양기관명'])` 추가

### 2.3 [MAJOR] CSV 행 수 카운팅 — 헤더 포함 오류
- **파일**: `make_csv_yaml_dynamic.py` — `patient_info.csv` 생성부
- **현상**: CSV 저장 후 행 수 검증 시 헤더를 포함하여 카운트 → 환자 수가 실제보다 1 많게 보고됨
- **영향**: 로그에만 영향 (시뮬레이션에는 영향 없음, pandas가 헤더 자동 인식)
- **권장**: `len(df)` 사용으로 통일

### 2.4 [MAJOR] API 에러 핸들링 — 429(Rate Limit) 재시도 로직 부재
- **파일**: `make_csv_yaml_dynamic.py:153+` `get_road_distance_kakao()` / `get_road_distance_osrm()`
- **현상**: Kakao API 429 응답 시 즉시 실패 처리. 재시도(retry with backoff) 로직 없음
- **영향**: API 할당량 한도 근처에서 간헐적 실패
- **권장**: `tenacity` 또는 수동 exponential backoff 추가
- **업데이트(2026-04)**: OSRM 백엔드 추가에 따라 동일 시그니처의 `get_road_distance_osrm()`이 신설되고, 두 공급자를 `road_provider`(kakao/osrm)로 분기하는 `get_road_distance()` 디스패처가 도입됨. `is_use_time=True`이면 Kakao, `False`이면 OSRM이 자동 선택된다. 또한 기존에 키가 없을 때 silently haversine으로 빠지던 fallback(구 라인 165–169)은 제거되었고, Kakao 모드에서 키가 없으면 즉시 `RuntimeError`로 중단한다(silent degradation 방지).

### 2.5 [MINOR] 하드코딩된 매직 넘버
- `buffer_ratio=1.5` (병원 검색 반경 배율)
- `n_amb=30` (소방서 검색 개수)
- `treat_tier2_mean` Red = `float('inf')` (무한대이지만 의미 불명확한 주석)
- **권장**: 상수를 파일 상단에 `NAMED_CONSTANT`로 정의

### 2.6 [MINOR] `orchestrator.py` — subprocess 호출 시 경로 하드코딩
- **파일**: `orchestrator.py`
- **현상**: `main.py` 경로를 상대경로로 하드코딩. 작업 디렉토리가 바뀌면 실패
- **권장**: `__file__` 기준 절대경로 사용 (현재도 부분적으로 사용 중이나 일관성 부족)

### 2.7 [MINOR] YAML 키 순서 의존성 — 문서화 부재
- `config.yaml`의 `entity_info` 키 순서가 `departure_time → patient → hospital → ambulance → uav`여야 하는데 이것이 어디에도 문서화되지 않음
- `yaml.dump(sort_keys=True)` 사용 시 즉시 크래시 (이미 수정 완료)
- **권장**: config YAML에 주석으로 순서 의존성 명시

### 2.8 [MINOR] `BatchLab.py` — 미사용 파일
- 대시보드에서 import되지 않고 독립 실행 용도로 보이나, `BatchExperiment.py`와 기능 중복
- **권장**: 정리 또는 deprecated 표기

---

## 3. sim_src (시뮬레이션 엔진)

### 3.1 [CRITICAL] `diversion_rule()` — UAV+Red 환자 전원 불가 크래시
- **파일**: `EventManager.py:239-265`
- **현상**: UAV(mode=1) + Red 환자(treat_tier2=False)인 경우, 헬기장 있는 Tier3 병원에만 이송 가능. 해당 병원들의 용량이 모두 소진되면 `Exception("Impossible to divert")` 발생
- **영향**: 1000개 좌표 중 5개(orig_cid 160, 433, 631, 663, 744)에서 확률적 크래시
- **근본 원인 (코드 로직 버그, 병상 부족 아님)**:
  - 5개 좌표 모두 익산/군산 부근 (전라북도)
  - **원광대학교병원**: Tier3 + 헬기장 O → 용량 16 (수술실3 + 병상13) → UAV+Red 전원 **유일한 후보**
  - **전북대학교병원**: Tier3 + 헬기장 X → 용량 19 (수술실3 + 병상16) → `mode==1`(UAV)이므로 **코드에서 제외됨** (line 255: `if mode == 1 and h_idx not in helipad_idx: continue`)
  - 전체 Tier3 용량 = 16+19 = **35병상으로 환자 30명 수용 충분**
  - 그러나 UAV+Red 환자는 원광대 **1곳(16병상)** 에만 갈 수 있고, 다른 중증도 환자가 먼저 채우면 → 전원 불가 → 크래시
  - 64개 규칙 중 Red Action에 UAV가 포함된 48개 규칙에서 발생 가능 (OnlyAMB만 안전)
  - 30회 반복 중 랜덤 시드에 따라 확률적으로 발생
- **크래시 경로**: `main.py:123` → `MCIEnvironment_gymnasium.py:39` → `EventManager.py:508 ev_uav_arrival_hospital()` → `EventManager.py:263 diversion_rule()` → `Exception("Impossible to divert")`
- **권장**: fallback 로직 추가 — 헬기장 제한 완화 (UAV가 인근 착륙 후 지상 이송), 대기 큐, 또는 AMB 모드 전환으로 비헬기장 Tier3 병원 이송

### 3.2 [MAJOR] 디버그 print 문 — 프로덕션 코드에 잔존
- **파일**: `EventManager.py`, `ScenarioManager.py` 다수 위치
- **현상**: `print(f"DEBUG: ...")` 형태의 디버그 출력이 시뮬레이션 루프 내부에 존재
- **영향**: 64규칙 × 30샘플 × 772좌표 = 약 150만회 반복에서 불필요한 stdout 출력 → 성능 저하 및 로그 파일 비대
- **권장**: `logging` 모듈로 전환하여 레벨 제어

### 3.3 [MAJOR] Random seed 관리 — 재현성 불완전
- **파일**: `main.py`, `ScenarioManager.py`
- **현상**: `np.random.seed()`를 전역으로 설정하나, 규칙 순서 변경 시 같은 seed에서도 결과가 달라짐
- **권장**: 각 (rule, sample) 조합마다 독립 seed 할당 (`np.random.RandomState` 인스턴스)

### 3.4 [MAJOR] 전원(diversion) 무한루프 방지 — 부분적 해결
- **파일**: `EventManager.py` `diversion_rule()`
- **현상**: 이전에 idle_capa만 체크하여 두 병원 간 무한 전원이 발생하던 버그는 수정됨 (`n_occupied < max_capa` 조건 추가). 그러나 3개 이상 병원 간 순환 전원은 이론적으로 여전히 가능
- **권장**: 전원 횟수 상한(max_divert_count) 설정 고려

### 3.5 [MINOR] `MCIEnvironment_gymnasium.py` — Gymnasium 인터페이스 미완성
- `action_space`, `observation_space` 정의는 있으나 실제 RL 학습에 사용되지 않음
- `step()` 내부에서 rule-based 로직이 혼재
- **권장**: RL 학습 계획이 없으면 Gymnasium 의존성 제거, 있으면 인터페이스 완성

### 3.6 [MINOR] 이벤트 처리 순서 — heapq 안정성
- **파일**: `EventManager.py`
- **현상**: 같은 시각에 여러 이벤트 발생 시 Python heapq는 tuple의 두 번째 요소로 비교. 이벤트 타입이 비교 불가능한 경우 오류 가능
- **영향**: 현재까지 관찰된 크래시 없음 (tie-breaking이 우연히 작동)
- **권장**: 삽입 순서를 tie-breaker로 추가 `(time, seq_num, event)`

### 3.7 [MINOR] 레거시 주석 코드 다수
- `ScenarioManager.py`, `EventManager.py`에 `# TODO`, `# FIXME`, 주석 처리된 코드 블록 다수
- **권장**: 정리 또는 이슈 트래커로 이관

---

## 4. vis_src (대시보드)

### 4.1 [MAJOR] Bare `except` 절 — 오류 무시
- **파일**: `MCI_Streamlit.py` 다수 위치, `Generate.py:158`, `ResultsCompare.py`
- **현상**: `except:` 또는 `except Exception:` 후 `pass`/`continue`로 모든 에러를 삼킴
- **영향**: 디버깅 어려움, 데이터 누락을 감지 못함
- **권장**: 최소한 `st.warning()` 또는 `logging.warning()`으로 에러 표시

### 4.2 [MAJOR] API 키 디버그 노출
- **파일**: `Generate.py:526-527`
- **현상**: `st.caption(f"Debug: header = Authorization: KakaoAK {kakao_api_key[:4]}...{kakao_api_key[-4:]}")` — API 키의 앞 4자리와 뒤 4자리가 UI에 노출됨
- **영향**: 보안 위험 (특히 Streamlit Cloud 배포 시)
- **권장**: 디버그 출력 제거 또는 환경변수 플래그로 제어
- **참고(2026-04)**: OSRM 백엔드가 추가되어 `is_use_time=False` 모드에서는 Kakao 키가 아예 필요 없게 되었다. 다만 본 디버그 출력은 Kakao 모드 분기에 그대로 남아 있으므로 별도 제거가 필요하다.

### 4.3 [MAJOR] Session State 초기화 — 페이지 간 충돌
- **파일**: `Generate.py`, `MCI_Streamlit.py`
- **현상**: 두 파일 모두 `base_path`, `kakao_api_key` 등을 독립적으로 session_state에 초기화. 다른 키 이름 사용 (`generate_base_path` vs `base_path`)
- **영향**: 사용자가 메인 페이지에서 설정한 경로가 Generate 페이지에 반영되지 않음
- **권장**: 공통 session_state 초기화 유틸리티 함수 생성

### 4.4 [MAJOR] 좌표 정규표현식 — 음수 좌표 미매칭
- **파일**: `MCI_Streamlit.py` `coord_to_tuple()`
- **현상**: `r"^\(([-\d\.]+),\s*([-\d\.]+)\)$"` — 동작은 하나, `[-\d\.]`는 문자 클래스에서 `-`의 위치에 따라 범위로 해석될 수 있음
- **영향**: 현재 한국 좌표(양수)에서는 문제 없으나, 확장 시 리스크
- **권장**: `[-\d.]` 또는 `[\-\d.]`로 명시적 이스케이프

### 4.5 [MINOR] `_split_factors()` 함수 중복 정의
- **파일**: `MCI_Streamlit.py` 내에서 2번 정의됨 (line ~130, line ~240)
- **영향**: 두 번째 정의가 첫 번째를 덮어씀. 내용이 동일하므로 실행에는 문제 없음
- **권장**: 하나로 통합

### 4.6 [MINOR] `import` 문 중복
- **파일**: `MCI_Streamlit.py` 상단 및 중간에 `import os, re`, `import numpy as np` 등 동일 import 반복
- **권장**: 파일 상단에 한 번만 import

### 4.7 [MINOR] 하드코딩된 기본값 불일치
- **파일**: `Generate.py:208-209` — `amb_handover: 0.0`, `uav_handover: 0.0`
- `batch_runner.py`와 `make_csv_yaml_dynamic.py`에서는 10.0/15.0으로 수정 완료
- **영향**: Generate 페이지에서 생성 시 handover=0으로 설정됨
- **권장**: 세 곳의 기본값을 통일 (amb=10.0, uav=15.0)

### 4.8 [MINOR] Folium 지도 성능 — 경로 다수 시 렌더링 지연
- 30개 소방서 + 20개 병원 경로를 모두 표시하면 브라우저 렌더링 지연
- **권장**: 기본 표시 개수 제한 (현재 멀티셀렉트로 부분적 해결 완료)

### 4.9 [MINOR] `ResultsCompare.py` — 대용량 결과 파일 메모리 이슈
- 64규칙 × 30샘플의 RAW 파일을 전체 메모리에 로드
- **권장**: 필요 메트릭만 선택적 파싱 (현재 `parse_raw_all_metrics`는 전체 로드)

### 4.10 [INFO] `st.cache_data` TTL 불일치
- `list_experiments_any`: ttl=60, `read_excel_hospital`: ttl=600, `load_json_files`: ttl=300
- 일관된 캐시 정책 수립 권장

### 4.11 [INFO] Streamlit Cloud 대응 코드
- `_detect_cloud_base_path()`, `IS_CLOUD` 분기 등 Cloud 배포 대응 코드가 잘 구현되어 있음
- API 키 Secrets 연동도 정상

### 4.12 [INFO] `BatchExperiment.py` — 페이지 구조 양호
- Step 1~5 워크플로우가 명확하게 구분되어 있음
- `process_coord()` 재사용으로 CLI와의 호환성 유지

---

## 5. experiment_1 (배치 실험 파이프라인)

### 5.1 [MAJOR] `progress.json` 동시 접근 — 원자적 쓰기 불완전
- **파일**: `batch_runner.py` `save_progress()`
- **현상**: `json.dump` 후 별도의 `os.replace` 없이 직접 파일에 쓰기. 프로세스 중단 시 파일 손상 가능
- **권장**: 임시 파일에 쓴 후 `os.replace()`로 원자적 교체 (부분적으로 구현되어 있으나 완전하지 않음)

### 5.2 [MINOR] `visualize_coords.py` — 컬러맵 범위 계산
- `clip_pct=2` 기본값으로 상하 2% 클리핑 → 이상치가 많은 경우 정보 손실
- **권장**: 이상치 개수를 별도 표기 (현재 `outlier_n` 파라미터로 부분 대응 중)

### 5.3 [MINOR] `generate_coords.py` — shapefile 인코딩
- `ctprvn.shp` 로딩 시 인코딩 자동 감지에 의존
- **권장**: `encoding='euc-kr'` 명시적 지정

### 5.4 [INFO] 전체 파이프라인 안정성 양호
- `batch_runner.py`의 Popen + 데몬 스레드 방식으로 stdout 버퍼 문제 해결 완료
- routes/ 폴더 초기화로 JSON 누적 방지 완료
- progress.json 기반 재시도 메커니즘 정상 동작 확인

---

## 6. 아키텍처 수준 관찰

### 6.1 강점
- **모듈 분리**: sce_src / sim_src / vis_src 3-tier 구조가 명확
- **재사용성**: `process_coord()`를 CLI와 대시보드에서 동일하게 사용
- **확장성**: Full Factorial 64규칙 조합이 `RuleManager`에 잘 캡슐화
- **데이터 보존**: routes/ JSON 저장으로 API 재호출 없이 경로 재활용 가능

### 6.2 개선 영역
- **에러 전파**: 하위 모듈 에러가 상위에서 충분히 처리되지 않음 (silent failure)
- **설정 중앙화**: 기본값이 3곳 이상에 분산 (batch_runner, make_csv_yaml_dynamic, Generate.py)
- **테스트 부재**: 단위 테스트/통합 테스트 파일 없음
- **로깅**: print 기반 → logging 모듈 전환 권장

---

## 7. 1000개 좌표 실험 최종 현황

| 분류 | 개수 | 설명 |
|------|------|------|
| 시나리오+시뮬 성공 | **772** | 정상 완료, 결과 데이터 존재 |
| 시나리오 성공, 시뮬 실패 | **5** | `diversion_rule()` 코드 로직 버그 (UAV+Red 전원 불가) |
| 사고지점 도로 불가 (rc=102) | **223** | 산/바다/무인도 등 도로 자체 없음 (소방서 문제 0건) |
| **합계** | **1000** | |

### 실패 원인 상세

- **223개 시나리오 실패**: 전부 사고지점 자체의 도로 접근 불가. 시나리오 폴더에 `amb_info_euc.csv`(API 불필요)만 존재하고 `hospital_info*.csv`(첫 API 호출 결과)가 없음 → 첫 번째 API 호출에서 바로 rc=102 실패. 소방서 좌표 문제는 0건 (소방서는 모두 건물이므로 도로 위에 존재)
- **5개 시뮬 실패**: 병상 부족이 아닌 코드 로직 이슈. 전북대학교병원(Tier3, 용량19)이 헬기장 없다는 이유로 UAV 전원 후보에서 제외됨. 전체 Tier3 용량(35)은 환자 수(30)보다 충분하나, UAV+Red 환자는 원광대(용량16) 1곳에만 갈 수 있어 확률적 크래시 발생
- **이전 이슈 해결 완료**: `avoid=ferries` 제거로 47개 추가 성공, handover 기본값 수정(0→10/15분), YAML 키 순서 버그 수정

---

## 8. 우선순위 권장 조치

| 순위 | 항목 | 난이도 | 영향도 |
|------|------|--------|--------|
| 1 | `diversion_rule()` fallback 추가 (헬기장 제한 완화) | 중 | 5개 좌표 크래시 해소 |
| 2 | Generate.py handover 기본값 통일 (0.0→10.0/15.0) | 하 | 파라미터 불일치 방지 |
| 3 | API 키 디버그 출력 제거 | 하 | 보안 개선 |
| 4 | 디버그 print → logging 전환 | 중 | 성능/유지보수 개선 |
| 5 | pd.concat 중복 제거 | 하 | 시뮬레이션 정확도 |
| 6 | bare except → 명시적 예외 처리 | 중 | 디버깅 용이성 |
| 7 | 기본값 중앙화 (constants.py) | 중 | 유지보수성 |

> **참고**: 이전 2순위였던 `make_amb_info()` 소방서 건너뛰기는 `avoid=ferries` 제거로 해결되어 목록에서 제외.

---

*본 보고서는 코드 수정 없이 읽기 전용으로 검토한 결과입니다.*
