# MCI_ADV: 대량 재난 사고 시뮬레이션 플랫폼

## 프로젝트 개요

대량 재난 사고(Mass Casualty Incident) 발생 시 **환자 이송 최적화**를 위한 시뮬레이션 및 분석 플랫폼입니다.

### 핵심 기능
- **시나리오 생성**: 카카오 모빌리티 API 기반 실시간/미래시간 교통정보 반영
- **시뮬레이션 엔진**: 구급차(AMB)와 드론(UAV)을 활용한 64개 정책 조합 평가
- **통계 분석**: Full Factorial ANOVA, 사후검정 자동 수행
- **시각화 대시보드**: Streamlit 기반 웹 인터페이스

---

## 목차

1. [디렉토리 구조](#디렉토리-구조)
2. [파이프라인 개요](#파이프라인-개요)
3. [모듈 간 Import 관계](#모듈-간-import-관계)
4. [시뮬레이션 엔진 아키텍처](#시뮬레이션-엔진-아키텍처)
5. [입력 파일 구조](#입력-파일-구조)
6. [API 사용](#api-사용)
7. [정책 조합 (64개 시나리오)](#정책-조합-64개-시나리오)
8. [대시보드 사용법](#대시보드-사용법)
9. [평가 지표](#평가-지표)
10. [배치 실험 파이프라인 (experiment_1)](#배치-실험-파이프라인-experiment_1)
11. [설치 및 실행](#설치-및-실행)

---

## 디렉토리 구조

```
MCI_ADV/
├── src/                                    # 소스 코드
│   ├── sce_src/                           # 시나리오 생성 모듈
│   │   ├── orchestrator.py               # 마스터 오케스트레이터
│   │   ├── make_csv_yaml_dynamic.py      # 동적 시나리오 생성기
│   │   └── BatchLab.py                   # 배치 처리 대시보드
│   │
│   ├── sim_src/                          # 시뮬레이션 엔진
│   │   ├── main.py                       # 시뮬레이션 진입점 (RunManager)
│   │   ├── ScenarioManager.py            # 시나리오 설정 및 개체 초기화
│   │   ├── EntityManager.py              # 개체 상태 관리
│   │   ├── EventManager.py               # 이벤트 큐 및 시뮬레이션 루프
│   │   ├── RuleManager.py                # 정책 규칙 관리 (64개 조합)
│   │   ├── MCIEnvironment_gymnasium.py   # Gymnasium 환경 래퍼
│   │   ├── config.yaml                   # 시뮬레이션 설정 템플릿
│   │   └── event_info.json               # 이벤트 정의 (8개 이벤트)
│   │
│   └── vis_src/                          # 시각화/대시보드
│       ├── MCI_Streamlit.py              # 메인 대시보드
│       └── pages/
│           ├── Generate.py               # 시나리오 생성 UI
│           ├── ResultsCompare.py         # 결과 비교 페이지
│           └── BatchExperiment.py        # 배치 실험 대시보드 (5단계 워크플로우)
│
├── scenarios/                             # 시나리오 데이터
│   ├── 안전센터와 소방서.csv               # 소방서/119안전센터 마스터 (필수)
│   ├── 엑셀 결합 데이터.xlsx               # 병원 마스터 데이터 (필수)
│   ├── DISTANCE_MATRIX_FINAL.xlsx         # 사전 계산된 거리 행렬
│   ├── label_map.csv                      # 실험 좌표 레이블
│   └── exp_{YYYYMMDD_HHMMSS}_dep_{HHMM}/ # 생성된 시나리오
│       └── (lat,lon)/                     # 좌표별 폴더
│           ├── config_(lat,lon).yaml      # 시뮬레이션 설정
│           ├── patient_info.csv           # 환자 중증도 분포
│           ├── hospital_info_road.csv     # 병원 정보 (도로 거리)
│           ├── hospital_info_euc.csv      # 병원 정보 (직선 거리)
│           ├── amb_info_road.csv          # 구급차 출동 정보 (도로)
│           ├── amb_info_euc.csv           # 구급차 출동 정보 (직선)
│           ├── uav_info.csv               # UAV 출동 정보
│           ├── distance_Hos2Hos_*.csv     # 병원-병원 거리 행렬
│           ├── distance_Hos2Site_*.csv    # 병원-현장 거리 행렬
│           └── routes/                    # 경로 JSON
│               ├── center2site/           # 안전센터 → 사고지점
│               └── hos2site/              # 사고지점 → 병원
│
├── results/                               # 시뮬레이션 결과
│   └── exp_{YYYYMMDD_HHMMSS}_dep_{HHMM}/
│       └── (lat,lon)/
│           ├── results_(lat,lon).txt      # RAW 결과 (전체 데이터)
│           └── results_(lat,lon)_stat.txt # 통계 요약
│
├── experiment_logs/                       # 실행 로그
│   └── (lat,lon)_YYYYMMDD_HHMMSS.txt
│
├── experiment_1/                          # 논문 배치 실험 파이프라인
│   ├── generate_coords.py                # 한국 육지 좌표 1000개 생성
│   ├── batch_runner.py                   # 시나리오 생성 + 시뮬레이션 배치 처리
│   ├── visualize_coords.py               # 배치 결과 지도·히스토그램·규칙분석 시각화
│   └── ctprvn.shp / .shx / .dbf         # 한국 행정구역 shapefile
│
├── requirements.txt                       # Python 패키지 의존성
├── MCI_대시보드_관련_정보.pdf              # 대시보드 참고 문서
└── README.md                              # 본 문서
```

---

## 파이프라인 개요

전체 시스템은 3단계 파이프라인으로 구성됩니다:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         1. 시나리오 생성 파이프라인                            │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  사용자 입력 (Generate.py)                                                    │
│    ├─ 좌표 (위도, 경도)                                                       │
│    ├─ 환자 수, 구급차 수, UAV 수                                              │
│    ├─ 이동 속도 (AMB: 40km/h, UAV: 80km/h)                                   │
│    └─ 카카오 API 키 + 출발 시간                                               │
│                     ↓                                                        │
│  Orchestrator.generate_scenario()                                            │
│                     ↓                                                        │
│  ScenarioGenerator (make_csv_yaml_dynamic.py)                                │
│    ├─ 병원 마스터 데이터 로드 (엑셀 결합 데이터.xlsx)                          │
│    ├─ 소방서 데이터 로드 (안전센터와 소방서.csv)                               │
│    ├─ 카카오 모빌리티 API 호출 (도로 거리 + 소요 시간)                         │
│    ├─ patient_info.csv 생성 (중증도 분포)                                     │
│    ├─ hospital/ambulance/uav CSV 생성                                        │
│    ├─ 거리 행렬 생성 (Hos2Hos, Hos2Site)                                      │
│    ├─ routes/*.json 생성 (API 응답 저장)                                      │
│    └─ config_{coord}.yaml 생성                                               │
│                     ↓                                                        │
│  scenarios/exp_{YYYYMMDD_HHMMSS}_dep_{HHMM}/(lat,lon)/                       │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                         2. 시뮬레이션 실행 파이프라인                          │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Orchestrator.run_simulation(config_path)                                    │
│                     ↓                                                        │
│  main.py --config_path config.yaml                                           │
│                     ↓                                                        │
│  RunManager 초기화                                                            │
│    ├─ ScenarioManager: 개체 설정 로드 (환자, 병원, 구급차, UAV)                │
│    │     ├─ EntityManager: 개체 상태 관리                                     │
│    │     └─ EventManager: 이벤트 큐 관리                                      │
│    ├─ RuleManager: 64개 정책 규칙 생성 (Full Factorial)                       │
│    └─ MCIEnvironment_gymnasium: 시뮬레이션 환경 생성                          │
│                     ↓                                                        │
│  시뮬레이션 루프 (totalSamples × 64 rules)                                    │
│    ├─ env.reset() → 초기 관찰값                                               │
│    ├─ While not done:                                                        │
│    │     ├─ EventManager.run_next() → 이벤트 처리                             │
│    │     ├─ rule.select(observation) → 행동 선택                              │
│    │     └─ env.step(action) → 관찰값, 보상, 종료 여부                         │
│    └─ 결과 기록: [Reward, Time, PDR, Reward_woG, PDR_woG]                     │
│                     ↓                                                        │
│  results/exp_{...}/(lat,lon)/                                                │
│    ├─ results_(lat,lon).txt       (RAW 데이터)                               │
│    └─ results_(lat,lon)_stat.txt  (통계: 평균, 표준편차, 95% CI)              │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                         3. 시각화 및 분석 파이프라인                           │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  MCI_Streamlit.py 대시보드                                                    │
│    │                                                                         │
│    ├─ Settings (사이드바)                                                     │
│    │     ├─ 프로젝트 경로 선택                                                │
│    │     ├─ 실험 ID 선택                                                      │
│    │     ├─ 좌표 선택                                                         │
│    │     └─ 미니맵 표시                                                       │
│    │                                                                         │
│    ├─ Scenarios 탭                                                           │
│    │     ├─ experiment_logs 로그 뷰어                                        │
│    │     ├─ 환자별 구조→이송→치료 타임라인                                    │
│    │     ├─ 이벤트 테이블                                                     │
│    │     └─ Rule/Iteration 필터                                              │
│    │                                                                         │
│    ├─ Maps 탭                                                                │
│    │     ├─ Folium 지도 렌더링                                               │
│    │     ├─ C→S 경로 (안전센터 → 사고지점): 보라 점선                         │
│    │     ├─ S→H 경로 (사고지점 → 병원): 청록 점선                             │
│    │     ├─ 혼잡도 색상 표시                                                  │
│    │     └─ 경로 정보 팝업 (거리 km, 시간 min)                                │
│    │                                                                         │
│    ├─ Analytics 탭                                                           │
│    │     ├─ results_.txt 파싱                                                │
│    │     ├─ ANOVA 분석 (Full Factorial, One-way, RCBD)                       │
│    │     ├─ 사후검정 (Tukey HSD, Games-Howell)                               │
│    │     ├─ 잔차 진단 (Shapiro-Wilk, QQ plot)                                │
│    │     └─ A그룹 교집합 추천                                                 │
│    │                                                                         │
│    ├─ Data Tables 탭                                                         │
│    │     ├─ CSV 파일 실시간 편집                                              │
│    │     ├─ 자동 백업                                                         │
│    │     └─ 수정값으로 재실행                                                 │
│    │                                                                         │
│    ├─ Rerun 탭                                                               │
│    │     └─ 기존 YAML 기반 시뮬레이션 재실행                                  │
│    │                                                                         │
│    └─ Generate 페이지 (pages/Generate.py)                                    │
│          ├─ 카카오 API 키 입력                                                │
│          ├─ 운행시간 모드 (실시간/미래시간)                                    │
│          ├─ 파라미터 설정                                                     │
│          └─ 시나리오 생성 + 즉시 실행                                         │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 모듈 간 Import 관계

### 1. MCI_Streamlit.py (메인 대시보드)
```
MCI_Streamlit.py
    ↓ imports
    ├── orchestrator (src/sce_src)  ──→ Orchestrator 클래스
    ├── pandas, numpy, yaml         ──→ 데이터 I/O
    ├── streamlit, folium, altair   ──→ UI 렌더링
    ├── scipy, statsmodels          ──→ 통계 분석
    └── openpyxl                    ──→ 엑셀 파일 처리
```

### 2. main.py (시뮬레이션 진입점)
```
main.py
    ↓ imports
    ├── ScenarioManager.py
    │     ├── EntityManager.py
    │     └── EventManager.py
    ├── RuleManager.py              ──→ Universal_Rule 클래스 (64개)
    ├── MCIEnvironment_gymnasium.py ──→ gymnasium.Env
    ├── yaml, argparse              ──→ 설정 파싱
    └── numpy, scipy                ──→ 수치 계산
```

### 3. orchestrator.py (오케스트레이터)
```
orchestrator.py
    ↓ imports
    ├── make_csv_yaml_dynamic.py    ──→ ScenarioGenerator 클래스
    ├── subprocess                  ──→ main.py 실행
    ├── requests                    ──→ 카카오 API 호출
    ├── pandas, yaml                ──→ 데이터 처리
    └── time, datetime              ──→ 로깅
```

### 4. make_csv_yaml_dynamic.py (시나리오 생성기)
```
make_csv_yaml_dynamic.py
    ↓ imports
    ├── requests                    ──→ 카카오 모빌리티 API
    ├── haversine                   ──→ 직선 거리 계산 (폴백)
    ├── pandas                      ──→ Excel/CSV I/O
    └── yaml, json                  ──→ 설정 파일 생성
```

---

## 시뮬레이션 엔진 아키텍처

### 클래스 계층 구조

```
RunManager (main.py)
│
├── config ← YAML 설정 파싱
│
├── ScenarioManager
│   │
│   ├── EntityManager
│   │   └── en_status: dict  ← 개체 상태
│   │       ├── patient: p_states, p_wait, p_sent
│   │       ├── hospital: h_states (idle, queue, occupied)
│   │       ├── ambulance: amb_states, amb_wait
│   │       └── uav: uav_states, uav_wait
│   │
│   └── EventManager
│       ├── event_queue: heapq  ← 우선순위 큐 (시간순)
│       ├── events: onset, p_rescue, amb_arrival_site, ...
│       └── time: 시뮬레이션 시계
│
├── RuleManager
│   └── rules: List[Universal_Rule]  ← 64개 정책 조합
│       └── 결정 요소:
│           ├── Priority: START vs ReSTART
│           ├── Hospital Selection: RedOnly vs YellowNearest
│           ├── Red Action: OnlyUAV, Both_UAVFirst, Both_AMBFirst, OnlyAMB
│           └── Yellow Action: OnlyUAV, Both_UAVFirst, Both_AMBFirst, OnlyAMB
│
└── MCIEnvironment_gymnasium (gym.Env)
    ├── action_space: (patient_severity, hospital_idx, transport_mode)
    ├── observation_space: 개체 상태
    ├── step(): 행동 실행 → (obs, reward, done, truncated, info)
    ├── reset(): 시나리오 초기화
    └── Reward = Σ[Patient_i: SurvivalProb(rescue_time, severity)]
```

### 이벤트 흐름 (event_info.json)

| 이벤트 | 참여 개체 | Decision Epoch | 설명 |
|--------|----------|----------------|------|
| `onset` | patient | No | 사고 발생, 환자 구조 이벤트 생성 |
| `p_rescue` | patient | **Yes** | 환자 구조 완료, 이송 대기 시작 |
| `amb_arrival_site` | ambulance | **Yes** | 구급차 현장 도착 |
| `uav_arrival_site` | uav | **Yes** | UAV 현장 도착 |
| `amb_arrival_hospital` | patient, ambulance, hospital | No | 구급차 병원 도착, 환자 인계 |
| `uav_arrival_hospital` | patient, uav, hospital | No | UAV 병원 도착, 환자 인계 |
| `p_care_ready` | patient, hospital | No | 환자 치료 준비 완료 |
| `p_def_care` | patient, hospital | No | 환자 치료 완료 |

### 시뮬레이션 루프 (EventManager.run_next)

```python
While True:
    1. event_queue에서 가장 빠른 이벤트 팝
    2. 시뮬레이션 시계 진행
    3. 자원 상태 업데이트 (구급차/UAV 이동 시간)
    4. 이벤트 핸들러 실행 (ev_onset, ev_p_rescue, ...)
    5. decision_epoch=True 이면: 정책에 행동 요청
    6. 종료 조건 확인 (모든 환자 치료 완료)
    7. 계속 진행
```

### 개체 상태 구조

**환자 상태**: `p_states[patient_id] = [severity_class, rescued, moving, moved, cared]`
- severity_class: 0=Red, 1=Yellow, 2=Green, 3=Black
- rescued: 0=미구조, 1=구조 완료
- moving: 0=대기 중, 1=이송 중
- moved: 0=현장, 1=병원 도착
- cared: 0=미치료, 1=치료 시작, 2=치료 완료

**병원 상태**: `h_states[hospital_id] = [n_idle, n_queue, n_occupied]`
- n_idle: 가용 병상 수
- n_queue: 대기 환자 수
- n_occupied: 점유 병상 수

**구급차 상태**: `amb_states[amb_id] = [destination_hospital_id, severity_carrying, time_to_arrival]`

**UAV 상태**: `uav_states[uav_id] = [destination_hospital_id, severity_carrying, time_to_arrival]`

---

## 입력 파일 구조

### 1. 마스터 데이터

#### 안전센터와 소방서.csv (필수)
```
경로: scenarios/안전센터와 소방서.csv
인코딩: CP949

컬럼:
- 지역명: 시도명
- 지역번호: 지역 코드
- 주소: 상세 주소
- y좌표: 위도 (latitude)
- x좌표: 경도 (longitude)
- 전화번호: 연락처
- 구분: 소방서/119안전센터
- 날짜: 데이터 기준일
- 순번: 일련번호
- 수량: 보유 구급차 대수 (복제 기준)
```

#### 엑셀 결합 데이터.xlsx (필수)
```
경로: scenarios/엑셀 결합 데이터.xlsx
인코딩: UTF-8 (openpyxl)

컬럼:
- 요양기관명: 병원명
- 종별코드: 1=상급종합, 11=종합, 21=병원, ...
- 응급실병상수: 응급실 병상 수
- x좌표: 경도 (longitude)
- y좌표: 위도 (latitude)
- 헬기장 여부: 1=있음, 0=없음 (UAV 착륙 가능 여부)
```

### 2. 생성된 시나리오 파일

#### config_(lat,lon).yaml
```yaml
entity_info:
  patient:
    incident_size: 30              # 총 환자 수
    latitude: 37.465833            # 사고지점 위도
    longitude: 126.443333          # 사고지점 경도
    incident_type: null            # 사고 유형 (확장용)
    info_path: "./patient_info.csv"

  hospital:
    load_data: True
    info_path: "./hospital_info_road.csv"
    dist_Hos2Hos_euc_info: "./distance_Hos2Hos_euc.csv"
    dist_Hos2Hos_road_info: "./distance_Hos2Hos_road.csv"
    dist_Hos2Site_euc_info: "./distance_Hos2Site_euc.csv"
    dist_Hos2Site_road_info: "./distance_Hos2Site_road.csv"
    max_send_coeff: [1, 1]         # max_send = a*capa + b*queue

  ambulance:
    load_data: True
    dispatch_distance_info: "./amb_info_road.csv"
    velocity: 40                   # km/h
    handover_time: 0               # 환자 인계 시간 (분)
    is_use_time: True              # API duration 사용 여부
    duration_coeff: 1.0            # duration 가중치

  uav:
    load_data: True
    dispatch_distance_info: "./uav_info.csv"
    velocity: 80                   # km/h
    handover_time: 0               # 환자 인계 시간 (분)

event_info_path: "event_info.json"

rule_info:
  isFullFactorial: True            # 64개 전체 조합
  priority_rule: ["START", "ReSTART"]
  hos_select_rule: ["RedOnly", "YellowNearest"]
  red_mode_rule: ["OnlyUAV", "Both_UAVFirst", "Both_AMBFirst", "OnlyAMB"]
  yellow_mode_rule: ["OnlyUAV", "Both_UAVFirst", "Both_AMBFirst", "OnlyAMB"]

run_setting:
  totalSamples: 10                 # 반복 횟수
  random_seed: 0                   # 랜덤 시드 (null=미고정)
  rule_test: True
  eval_mode: True
  output_path: "./results"
  exp_indicator: "(lat,lon)"       # 결과 파일 접미사
  save_info: True
```

#### patient_info.csv
```csv
type,ratio,rescue_param_alpha,rescue_param_beta,treat_tier3,treat_tier2,treat_tier3_mean,treat_tier2_mean
Red,0.1,6,5,True,False,40,INF
Yellow,0.3,2,13,True,True,20,30
Green,0.5,1,22,True,True,10,15
Black,0.1,0,0,True,True,0,0
```
- ratio: 환자 비율 (합계=1.0)
- rescue_param_alpha/beta: 구조 시간 베타 분포 파라미터
- treat_tier3: 상급종합병원(Tier3) 치료 가능 여부
- treat_tier2: 일반병원 치료 가능 여부
- treat_tier3/2_mean: 치료 시간 지수분포 평균 (분)

#### hospital_info_road.csv
```csv
Index,요양기관명,종별코드,응급실병상수,수술실수,병상수,헬기장 여부,x좌표,y좌표,distance,duration
0,서울대학교병원,1,50,3,47,1,126.9997,37.5795,15.3,28.5
1,연세대학교의과대학,1,45,3,42,1,126.9406,37.5622,12.1,22.3
...
```

#### amb_info_road.csv
```csv
Index,init_distance,duration,안전센터/소방서이름,보유대수
0,5.2,8.5,영등포소방서,3
1,6.8,11.2,구로119안전센터,2
...
```

#### uav_info.csv
```csv
Index,init_distance,hospital_name
0,15.3,서울대학교병원
1,12.1,연세대학교의과대학
...
```

#### routes/*.json (카카오 API 응답)
```json
{
  "meta": {
    "api_provider": "kakao",
    "route_type": "center2site",
    "source_index": 0,
    "name": "영등포소방서",
    "center": [126.9123, 37.5234],
    "site": [126.9456, 37.5567],
    "departure_time": "202502091030",
    "distance_km": 5.2,
    "duration_min": 8.5,
    "duration_sec": 510
  },
  "payload": {
    "kakao_response": { ... }
  }
}
```

---

## API 사용

### 카카오 모빌리티 API

#### 역지오코딩 (좌표 → 주소)
```python
# orchestrator.py: reverse_geocode_kakao()
URL: https://dapi.kakao.com/v2/local/geo/coord2address.json
Headers: {"Authorization": "KakaoAK {API_KEY}"}
Params: {"x": lon, "y": lat, "input_coord": "WGS84"}

Response:
{
  "full_address": "서울특별시 영등포구 여의도동",
  "road_address": "서울특별시 영등포구 여의나루로 76",
  "area1": "서울특별시",
  "area2": "영등포구",
  "area3": "여의도동",
  "area4": ""
}
```

#### 도로 거리 및 소요 시간
```python
# make_csv_yaml_dynamic.py: get_road_distance_kakao()
URL: https://apis-navi.kakaomobility.com/v1/future/directions
Headers: {"Authorization": "KakaoAK {API_KEY}"}
Params: {
  "origin": "lon,lat",
  "destination": "lon,lat",
  "priority": "TIME",
  "departure_time": "YYYYMMDDHHMM"  # 미래시간 (선택)
}

Response:
{
  "routes": [{
    "summary": {
      "distance": 5200,      # 미터
      "duration": 510,       # 초
      "fare": {"toll": 0, "taxi": 3500}
    }
  }]
}
```

#### API 키 설정 방법
```python
# 1. Streamlit Cloud (secrets.toml)
[kakao]
rest_api_key = "your_api_key"

# 2. 환경 변수
export KAKAO_REST_API_KEY="your_api_key"

# 3. Generate.py UI 직접 입력
```

#### 오류 처리
- **401 (Auth failure)**: API 키 확인 필요 → 중단
- **429 (Rate limit)**: 2초 대기 후 재시도 (최대 3회)
- **Timeout**: 15초 → 직선 거리(Haversine)로 폴백

---

## 정책 조합 (64개 시나리오)

```
2 (Priority) × 2 (Hospital Selection) × 4 (Red Action) × 4 (Yellow Action) = 64개
```

### Priority (우선순위 정책)
| 값 | 설명 |
|----|------|
| START | 초기에 전체 환자 배정 계획 수립 |
| ReSTART | 병원 도착 시마다 잔여 환자 기반 재배정 (τ값 계산) |

ReSTART τ 계산:
```
τ = 71 - (0.5 × num_D × (θ_amb/K_amb + θ_uav/K_uav))
- num_D: 잔여 Yellow 환자 수
- θ: 평균 왕복 시간
- K: 이송 수단 수
```

### Hospital Selection (병원 선택 정책)
| 값 | 설명 |
|----|------|
| RedOnly | Red 환자: 상급종합병원만, Yellow: 일반병원만 |
| YellowNearest | Red: 상급종합, Yellow: 거리순 (등급 무관) |

### Red/Yellow Action (이송 수단 선택)
| 값 | 설명 |
|----|------|
| OnlyUAV | UAV만 사용 (없으면 대기) |
| OnlyAMB | 구급차만 사용 (없으면 대기) |
| Both_UAVFirst | UAV 우선, 없으면 구급차 |
| Both_AMBFirst | 구급차 우선, 없으면 UAV |

### 시나리오 명명 규칙
```
{Priority}, {HosSelect}, Red {RedAction}, Yellow {YellowAction}

예시:
- START, RedOnly, Red OnlyUAV, Yellow OnlyAMB
- ReSTART, YellowNearest, Red Both_AMBFirst, Yellow Both_UAVFirst
```

---

## 대시보드 사용법

### 실행 방법
```bash
# 메인 대시보드
cd src/vis_src
streamlit run MCI_Streamlit.py

# 시나리오 생성 페이지 (독립 실행)
streamlit run pages/Generate.py
```

### 탭별 기능

#### 1. Settings (사이드바)
- **프로젝트 경로**: `C:\Users\User\MCI_ADV` 입력
- **실험 ID 선택**: `exp_YYYYMMDD_HHMM_dep_HHMM` 드롭다운
- **좌표 선택**: `(lat,lon)` 드롭다운
- **미니맵**: 선택된 좌표 위치 표시

#### 2. Scenarios 탭
- 로그 파일 선택 (experiment_logs/)
- **Rule 선택**: 64개 정책 중 선택
- **Iteration 선택**: 반복 횟수 중 선택
- **환자 요약표**: 구조시각 → 이송수단 → 병원 → 도착시각 → 치료완료
- **이벤트 테이블**: 전체 시뮬레이션 이벤트 타임라인

#### 3. Maps 탭
- **테마**: Light / Dark
- **경로 표시**:
  - AMB C→S (안전센터 → 사고지점): 실선, 혼잡도 색상
  - AMB S→H (사고지점 → 병원): 실선
  - UAV 출동: 점선 (상급종합병원 → 사고지점)
  - UAV 이송: 점선 (사고지점 → 병원)
- **범례**: 혼잡도 색상 + AMB/UAV 속도 표시
- **팝업**: 클릭 시 거리(km), 시간(min) 표시

#### 4. Analytics 탭
- **지표 선택**: Reward, Time, PDR, Reward w.o.G, PDR w.o.G
- **정렬 기준**: Reward↓, PDR↑, Time↑
- **ANOVA 설계**:
  - Full Factorial: Phase × RedPolicy × RedAction × YellowAction
  - One-way: 단일 요인
  - RCBD: Randomized Complete Block Design
- **유의수준**: α = 0.001 ~ 0.1
- **사후검정**: Tukey HSD (등분산), Games-Howell (이분산)
- **잔차 진단**: Shapiro-Wilk 검정, QQ plot, 히스토그램
- **A그룹 교집합**: 모든 지표에서 상위 그룹인 시나리오 추천

#### 5. Data Tables 탭
- CSV 파일 선택 (파일명만 표시, 경로 숨김)
- 실시간 편집 가능 (`안전센터와 소방서.csv` 제외)
- 저장 시 자동 백업: `*_backup_{timestamp}.csv`
- "수정값으로 재실행" 버튼

#### 6. Rerun 탭
- 기존 YAML 설정 파일 선택
- 시뮬레이션 재실행

#### 7. Generate 페이지 (pages/Generate.py)
1. **카카오 API 키 입력**
2. **운행시간 모드 선택**:
   - 실시간: 현재 교통 상황 반영
   - 미래시간: YYYYMMDDHHMM 형식 입력
3. **파라미터 설정**:
   - 위도/경도
   - 환자 수 (기본: 30)
   - 구급차 수 (기본: 30)
   - UAV 수 (기본: 3)
   - 구급차 속도 (기본: 40 km/h)
   - UAV 속도 (기본: 80 km/h)
   - 시뮬레이션 반복 (기본: 10)
   - 랜덤 시드 (기본: 0)
4. **생성 및 실행**: 시나리오 생성 후 자동으로 시뮬레이션 실행

---

## 평가 지표

| 지표 | 계산 방법 | 해석 |
|------|----------|------|
| **Reward** | Σ SurvivalProb(rescue_time, severity) | 생존확률 합계 (↑ 좋음) |
| **Time** | 마지막 환자 치료 완료 시각 | 총 소요 시간 (↓ 좋음) |
| **PDR** | 1 - Reward / Preventable | 예방가능사망률 (↓ 좋음) |
| **Reward w.o.G** | Reward - Green 환자 기여분 | Green 제외 보상 (↑ 좋음) |
| **PDR w.o.G** | 1 - (Reward - Green) / (Preventable - Green) | Green 제외 PDR (↓ 좋음) |

### 생존확률 계산
```
SurvivalProb = f(rescue_time, severity_class)
- Red: 시간에 민감 (빠른 이송 필수)
- Yellow: 중간 민감도
- Green: 시간 영향 적음
- Black: 사망 (기여분 0)
```

---

## 배치 실험 파이프라인 (experiment_1)

논문 실험용 배치 자동화 워크플로우입니다. 한국 육지 경계 내 랜덤 좌표 1000개에 대해 시나리오 생성 → 시뮬레이션 → 결과 시각화를 자동으로 처리합니다. 상세 사용법은 [`experiment_1/README.md`](experiment_1/README.md)를 참조하세요.

### 전체 흐름

```
Step 1. 좌표 생성
  python experiment_1/generate_coords.py --n 1000 --seed 0
  → experiment_1/coords_korea.csv (1000개 한국 육지 좌표)

Step 2. 배치 실험 (매일 동일 명령 실행, progress.json에서 자동 이어서 처리)
  python experiment_1/batch_runner.py --kakao-api-key YOUR_KEY --experiment-id exp_korea_random_1000

Step 3. 결과 시각화
  python experiment_1/visualize_coords.py
  → scenarios/{experiment_id}/ 에 시각화 파일 생성
```

> 시각화 산출물(`coords_map.html`, 히스토그램, 규칙 히트맵, 주효과 그래프)은 `scenarios/{experiment_id}/` 폴더에 저장되며, 대시보드 BatchExperiment 페이지에서도 확인 가능합니다.

### visualize_coords.py 기능

- **결과 지도 (단일 HTML)**: Reward / Time / PDR 3개 지표를 JavaScript 버튼으로 전환
- **지도 타일 전환**: OpenStreetMap / CartoDB 두 가지 타일 선택 가능
- **컬러맵**: RdYlGn (빨강↔초록), P5~P95 백분위수 클리핑으로 상대 비교 최적화
- **이상치 강조**: 상위·하위 N개 좌표를 별도 색상(파랑/보라)으로 표시
- **이상치 목록**: 접을 수 있는 `<details>` 패널로 좌표 및 인덱스 표시
- **히스토그램**: Freedman-Diaconis 빈 크기 (min 60, max 120개 빈), 이상치 빈 별도 색상, rug plot
- **규칙 히트맵**: 64개 규칙의 3지표 × 4패널(Priority×HosSelect) 매트릭스, 각 패널 4×4(Red Mode×Yellow Mode)
- **주효과 그래프**: 4개 요인별 marginal mean 막대그래프, Best level 빨간 테두리 + ★ 표시, Effect size 박스

```bash
python experiment_1/visualize_coords.py [옵션]
  --clip-pct FLOAT   컬러맵 클리핑 백분위수 (기본: 5.0 → 5th~95th)
  --outlier-n INT    양쪽 이상치 개수 (기본: 3)
  --out PATH         출력 HTML 경로 (기본: experiment_1/coords_map.html)
  --hist-format FMT  히스토그램 포맷 pdf|png (기본: pdf)
```

### stat.txt 구조

시뮬레이션 결과 `results_*_stat.txt`는 320행 구성:
```
64룰 × 5블록 = 320행
블록 순서: Reward → Time → PDR → RewardWOG → PDRWOG
각 행: rule_name  mean  std  95%CI_half
시각화 값 = 블록별 64개 mean의 평균 (mean of means)
```

---

## 설치 및 실행

### 환경 요구사항
- Python 3.9 이상
- Windows / Linux / macOS

### 설치
```bash
# 1. Conda 환경 생성 (권장)
conda create -n MCI python=3.9
conda activate MCI

# 2. 패키지 설치
pip install -r requirements.txt

# 또는 개별 설치
pip install streamlit==1.50.0 pandas==2.2.2 numpy==1.26.4 \
    folium==0.20.0 streamlit-folium==0.25.1 altair==5.5.0 \
    plotly==6.5.1 openpyxl==3.1.2 PyYAML==6.0.2 \
    requests==2.32.4 haversine==2.9.0 scipy==1.13.1 \
    statsmodels==0.14.5 scikit-posthocs==0.11.4 pingouin==0.5.5 \
    gymnasium==1.0.0
```

### 필수 파일 확인
```
scenarios/
├── 안전센터와 소방서.csv  ← 필수
└── 엑셀 결합 데이터.xlsx   ← 필수
```

### 실행
```bash
# 1. 대시보드 실행
cd src/vis_src
streamlit run MCI_Streamlit.py

# 2. 시나리오 생성 페이지
streamlit run pages/Generate.py

# 3. 시뮬레이션 직접 실행 (CLI)
cd src/sim_src
python main.py --config_path /path/to/config.yaml
```

### Streamlit Cloud 배포
```
# 1. GitHub 저장소에 푸시
# 2. Streamlit Cloud에서 연결
# 3. secrets.toml 설정:
[kakao]
rest_api_key = "your_api_key"
```

---

## 참고사항

### 성능
- 500회 초과 반복 시 로그 뷰어 자동 비활성화
- 대용량 데이터 처리 시 로딩 시간 증가 가능

### 파일 인코딩
- 한글 파일명: CP949 인코딩 사용
- CSV 파일: UTF-8-sig → CP949 자동 폴백

### 데이터 보호
- CSV 편집 시 자동 백업 생성
- 원본 데이터 보존

### 확장 포인트
- `event_info.json`: 새로운 이벤트 타입 추가
- `RuleManager.py`: 새로운 정책 규칙 추가
- `make_csv_yaml_dynamic.py`: 새로운 데이터 소스 연동

---

## 라이선스

(프로젝트 라이선스 명시 필요)

---

## 문의

(문의처 정보 추가 필요)
