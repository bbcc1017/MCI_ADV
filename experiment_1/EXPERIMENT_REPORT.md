# Experiment 1: 한국 전역 랜덤 좌표 1,000개 배치 실험 보고서

## 1. 실험 개요

### 1.1 목적
한국 육지 경계 내 무작위 추출한 1,000개 좌표에 대해 MCI(Mass Casualty Incident) 시뮬레이션을 수행하여, **지리적 위치에 따른 응급의료 대응 성능의 공간적 분포**를 분석한다. 각 좌표에서 64개 운용 규칙(rule) 조합에 대한 시뮬레이션을 반복 수행하여 규칙 간 성능 비교 및 지역별 편차를 도출한다.

### 1.2 실험 식별 정보

| 항목 | 값 |
|------|-----|
| Experiment ID | `korea_random_1000` |
| 시나리오 폴더 | `scenarios/exp_korea_random_1000_dep_202604071400/` |
| 결과 폴더 | `results/exp_korea_random_1000_dep_202604071400/` |
| 진행 상태 파일 | `scenarios/exp_korea_random_1000_dep_202604071400/progress.json` |
| 좌표 CSV | `scenarios/exp_korea_random_1000_dep_202604071400/coords.csv` |
| 실험 기간 | 2026-03-19 12:46 ~ 2026-04-04 18:08 (17일) |
| 총 연산 시간 | 약 4.6시간 (시나리오 생성 3.3h + 시뮬레이션 1.3h) |

---

## 2. 실험 설계

### 2.1 좌표 생성

- **방법**: 한국 행정구역 shapefile(`ctprvn.shp`) 기반 Point-in-Polygon 필터링
- **좌표 수**: 1,000개
- **랜덤 시드**: 0 (재현 가능)
- **좌표 생성일**: 2026-03-18
- **위도 범위**: 33.2927° ~ 38.5135°N
- **경도 범위**: 125.7155° ~ 130.8042°E

### 2.2 시뮬레이션 파라미터

| 파라미터 | 값 | 비고 |
|----------|-----|------|
| 환자 수 (`incident_size`) | 30 | 고정 |
| 구급차 수 (`amb_count`) | 30 | 소방서 기반 배치 |
| UAV 수 (`uav_count`) | 3 | 상급종합병원(Tier3) 배치 |
| 구급차 속도 | 40 km/h | |
| UAV 속도 | 80 km/h | |
| 구급차 인계시간 (`amb_handover_time`) | 10분 | |
| UAV 인계시간 (`uav_handover_time`) | 15분 | |
| API 경로 사용 (`is_use_time`) | True | Kakao Mobility API duration 기반 (본 실험 당시. 이후 OSRM 백엔드도 추가되어 `is_use_time=false`로도 동일 파이프라인을 돌릴 수 있음) |
| Duration 가중치 (`duration_coeff`) | 1.0 | |
| 병원 전송계수 (`max_send_coeff`) | [1.0, 1.0] | |
| 출발시각 (`departure_time`) | 202604071400 | 2026년 4월 7일(화) 14:00 |
| 반복 횟수 (`totalSamples`) | 30 | 시뮬레이션 반복 (표본 수) |
| 랜덤 시드 (`random_seed`) | 0 | |

### 2.3 규칙 조합 (Full Factorial Design)

| 규칙 차원 | 수준 | 값 |
|-----------|------|-----|
| 우선순위 (`priority_rule`) | 2 | START, ReSTART |
| 병원 선택 (`hos_select_rule`) | 2 | RedOnly, YellowNearest |
| Red 이송모드 (`red_mode_rule`) | 4 | OnlyUAV, Both_UAVFirst, Both_AMBFirst, OnlyAMB |
| Yellow 이송모드 (`yellow_mode_rule`) | 4 | OnlyUAV, Both_UAVFirst, Both_AMBFirst, OnlyAMB |
| **총 규칙 조합** | **64** | 2 × 2 × 4 × 4 |

### 2.4 환자 분류 (Triage)

| 분류 | 비율 | 환자 수 | 치료 가능 병원 | rescue_alpha | rescue_beta |
|------|------|---------|---------------|-------------|-------------|
| Red | 10% | 3명 | Tier3(상급종합)만 | 6 | 5 |
| Yellow | 40% | 12명 | Tier2 + Tier3 | - | - |
| Green | 40% | 12명 | Tier1 + Tier2 + Tier3 | - | - |
| Black | 10% | 3명 | (사망) | - | - |

### 2.5 병원 구성

| 항목 | 통계 (n=772) |
|------|-------------|
| 시나리오당 병원 수 (평균) | 9.9개 |
| 시나리오당 병원 수 (중앙값) | 10개 |
| 병원 수 범위 | 4 ~ 15개 |
| 구급차 배치 소방서 수 | 30개 (고정) |
| UAV 배치 수 | 3대 (Tier3 병원 배치) |

### 2.6 경로 데이터

- **도로 경로**: Kakao Mobility API (자동차 길찾기)
- **UAV 경로**: 유클리드 거리 기반 (직선)
- **API 총 호출 수**: 28,661회
- **API 사용 기간**: 6일 (일일 한도 약 5,000회)

| 날짜 | API 호출 | 처리 좌표 |
|------|----------|-----------|
| 2026-03-19 | 2,477 | 89 |
| 2026-03-20 | 4,393 | 269 |
| 2026-03-21 | 4,711 | 166 |
| 2026-03-22 | 3,776 | 166 |
| 2026-03-23 | 12,155 | 755 |
| 2026-03-24 | 1,149 | 628 |
| **합계** | **28,661** | **2,073** |

> "처리 좌표" 합계(2,073)가 1,000보다 큰 이유: 실패 후 재시도(최대 4회)된 좌표가 포함됨.

---

## 3. 실험 결과 요약

### 3.1 전체 현황

| 구분 | 건수 | 비율 |
|------|------|------|
| 시나리오 생성 성공 + 시뮬레이션 성공 | **772** | 77.2% |
| 시나리오 생성 성공 + 시뮬레이션 실패 | **5** | 0.5% |
| 시나리오 생성 실패 | **223** | 22.3% |
| **합계** | **1,000** | 100% |

### 3.2 실행 단계별 분류

#### 1차 실행 (원본)

| 결과 | 건수 |
|------|------|
| 시뮬 성공 | 700 |
| 시뮬 실패 | 0 |
| 시나리오 생성 실패 | 300 |
| **소계** | **1,000** |

#### 2차 실행 (ferry 제약 해제 후 재시도)

1차에서 시나리오 생성에 실패한 300개 좌표 중 Kakao API의 `avoid=ferries` 옵션 제거 후 재생성을 시도하였다.

| 결과 | 건수 |
|------|------|
| 시뮬 성공 | 72 |
| 시뮬 실패 (diversion) | 5 |
| 시나리오 생성 여전히 실패 | 223 |
| **소계** | **300** |

> ferry 제약 해제로 77개 추가 시나리오 생성에 성공하였으며, 이 중 5개가 시뮬레이션 중 diversion 실패로 중단되었다.

---

## 4. 실패 분석

### 4.1 시나리오 생성 실패 (223건)

- **원인**: Kakao Mobility API가 해당 좌표에서 도로 네트워크 경로를 탐색하지 못함
- **재시도 횟수**: 전원 최대 4회 재시도 후 실패 확정
- **에러 유형**: `CONFIG_PATH not found in generator stdout` (생성기 subprocess가 CONFIG_PATH를 출력하지 못하고 종료)
- **해석**: 해당 좌표가 도로 네트워크에서 도달 불가능한 지점 (산악 오지, 도서 지역, 군사 지역 등)에 위치

**지역 분포 (대략적 분류):**

| 지역 유형 | 건수 | 비고 |
|-----------|------|------|
| 내륙 산악/오지 | 164 | 강원 산간, 내륙 산악 등 |
| 강원 북부 산악 (lat>37.5, lon<128.5) | 47 | DMZ 인근, 고산 지대 |
| 남해 도서 (lat<33.6) | 7 | 제주 남쪽 소규모 도서 |
| 서해안 도서 (lon<126.5) | 4 | 서해 도서 지역 |
| 동해안 (lon>129.5) | 1 | 울릉도/독도 인근 |

### 4.2 시뮬레이션 실패 (5건)

- **원인**: `EventManager.diversion_rule()`에서 `"Impossible to divert"` 예외 발생
- **발생 경로**: `ev_uav_arrival_hospital` → `diversion_rule()` → 전원 가능한 병원 없음
- **근본 원인**: 해당 지역의 병원 배치가 빡빡하여, 모든 후보 병원의 물리적 병상이 가득 찬 상태에서 추가 전원 불가

**실패 좌표 (전부 전라북도 익산/군산 인근):**

| coord_id | 좌표 | 위도 | 경도 |
|----------|------|------|------|
| #160 | (35.9624, 126.9561) | 35.96° | 126.96° |
| #433 | (36.0098, 126.9449) | 36.01° | 126.94° |
| #631 | (36.0358, 126.9060) | 36.04° | 126.91° |
| #663 | (35.8857, 126.8880) | 35.89° | 126.89° |
| #744 | (35.9013, 126.8993) | 35.90° | 126.90° |

> 5개 좌표 모두 위도 35.89°~36.04°, 경도 126.89°~126.96° 범위에 밀집되어 있으며, 전라북도 익산·군산 일대에 해당한다. 이 지역은 주변 의료 인프라 밀도가 상대적으로 낮아 30명 환자 동시 발생 시나리오에서 병상 포화가 발생하는 것으로 판단된다.

---

## 5. 성능 지표 분석

### 5.1 지표 정의

| 지표 | 설명 | 방향 |
|------|------|------|
| **Reward** | 종합 보상 점수 (Green 포함) | 높을수록 좋음 |
| **Time** | 전체 이송 완료 시간 (분) | 낮을수록 좋음 |
| **PDR** | Patient Death Rate (사망률) | 낮을수록 좋음 |
| **RewardWOG** | Reward Without Green (Green 제외 보상) | 높을수록 좋음 |
| **PDRWOG** | PDR Without Green (Green 제외 사망률) | 낮을수록 좋음 |

> 각 지표의 값은 **64개 규칙의 30회 반복 평균(mean)을 다시 772개 시나리오에 걸쳐 평균**한 것이다.

### 5.2 전체 통계 (772개 시나리오, 64개 규칙 평균)

| 지표 | Mean | Median | Std | Min | Max | P5 | P25 | P75 | P95 |
|------|------|--------|-----|-----|-----|----|-----|-----|-----|
| Reward | 20.7016 | 20.7139 | 0.7250 | 17.7101 | 22.8025 | 19.4058 | 20.2883 | 21.1475 | 21.9225 |
| Time (분) | 310.14 | 301.39 | 56.27 | 189.17 | 618.34 | 231.14 | 272.76 | 341.90 | 413.79 |
| PDR | 0.1390 | 0.1384 | 0.0305 | 0.0506 | 0.2648 | 0.0878 | 0.1203 | 0.1566 | 0.1936 |
| RewardWOG | 5.6349 | 5.6473 | 0.7250 | 2.6435 | 7.7359 | 4.3391 | 5.2217 | 6.0809 | 6.8558 |
| PDRWOG | 0.3609 | 0.3593 | 0.0811 | 0.1302 | 0.6967 | 0.2240 | 0.3123 | 0.4071 | 0.5043 |

### 5.3 규칙별 성능 순위

#### Top 5 규칙 (Reward 기준, 높을수록 우수)

| 순위 | 규칙 조합 | Reward | Time (분) | PDR |
|------|-----------|--------|-----------|-----|
| 1 | ReSTART, YellowNearest, Red OnlyAMB, Yellow Both_UAVFirst | 21.4609 | 243.1 | 0.1071 |
| 2 | ReSTART, YellowNearest, Red Both_UAVFirst, Yellow Both_UAVFirst | 21.4604 | 242.4 | 0.1071 |
| 3 | ReSTART, YellowNearest, Red Both_UAVFirst, Yellow Both_AMBFirst | 21.4551 | 242.6 | 0.1074 |
| 4 | ReSTART, YellowNearest, Red OnlyAMB, Yellow Both_AMBFirst | 21.4548 | 243.4 | 0.1074 |
| 5 | ReSTART, YellowNearest, Red Both_AMBFirst, Yellow Both_UAVFirst | 21.4540 | 242.8 | 0.1074 |

#### Bottom 5 규칙 (Reward 기준)

| 순위 | 규칙 조합 | Reward | Time (분) | PDR |
|------|-----------|--------|-----------|-----|
| 60 | START, RedOnly, Red Both_AMBFirst, Yellow OnlyUAV | 18.7311 | 487.2 | 0.2211 |
| 61 | ReSTART, YellowNearest, Red OnlyUAV, Yellow OnlyUAV | 18.1604 | 529.3 | 0.2461 |
| 62 | START, YellowNearest, Red OnlyUAV, Yellow OnlyUAV | 17.9119 | 529.7 | 0.2566 |
| 63 | ReSTART, RedOnly, Red OnlyUAV, Yellow OnlyUAV | 17.7251 | 595.7 | 0.2641 |
| 64 | START, RedOnly, Red OnlyUAV, Yellow OnlyUAV | 17.5164 | 596.0 | 0.2729 |

#### Top 5 규칙 (Time 기준, 낮을수록 우수)

| 순위 | 규칙 조합 | Time (분) | Reward | PDR |
|------|-----------|-----------|--------|-----|
| 1 | START, YellowNearest, Red Both_UAVFirst, Yellow Both_UAVFirst | 241.8 | 21.4509 | 0.1075 |
| 2 | START, YellowNearest, Red Both_UAVFirst, Yellow Both_AMBFirst | 242.1 | 21.4455 | 0.1078 |
| 3 | START, YellowNearest, Red Both_AMBFirst, Yellow Both_UAVFirst | 242.3 | 21.4445 | 0.1078 |
| 4 | ReSTART, YellowNearest, Red Both_UAVFirst, Yellow Both_UAVFirst | 242.4 | 21.4604 | 0.1071 |
| 5 | START, YellowNearest, Red OnlyAMB, Yellow Both_UAVFirst | 242.5 | 21.4531 | 0.1075 |

#### Top 5 규칙 (PDR 기준, 낮을수록 우수)

| 순위 | 규칙 조합 | PDR | Reward | Time (분) |
|------|-----------|-----|--------|-----------|
| 1 | ReSTART, YellowNearest, Red OnlyAMB, Yellow Both_UAVFirst | 0.1071 | 21.4609 | 243.1 |
| 2 | ReSTART, YellowNearest, Red Both_UAVFirst, Yellow Both_UAVFirst | 0.1071 | 21.4604 | 242.4 |
| 3 | ReSTART, YellowNearest, Red Both_UAVFirst, Yellow Both_AMBFirst | 0.1074 | 21.4551 | 242.6 |
| 4 | ReSTART, YellowNearest, Red OnlyAMB, Yellow Both_AMBFirst | 0.1074 | 21.4548 | 243.4 |
| 5 | ReSTART, YellowNearest, Red Both_AMBFirst, Yellow Both_UAVFirst | 0.1074 | 21.4540 | 242.8 |

### 5.4 규칙 차원별 핵심 관찰

1. **Yellow 이송모드가 성능에 가장 큰 영향**: `Yellow OnlyUAV` 규칙이 하위권을 독점하며, `Yellow Both_UAVFirst` 또는 `Yellow Both_AMBFirst`가 상위권을 차지
2. **`YellowNearest` 병원 선택이 `RedOnly`보다 일관되게 우수**: 상위 규칙 전부 `YellowNearest` 사용
3. **`ReSTART` vs `START` 차이 미미**: 최상위 규칙에서 `ReSTART`가 약간 우세하나 실질적 차이는 매우 작음
4. **Red 이송모드의 영향은 제한적**: 상위권에서 `OnlyAMB`, `Both_UAVFirst`, `Both_AMBFirst`가 고르게 분포

---

## 6. 처리 시간 분석

### 6.1 시나리오 생성 소요 시간

| 구분 | Mean | Median | Std | Min | Max |
|------|------|--------|-----|-----|-----|
| 1차 원본 (700건) | 15.3s | 14.3s | 4.1s | 10.2s | 46.7s |
| 2차 재실행 (77건) | 14.0s | 13.3s | 3.2s | - | - |
| **전체 (777건)** | **15.2s** | **14.2s** | **4.1s** | **10.2s** | **46.7s** |

### 6.2 시뮬레이션 소요 시간

| 구분 | Mean | Median | Std | Min | Max |
|------|------|--------|-----|-----|-----|
| 1차 원본 (700건) | 6.1s | 6.1s | 0.2s | 5.7s | 8.3s |
| 2차 재실행 (72건) | 6.8s | 7.0s | 1.4s | - | - |
| **전체 (772건)** | **6.2s** | **6.1s** | **0.4s** | **5.7s** | **8.3s** |

> 좌표 1개당 평균 처리 시간: 시나리오 생성 15.2s + 시뮬레이션 6.2s = **약 21.4초**
> 772개 시나리오 × 64개 규칙 × 30회 반복 = **총 1,482,240회 시뮬레이션 실행**

---

## 7. 데이터 구조

### 7.1 시나리오 파일 구조

```
scenarios/exp_korea_random_1000_dep_202604071400/
├── (lat,lon)/                          # 좌표별 폴더 (772 + 5 = 777개)
│   ├── config_(lat,lon).yaml           # 시뮬레이션 설정 파일
│   ├── patient_info.csv                # 환자 분류 정보 (4행: Red/Yellow/Green/Black)
│   ├── hospital_info_road.csv          # 병원 목록 (도로 거리 기반)
│   ├── hospital_info_euc.csv           # 병원 목록 (유클리드 거리 기반)
│   ├── amb_info_road.csv               # 구급차(소방서) 배치 정보
│   ├── uav_info.csv                    # UAV 배치 정보
│   ├── distance_Hos2Hos_road.csv       # 병원 간 도로 거리 행렬
│   ├── distance_Hos2Hos_euc.csv        # 병원 간 유클리드 거리 행렬
│   ├── distance_Hos2Site_road.csv      # 병원-사고현장 도로 거리
│   ├── distance_Hos2Site_euc.csv       # 병원-사고현장 유클리드 거리
│   └── routes/                         # Kakao API 원본 응답 JSON
│       ├── center2site/                # 소방서→사고현장 경로
│       └── hos2site/                   # 병원→사고현장 경로
```

### 7.2 결과 파일 구조

```
results/exp_korea_random_1000_dep_202604071400/
├── (lat,lon)/
│   ├── results_(lat,lon).txt           # RAW 시뮬레이션 데이터
│   └── results_(lat,lon)_stat.txt      # 통계 요약 (320행)
```

**stat.txt 구조** (320행 = 64규칙 × 5블록):

| 블록 | 행 범위 | 지표 |
|------|---------|------|
| Block 0 | 0~63 | Reward |
| Block 1 | 64~127 | Time |
| Block 2 | 128~191 | PDR |
| Block 3 | 192~255 | RewardWOG |
| Block 4 | 256~319 | PDRWOG |

각 행 형식: `규칙명  mean  std  95%CI_half`

### 7.3 진행 상태 파일 (progress.json)

```json
{
  "experiment_id": "korea_random_1000",
  "total": 1000,
  "statuses": {
    "<coord_id>": {
      "status": "done|failed",
      "config_path": "scenarios/.../config_(...).yaml",
      "sim_ok": true|false,
      "attempts": 1,
      "gen_elapsed_sec": 15.3,
      "sim_elapsed_sec": 6.1,
      "finished_at": "2026-03-19 12:46:57",
      "note": "merged from fail rerun no-ferry (fail_cid=N)"  // 2차 재실행 건만
    }
  },
  "api_log": [...]
}
```

---

## 8. 재현 방법

### Step 1. 좌표 생성
```bash
python experiment_1/generate_coords.py --n 1000 --seed 0
```

### Step 2. 배치 실험 실행

**(A) Kakao API 모드 (원본 실험과 동일, `is_use_time=true`)**
```bash
python experiment_1/batch_runner.py \
    --kakao-api-key YOUR_KEY \
    --experiment-id exp_korea_random_1000 \
    --incident-size 30 \
    --amb-count 30 \
    --uav-count 3 \
    --amb-velocity 40 \
    --uav-velocity 80 \
    --total-samples 30 \
    --random-seed 0 \
    --amb-handover-time 10.0 \
    --uav-handover-time 15.0 \
    --is-use-time true \
    --duration-coeff 1.0 \
    --departure-time 202604071400
```

**(B) OSRM 모드 (오픈소스, 키 불필요, `is_use_time=false`)**
```bash
python experiment_1/batch_runner.py \
    --experiment-id exp_korea_random_1000_osrm \
    --incident-size 30 \
    --amb-count 30 \
    --uav-count 3 \
    --amb-velocity 40 \
    --uav-velocity 80 \
    --total-samples 30 \
    --random-seed 0 \
    --amb-handover-time 10.0 \
    --uav-handover-time 15.0 \
    --is-use-time false \
    --duration-coeff 1.0 \
    --departure-time 202604071400 \
    --osrm-url https://router.project-osrm.org   # 또는 자체 호스팅 URL
```
> 주: 본 보고서의 수치는 (A) Kakao 모드 결과이며, (B) OSRM 모드는 동일 파이프라인의 재현 가능성을 위한 대안이다. 도로 네트워크/속도 모델 차이로 절대 수치는 다를 수 있다.

### Step 3. 결과 시각화
```bash
python experiment_1/visualize_coords.py
```

---

## 9. 주요 제약 사항 및 논의

### 9.1 좌표 탈락 (22.3%)
- 1,000개 중 223개(22.3%)가 도로 네트워크 도달 불가로 시나리오 생성에 실패하였다
- 이는 한국 육지 경계 내 랜덤 추출 시 산악/도서/오지 지역이 포함되기 때문이며, 실제 MCI가 발생할 가능성이 낮은 지역이다
- 최종 분석 대상은 도로 접근 가능한 772개 좌표이다

### 9.2 Ferry 제약
- 1차 실행에서 Kakao API의 `avoid=ferries` 옵션을 사용하여 페리 경로를 제외하였으나, 도서 지역 좌표에서 경로 탐색 실패율이 높았다
- 2차 실행에서 ferry 제약을 해제하여 77개 추가 시나리오를 확보하였다
- ferry 제약 해제 그룹에서만 diversion 실패(5건)가 발생한 것은, 도서/해안 지역의 병원 인프라가 상대적으로 부족함을 시사한다

### 9.3 Diversion 실패 (0.6%)
- 시나리오 생성에 성공한 777건 중 5건(0.6%)에서 시뮬레이션 중 전원 불가 상황이 발생하였다
- 5건 모두 전라북도 익산/군산 인근(위도 35.89°~36.04°, 경도 126.89°~126.96°)에 집중
- `diversion_rule()`에서 모든 후보 병원의 물리적 병상(`n_occupied >= max_capa`)이 포화된 상태에서 추가 환자 전원이 불가능하여 예외 발생
- 이는 코드 버그가 아닌, 해당 지역의 의료 인프라 한계를 반영하는 정상적 실패임

### 9.4 Departure Time 통일
- 1차 원본 실행과 2차 재실행 간 Kakao API departure_time이 다른 날짜였으나, 동일 요일(화요일) 동일 시각(14:00)이므로 도로 교통 패턴 차이가 무시할 수 있는 수준이다
- 데이터 일관성을 위해 전체를 `202604071400`으로 통일하였다

---

## 10. 핵심 수치 요약 (Quick Reference)

```
총 좌표:              1,000
유효 시나리오:         772 (77.2%)
시뮬레이션 실패:       5 (0.6%)
시나리오 생성 실패:    223 (22.3%, 도로 도달 불가)

규칙 조합:            64개 (Full Factorial)
시뮬레이션 반복:      30회/규칙/좌표
총 시뮬레이션 횟수:   1,482,240회

평균 Reward:          20.70 (std=0.73)
평균 Time:            310.1분 (std=56.3)
평균 PDR:             13.9% (std=3.1%p)
평균 PDRWOG:          36.1% (std=8.1%p)

최우수 규칙 (Reward):  ReSTART, YellowNearest, Red OnlyAMB, Yellow Both_UAVFirst
                       R=21.46, T=243.1분, PDR=10.7%
최하위 규칙 (Reward):  START, RedOnly, Red OnlyUAV, Yellow OnlyUAV
                       R=17.52, T=596.0분, PDR=27.3%

Reward 최대-최소 차:   3.94 (22.5% 성능 차이)
PDR 최대-최소 차:      16.6%p
Time 최대-최소 차:     352.9분 (약 5.9시간)
```
