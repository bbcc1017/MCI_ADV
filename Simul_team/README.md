# MCI 대량 재난 사고 시뮬레이션 플랫폼

## 프로젝트 개요

대량 재난 사고(Mass Casualty Incident) 발생 시 환자 이송 최적화를 위한 시뮬레이션 및 분석 플랫폼입니다.

### 주요 구성
- **시뮬레이션 엔진**: 구급차(AMB)와 드론(UAV)을 활용한 환자 이송 최적화
- **자동화 도구**: PowerShell 기반 시나리오 일괄 생성 및 실행
- **대시보드**: Streamlit 기반 웹 인터페이스로 경로 시각화, 통계 분석, 시나리오 관리

---

## 🎯 MCI_Streamlit 대시보드

### 주요 기능

#### 1. **Maps 탭** - 경로 시각화
- 구급차/UAV 경로를 지도에 표시 (Folium 기반)
- Light/Dark 테마 지원
- 혼잡도별 색상 구분 (카카오 교통 정보)
- C→S (안전센터/소방서 → 사고지점), S→H (사고지점 → 병원) 경로 개별 토글

#### 2. **Scenarios 탭** - 로그 분석
- 실험 로그 파일 뷰어
- 환자별 구조·이송·치료 타임라인 요약
- 전체 이벤트 테이블 (시뮬레이션 세부 과정)
- Rule/Iteration 선택 기능

#### 3. **Analytics 탭** - 통계 분석
- 64개 시나리오 자동 평가
- ANOVA 분석 (One-way, RCBD, Full Factorial)
- Shapiro-Wilk 정규성 검정
- Tukey HSD, Games-Howell, Friedman 사후검정 자동 선택
- **A그룹 교집합**: Reward, Time, PDR 모두에서 최상위 시나리오 자동 추천
- 잔차 진단 (QQ plot, 히스토그램)

#### 4. **Data Tables 탭** - 데이터 편집
- CSV 파일 실시간 편집 (자동 백업)
- 병원/소방서 마스터 데이터 조회
- 수정값으로 즉시 재실행

#### 5. **Rerun 탭** - 시나리오 재실행
- 기존 YAML 파일 기반 재실행

#### 6. **Generate 페이지** (독립 실행)
- 카카오 API 기반 신규 시나리오 생성
- 실시간/미래시간 교통정보 반영
- 위도/경도, 환자수, 구급차수, UAV수 등 파라미터 설정
- 생성 후 즉시 시뮬레이션 실행

### 설치 및 실행

#### 환경 요구사항
- Python 3.9 이상
- Streamlit 1.34+

#### 설치
```bash
# Conda 환경 생성 (권장)
conda create -n MCI python=3.9
conda activate MCI

# 필수 패키지 설치
pip install streamlit streamlit-folium pandas numpy openpyxl altair folium pyyaml scipy statsmodels pingouin requests haversine geopandas shapely gymnasium
```

#### 실행
```bash
# 메인 대시보드
streamlit run MCI_Streamlit.py

# 시나리오 생성 페이지 (독립)
streamlit run pages/Generate.py
```

### 디렉토리 구조
```
Simul_team/
├── scenarios/                          # 시나리오 데이터
│   ├── 안전센터와 소방서.csv              # 소방서/119안전센터 마스터
│   ├── 엑셀 결합 데이터.xlsx             # 병원 마스터
│   ├── ctprvn.shp/shx/dbf              # 시도 경계 shapefile
│   └── exp_{YYYYMMDD_HHMMSS}_dep_{timestamp}/
│       ├── {exp}_summary.csv           # 실험 요약
│       └── (lat,lon)/                  # 좌표별 폴더
│           ├── config_(lat,lon).yaml   # 시뮬레이션 설정
│           ├── patient_info.csv        # 환자 정보
│           ├── hospital_info_road.csv  # 병원 정보
│           ├── amb_info_road.csv       # 구급차 출동 정보
│           ├── uav_info.csv            # UAV 출동 정보
│           ├── distance_*.csv          # 거리 행렬
│           └── routes/                 # 경로 JSON
│               ├── center2site/        # C→S 경로
│               └── hos2site/           # S→H 경로
├── results/                            # 시뮬레이션 결과
│   └── exp_{YYYYMMDD_HHMMSS}_dep_{timestamp}/
│       └── (lat,lon)/
│           ├── results_(lat,lon).txt       # RAW 결과 (전체 데이터)
│           └── results_(lat,lon)_stat.txt  # 통계 요약 (평균, 표준편차, 95% CI)
├── experiment_logs/                    # 실행 로그
│   └── (lat,lon)_{timestamp}.log
├── MCI_Streamlit.py                    # 메인 대시보드
├── pages/
│   └── Generate.py                     # 시나리오 생성 페이지
├── main.py                             # 시뮬레이션 실행 스크립트
├── make_csv_yaml_dynamic.py            # 시나리오 생성 스크립트
├── orchestrator.py                     # 오케스트레이션 모듈
└── config.yaml                         # 기본 설정 템플릿
```

### 평가 지표
- **Reward**: 생존확률 합 (클수록 좋음)
- **Time**: 평균 환자 처리 시간 (작을수록 좋음)
- **PDR (Preventable Death Rate)**: 예방가능사망률 (작을수록 좋음)
- **w.o.G (without Green)**: Green 환자 제외 지표

### 시나리오 구조 (64개 조합)
```
2 (Phase) × 2 (Policy) × 4 (Red Action) × 4 (Yellow Action) = 64개

Phase:
  - START: 초기 전체 환자 배정
  - ReSTART: 병원 도착 시마다 재배정

Policy:
  - RedOnly: Red 환자만 먼저 배정
  - YellowHalf: Red + Yellow 50% 배정 후 나머지

Action (Red/Yellow):
  - OnlyUAV: UAV만 사용
  - OnlyAMB: 구급차만 사용
  - Both_UAVFirst: UAV 우선, 부족 시 구급차
  - Both_AMBFirst: 구급차 우선, 부족 시 UAV
```

### 사용 방법

#### 1. Settings (사이드바)
- 프로젝트 경로 입력
- 실험 ID 선택 (드롭다운)
- 좌표 선택 (드롭다운)
- 미니맵 자동 표시

#### 2. Maps 탭
- 지도 테마 선택 (Light/Dark)
- AMB C→S, S→H 경로 개별 체크박스
- UAV 경로 토글 (출동+이송)
- 혼잡도 범례 표시

#### 3. Scenarios 탭
- 로그 파일 선택
- Rule/Iteration 선택
- 환자 스토리 요약표 자동 생성
- 전체 이벤트 타임라인 조회

#### 4. Analytics 탭
- 표시할 지표 선택 (Reward, Time, PDR 등)
- 정렬 기준 선택 (Reward↓, PDR↑, Time↑)
- ANOVA 설계 선택 (One-way/RCBD/Full Factorial)
- 유의수준(alpha) 조정 (0.001~0.1)
- A그룹 교집합 자동 추천

#### 5. Data Tables 탭
- 편집할 CSV 선택
- 데이터 편집 후 저장 (자동 백업)
- 수정값으로 재실행 버튼

#### 6. Generate 페이지
- 카카오 API 키 입력
- 운행시간 모드 선택 (실시간/미래시간)
- 파라미터 설정 (위도, 경도, 환자수, 구급차수, UAV수, 속도 등)
- 시나리오 생성 및 즉시 실행

### 참고사항

#### 성능
- 500회 초과 반복 시 로그 뷰어 자동 비활성화
- 대용량 데이터 처리 시 로딩 시간 증가 가능

#### API
- 카카오 REST API 키 필요 (Generate 페이지)
- 실시간 교통정보 반영 (Kakao API)
- 미래시간 교통정보 지원 (YYYYMMDDHHMM 형식)

#### 파일 인코딩
- 한글 파일명: CP949 인코딩 사용
- CSV 파일: UTF-8-sig → CP949 자동 폴백

#### 데이터 보호
- CSV 편집 시 자동 백업 (`*_backup_{timestamp}.csv`)
- 원본 데이터 보존

#### 필수 파일
- `scenarios/안전센터와 소방서.csv`
- `scenarios/엑셀 결합 데이터.xlsx`
- `scenarios/ctprvn.shp/shx/dbf`

---

## 🔧 MCI_Experiment_Autonomation 자동화 도구 (v5.0)

### 사전준비

1. MCI conda 가상환경 설치

2. (MCI) 활성상태에서 패키지 설치
```bash
pip install pandas numpy requests haversine pyyaml geopandas shapely gymnasium scipy openpyxl streamlit streamlit-folium altair folium statsmodels pingouin
```

3. scenarios 폴더 안에 필수 파일 존재 확인
   - 안전센터와 소방서.csv
   - 엑셀 결합 데이터.xlsx
   - ctprvn.shp, ctprvn.shx, ctprvn.dbf

4. 프로젝트 폴더에 시뮬레이션 관련 파일들 존재 확인

5. 네이버 API 키 준비 (레거시, 카카오 API 권장)

### 실행순서

1. **사전준비 완료 후** `MCI_Experiment_Autonomation_v5.0.ps1` 더블클릭

2. **[📁 프로젝트 경로 설정]**
   - 엔터 입력 시 현재 디렉토리로 인식
   - `C:\Users\사용자명` 위치 권장

3. **[🐍 Conda 환경 탐지]**
   - "MCI 환경을 사용하시겠습니까?" → `y(Y)` 입력 시 자동 활성화
   - `n(N)` 입력 시 가상환경 리스트에서 선택

4. **[🔑 Naver API 키 설정]**
   - Client ID/Client Secret 순차 입력
   - 환경변수에 자동 저장

5. **[📦 Python 패키지 확인]**
   - 필수 패키지 자동 검사
   - 누락 시 피드백 제공

6. **[🎯 시뮬레이션 개수 설정]**
   - 생성할 시뮬레이션 개수 입력 (최대 10개)
   - 단일 좌표 파라미터 수정 실험 시 1개씩 실행 권장

7. **[⚙️ 고급 옵션]**

   **queue_policy**: 병원 대기열 설정
   - 기본값: 0
   - 옵션: `capa/2`, `capa/3`, `capa/4`, `0.5`, `0.333` 등
   - 소수점 버림 처리

   **util_by_tier**: 병상 가용률 설정
   - 사용 가능 병상수 = 전체 병상수 × (1 - util)
   - 기본값: `1:0.656, 11:0.461, etc:0.461`
   - 종별코드별 적용 (1=상급종합, 11=종합, 기타=일반)

   **buffer_ratio**: 병원 후보군 확장 비율
   - 기본값: 1.5
   - 도심/인프라 좋은 지역: 비율 낮춤
   - 농촌/산간 지역: 비율 높임
   - ※ AMB 후보군은 `make_csv_yaml_dynamic.py` 내 `multiplier=2` 사용

   **patient_info 파라미터**
   - Red 비율 (기본: 0.1)
   - Yellow 비율 (기본: 0.3)
   - Green 비율 (기본: 0.5)
   - Black 비율 (기본: 0.1)

   **hospital.max_send_coeff (a, b)**
   - 공식: `eff = a × capa + b × queue_capa`
   - 예시: `1,1` 또는 `1.5,1`

8. **[📋 디폴트 파라미터 설정]**
   - `y`: 기존 디폴트 파라미터로 일괄 생성
   - `n`: 개별 파라미터 수정 모드 진입

9. **[⚙️ 시뮬레이션 #N 설정]**

   **🎯 좌표 생성 모드**

   **🎲 대한민국 전국 완전랜덤**
   - shapefile 폴리곤 경계 내에서 uniform 분포로 추출
   - 해상 제외

   **🏙️ 특정 시도 선택**
   - 시도 단위 경계 기반 랜덤 추출
   - 선택 가능 지역:
     ```
     [1] 서울특별시      [2] 부산광역시
     [3] 대구광역시      [4] 인천광역시
     [5] 광주광역시      [6] 대전광역시
     [7] 울산광역시      [8] 세종특별자치시
     [9] 경기도          [10] 충청북도
     [11] 충청남도       [12] 전라북도
     [13] 전라남도       [14] 경상북도
     [15] 경상남도       [16] 제주특별자치도
     [17] 강원특별자치도
     ```

   **📍 수동 좌표 입력**
   - 위도, 경도 직접 입력
   - 범위: 위도 33.1~38.6, 경도 124.6~131.0

   **파라미터 수정**
   ```
   환자 수 [30]:
   구급차 수 [30]:
   UAV 수 [3]:
   구급차 속도 [40]:
   UAV 속도 [80]:
   시뮬레이션 반복 [10]:
   랜덤 시드 [0]:
   ```

   **[시뮬레이션 #1 설정 완료]**
   ```
   (예시)
   🎯 모드: 대구광역시 지역
   ⚙️ 환자: 30, 구급차: 30, UAV: 3
   ```

10. **[📋 실험 설정 최종 검토]**
    - 예상 소요시간 표시
    - 시뮬레이션 번호별 파라미터 요약
    - 네이버 API 예상 호출량
    - ★매우 신중하게 검토 필요

11. **시나리오 생성 및 실행**
    - `y` 입력 시 시나리오 생성 후 시뮬레이션 자동 실행
    - 완료 시 성공/실패 개수 및 상세 로그 출력

### 실행결과 파일

#### 실험 ID
- 형식: `exp_YYYYMMDD_HHMMSS_dep_{timestamp}`
- 시뮬레이션 개수 확정 시 자동 생성

#### scenarios 폴더
- `{exp}_summary.csv`: 실험 요약
- 컬럼:
  ```
  실험ID 순번, 생성모드, 생성유형, 좌표정보, 실제위도, 실제경도,
  주소, 도로명주소, 시도, 시군구, 읍면동, 리,
  시나리오생성_시작, 시나리오생성_소요(초),
  시뮬레이션_시작, 시뮬레이션_소요(초),
  실험_완료시간, 좌표별_총소요(초), 성공여부, 로그파일,
  환자수, max_send_coeff, 구급차수, UAV수,
  구급차속도, UAV속도, 시뮬레이션반복, 랜덤시드
  ```

#### results 폴더
- `results_(lat,lon).txt`: RAW 결과 (전체 데이터)
- `results_(lat,lon)_stat.txt`: 통계 요약
- 각 Rule 조합별 Reward, Time, PDR 평균, 표준편차, 95% 신뢰구간
- w.o.G (without Green) 지표 포함

#### experiment_logs 폴더
- `(lat,lon)_{timestamp}.log`: 시뮬레이션 실행 로그
- 터미널 출력 텍스트 기록

---

## 기술 스택

### 핵심 프레임워크
- **Streamlit**: 대시보드 프레임워워크
- **Folium**: 인터랙티브 지도 시각화
- **Gymnasium**: 강화학습 환경

### 데이터 처리
- **pandas**: 데이터프레임 처리
- **numpy**: 수치 계산
- **openpyxl**: 엑셀 파일 처리

### 시각화
- **Altair**: 차트 생성
- **streamlit-folium**: Streamlit + Folium 통합

### 통계 분석
- **statsmodels**: OLS 회귀, ANOVA
- **scipy**: Shapiro-Wilk, Friedman, t-test
- **pingouin**: Games-Howell 사후검정

### 지리 데이터
- **geopandas**: 지리 데이터 처리
- **shapely**: 폴리곤 처리
- **haversine**: 거리 계산

### API/네트워크
- **requests**: HTTP 요청 (Kakao/Naver API)
- **pyyaml**: YAML 파일 파싱

---

## 라이선스

(프로젝트 라이선스 명시 필요)

---

## 문의

(문의처 정보 추가 필요)
