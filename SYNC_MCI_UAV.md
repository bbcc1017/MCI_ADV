# MCI_UAV 시뮬 정합성 동기화 기록 (2026-08-13)

이 저장소의 시뮬레이션 코드를 연구 저장소 **MCI_UAV**(`bbcc1017/MCI_UAV`, 브랜치 `main`)의
정본과 일치시키고, 고속 실행경로(`src/sim_src_upgrade`)를 이식했다.

동기화 직전 상태: 마지막 커밋 `d85cff6`(2026-07-02, 성남시의료원 헬기장 정정). 그 이후
MCI_UAV 에서 이루어진 시뮬 정합성 수정이 전부 빠져 있었다.

## 원칙

* **시뮬 로직은 MCI_UAV 정본과 일치**시킨다(§1 의 의도적 차이 2건 제외).
* **이 저장소의 산출물 계약은 바꾸지 않는다** — 결과 파일명·스키마·대시보드가 읽는 열,
  경로 JSON, trace JSON 은 그대로 나온다. 추가만 하고 제거하지 않는다.

## 1. 바이트 동일하게 맞춘 파일 (`src/sim_src/`)

`EntityManager.py` · `EventManager.py` · `ScenarioManager.py` ·
`MCIEnvironment_gymnasium.py` · `RuleManager.py` · `main.py`

MCI_UAV 정본과 **로직 동일**. 파일 단위 md5 도 `EntityManager` · `EventManager` ·
`ScenarioManager` · `MCIEnvironment_gymnasium` 은 일치하고, 다음 두 개만 의도적으로 다르다.

| 파일 | 차이 | 이유 |
|---|---|---|
| `RuleManager.py` | `ShinHeuristics` import 와 `include_shin` 분기 제거 | 이 저장소는 Shin 문헌 휴리스틱을 비교군으로 쓰지 않는다(§2) |
| `main.py` | 시뮬 로그 파일 기본 꺼짐(`--log` 로 켬) | Orchestrator 가 실행마다 stdout 을 이미 보관한다(§2) |

고속 사본의 G0 게이트(`origin_sync.py --check`)는 PASS — 사본이 파생된 원본이 곧 현재 이
저장소의 `src/sim_src` 다(Shin 제거를 사본에도 동일 반영한 뒤 `--write` 로 재기준화).

### 반영된 정합성 수정 (동작이 바뀌는 것들)

| # | 내용 | 위치 |
|---|---|---|
| 1 | **병원 후보 순회를 인덱스순 → 수단별 실제 ETA 순**. 병원 슬롯 인덱스는 도로 *소요시간* 순인데, `is_use_time=False` 면 시뮬의 실제 ETA 는 `road_dist/velocity` 이고 UAV 는 직선거리·헬기장 한정이라 인덱스순이 맞지 않았다. `RedOnly`/`YellowNearest` 의 Red·Yellow 순회 4곳을 `_ordered_hospital_indices(candidates, mode)` 로 통일 | `RuleManager` |
| 2 | **ReSTART `theta`** 를 병원 배열 앞 3개 평균이 아니라 **실제 ETA 최소 3개**의 왕복 평균으로. UAV `theta` 는 헬기장 병원만 후보 | `RuleManager` |
| 3 | **AMB 폴백 조건 버그**: Red 를 AMB 로 보낼지 판정하는 자리가 `yellow_exist` 를 보고 있었다 → `red_exist` | `RuleManager` |
| 4 | **발송 용량 게이트 통신축 재정의**: `occ`(기본, 통신 가용) = 입원 census + 이송중 in-flight / `psent`(통신 단절) = 현장이 보낸 누적. `MCI_CAP_GATE` 로 토글하며 휴리스틱·RL·obs 가 같은 정의를 공유 | `RuleManager`, `MCIEnvironment_gymnasium`, `EntityManager.in_flight_by_hospital` |
| 5 | **G/B 일괄이송**: 후보 순회를 수단별 ETA 순으로, 게이트를 `max_send − p_sent` 에서 **물리 입원용량**(`occ+in_flight < max_capa+max_queue`)으로. `p_sent` 는 퇴원에도 줄지 않는 누적값이라 장기·과부하 에피소드에서 전 병원이 소진돼 `RuntimeError` 로 죽었다. 주석에만 있고 미구현이던 "등급 무관 최근접" 폴백을 구현 | `EventManager.default_transportation_GB` |
| 6 | **diversion**: 같은 이유로 `p_sent` 게이트 제거 → 물리용량. 여유 병원이 없으면 최근접 치료가능 병원으로 강행(재차 diversion 으로 자연 해소)하고, 치료가능 병원 자체가 없을 때만 예외 | `EventManager.diversion_rule` |
| 7 | **OVERTIME 은 truncation** — `terminated=True` 로 주면 학습·평가에서 종단으로 취급돼 편향이 생긴다. `main.py` 도 `done = done or truncated` 로 수신 | `MCIEnvironment_gymnasium`, `main.py` |
| 8 | **정확 woG**: `cumul_reward − total_Green` 근사를 `info['r_woG']` 누적 + `env.preventable_woG` 로 교체. 근사식은 미처치 Green 이 남으면(절단·과부하) 과소산출된다. 정상 종료(전원 처치)에선 값이 같다 | `MCIEnvironment_gymnasium`, `main.py` |
| 9 | **`reset(seed)` 재현성**: 시뮬 동역학 rng(`EventManager`)까지 재시드. 기존엔 미사용 dead 변수만 갈아끼워 env 재사용 시 same-seed 비교가 조용히 깨졌다 | `MCIEnvironment_gymnasium` |
| 10 | 생성자 자동 `reset()` 제거 — 헛 `ev_onset` 1회가 사라진다 | `MCIEnvironment_gymnasium` |
| 11 | 자원·부하 런타임 노브 `MCI_INCIDENT_SIZE` / `MCI_CAPA_SCALE` / `MCI_AMB_NUM` / `MCI_UAV_NUM` (미설정 시 동작 불변) | `ScenarioManager` |
| 12 | ~~문헌 비교군 Shin and Lee (2020) 16종~~ → **이 저장소에서는 제외**(§2). 규칙은 항상 Full64 | `RuleManager` |
| 13 | `MCI_CAP_GATE=psent` 실행이 occ 결과를 덮지 않도록 결과 파일명에 `_psent` 접미사. 기본 `occ` 에서는 파일명 불변 | `main.py` |
| 14 | 시뮬 로그 파일(`experiment_logs/sim_<exp>_<ts>.log`) — **기본 꺼짐**, `--log` 로만 켬 | `main.py` |
| 15 | `RuleManager` 의 ND-TRACE 디버그 블록 제거(stderr 스팸) | `RuleManager` |

### 동기화가 결과를 실제로 바꾼 폭 (서울시청 좌표 · OSRM · 병원 9곳 · 환자 30 · 64룰 × 5에피)

| 지표 | 동기화 전 | 동기화 후 | Δ평균 | 변한 원소 |
|---|---:|---:|---:|---:|
| reward | 21.074425 | 21.098569 | +0.024144 | 170/320 |
| time | 200.656418 | 200.121627 | −0.534791 | 170/320 |
| PDR | 0.072150 | 0.071308 | −0.000843 | 170/320 |
| reward_woG | 7.674425 | 7.698569 | +0.024144 | 256/320 |
| PDR_woG | 0.172077 | 0.170553 | −0.001525 | 276/320 |

`Best-of-64` PDR_woG 0.088010 → **0.081303** (최선 규칙은 동일:
`START, YellowNearest, Red Both_AMBFirst, Yellow Both_AMBFirst`). 64룰 중 **52개**의 평균
PDR_woG 가 바뀌었다. `reward` 는 그대로인데 `reward_woG` 만 바뀐 원소가 있는 것은 8번(정확 woG)
때문이다. **동기화 이전에 낸 수치와 이후 수치를 섞어 인용하면 안 된다.**

### ⚠️ 위 표는 15건 전체의 합이다 — 1번(ETA순 정정) 단독 기여는 따로 봐야 한다

`_ordered_hospital_indices` 만 "인덱스 순서 그대로"로 되돌리고 나머지를 전부 새 코드로 고정해
측정하면(같은 시드·64룰×10에피):

| 좌표 | 병원수 | 순서 교체만의 효과 |
|---|---:|---|
| 서울시청 (OSRM) | 9 | **0/64 변화** (Δ 0.000000) |
| 서울시청 (duration 축) | 9 | **0/64 변화** (Δ 0.000000) |
| 강릉 (OSRM) | 15 | **22/64 변화** — 전부 `RedOnly`(22/32), 전부 UAV 관여(22/60). 전체 평균 PDR_woG 0.386158 → **0.384468** (−0.001689 개선), Best-of-64 불변 |

이유: 병원 총용량이 부하의 6~15배라 발송 게이트(`hos_max_send > cap_used`)가 사실상 안 걸린다
→ 순회는 거의 항상 **첫 후보**를 집는다. 그래서 인덱스순과 ETA순의 **첫 원소가 갈릴 때만**
동작이 바뀐다.

* 서울시청: AMB Yellow 전체 순회가 `[0,1,2,3,4,…]` vs `[0,1,2,4,3,…]` 로 다르지만 **첫 원소가
  둘 다 0** → 결과 불변. UAV 헬기장 순서도 일치.
* 강릉: UAV 헬기장 순서가 `[10,12,13,14]`(인덱스) vs `[10,14,12,13]`(ETA). `RedOnly` 는 Yellow 를
  tier3 에서 제외하므로 후보가 `[12,13,14]` vs `[14,12,13]` 이 되어 **첫 원소가 12 → 14 로 바뀐다**.
  `YellowNearest` 는 tier 제외가 없어 첫 원소가 10 으로 같아 0/32.

즉 서울시청 표의 52/64 변화는 대부분 **8번(정확 woG)·5·6번(용량 게이트)·2번(theta)** 등
나머지 항목에서 온 것이다. 1번은 **좌표에 따라 0 이거나 UAV·`RedOnly` 조합에서 국소적으로**
효과가 난다.

## 2. 이 저장소 고유로 **유지**한 것 (의도적 차이)

| 항목 | 유지 이유 |
|---|---|
| `make_csv_yaml_dynamic.py` CLI 기본값 — `incident_size 30`, `amb_velocity 40`, `uav_velocity 80`, `handover 10/15`, `total_samples 30`, `uav_count 3`, `is_use_time True`(Kakao) | 대시보드·사용자 매뉴얼에 문서화된 값. MCI_UAV 는 연구용 기본값(100 / 50·200 / 5·10 / 1000 / 25 / OSRM)이 다르다. 기본값은 시뮬 로직 정합성과 무관하다 |
| `uav_info.csv` 의 `종별코드` · `수술실수` · `병상수` 열 | `MCI_Streamlit` 의 헬기장 병원 마커가 읽는다. sim 은 참조하지 않으므로 열 추가는 정합성에 영향 없음 |
| `generate_scenario(uav_num=None)` → `uav_count` 를 런타임 대수로 사용 | 기존 대시보드 계약(생성 대수 = 런타임 대수) 유지. MCI_UAV 처럼 superset/런타임을 분리하려면 `--uav_num` 을 명시 |
| `src/sim_src/config.yaml` 의 경로·속도·시각 값 | 이 저장소 템플릿. `rule_info` 에 `include_standard` 만 추가했다 |
| **Shin 휴리스틱 미포함** | 이 저장소의 비교 대상은 Full64 뿐이다. `ShinHeuristics.py`·`ShinAlignedHeuristics.py` 를 두지 않고 `RuleManager` 의 `include_shin` 분기도 제거했다 |
| **시뮬 로그 기본 꺼짐** | `main.py --log` 로만 켠다. Orchestrator 의 실행 로그(`experiment_logs/<coord>_<ts>.txt`)는 대시보드가 경로를 표시하므로 기본 켜짐이고 `MCI_WRITE_RUN_LOG=0` 으로 끈다 |
| **고속경로 기본 켜짐 · trace 항상 생성** | `Orchestrator.run_simulation` 의 `use_fast_core`·`trace` 기본값이 켜짐이다(§4). MCI_UAV 는 드라이버별로 런처를 명시 호출한다 |

## 3. 시나리오 생성기에 반영한 것 (`src/sce_src/make_csv_yaml_dynamic.py`)

산출물은 기존 그대로 나오고(경로 JSON 포함), 아래가 더해졌다.

* **병원 중복 제거** — 소스 풀을 `요양기관명` 기준 dedup. 동명 병원 때문에 같은 병원이 두 슬롯을
  차지하던 결함(P1-a) 차단.
* **`hospital_info.csv` 에 `x좌표`/`y좌표` 열 추가** — 병원간 거리행렬을 **이름+좌표 키**로
  조회하게 되어 동명 병원 오매칭이 사라진다. 유클리드 행렬도 이 좌표를 직접 쓴다.
* **Kakao `avoid=roadevent` 상시 적용** — 유고(공사·사고 통제)로 `result_code 105/106` 이
  떠서 생성 자체가 실패하던 문제. 유고가 없으면 영향 없다.
* **좌표 스냅 + OSRM 폴백** — 도로에 스냅되지 않는 산간/오지 좌표는 OSRM `/nearest` 로 가장
  가까운 도로에 스냅해 Kakao 재시도, 해상·페리·완전고립은 OSRM 라우팅으로 폴백. 스냅 이동거리·
  폴백 레그를 **`route_adjustments.json`** 과 `ROUTE_ADJUST:` stdout 으로 남긴다(신규 산출물).
  할당량/인증 오류는 폴백하지 않고 그대로 올린다(키 로테이션 담당).
* Kakao 400 응답 본문 노출 — 할당량 소진(`API limit has been exceeded`)과 좌표 불량을 구분.
* `KAKAO_API_KEY` 환경변수 자동 사용(인자 미지정 시).
* `--fixed_hos_num` / `--min_hos_num` / `--max_hos_num` (병원 수 cap / floor / cap-only).
  전부 미지정이 기본 = 기존 동적 선정과 동일.

## 4. 고속 실행경로 (`src/sim_src_upgrade/`)

사용법·검증 기록·주의사항은 `src/sim_src_upgrade/README.md` 참조.

**대시보드는 별도 설정 없이 자동으로 고속경로를 탄다.** `Orchestrator.run_simulation` 의
`use_fast_core` 기본값이 켜짐이고(`MCI_FAST_CORE=0` 으로 전역 비활성), `trace` 기본값도
켜짐이라 대시보드 애니메이션이 쓰는 `trace_*.json` 이 항상 생성된다. 고속 런처 파일이 없는
체크아웃에서는 조용히 기존 `main.py` 경로로 폴백한다.

```bash
# CLI 로 직접 (산출 파일 바이트 동일)
python src/sim_src_upgrade/drivers/run_sim_fast.py -- --config_path "$CFG" --trace

# Orchestrator (인자 없이 = 고속 + trace)
orc.run_simulation(config_path)
orc.run_simulation(config_path, use_fast_core=False)   # 원본 코어 강제
```

반환 dict 에 `sim_core`(`"fast"`/`"origin"`)·`trace` 가 들어가고, 실행 로그 첫 줄에도
`=== SIM_START ... (core=fast, trace=True) ===` 로 기록된다.

검증(서울시청 좌표): 지표 `64규칙 × 10에피 × 5지표` = **3,200 원소 전부 비트동일(최대차 0.0)**,
`results_*.txt` · `results_*_stat.txt` · `trace_*.json`(5.5MB) **바이트 동일**, in-process
배속 **2.15×**.

> ⚠️ **콘솔 출력만 다르다.** 고속 코어는 이벤트별 `print(c_event)` 와 `Action:` 출력을
> `TRACE_PRINT=False` 로 막는다 → 같은 실행의 stdout 이 3.1MB(68,029줄) → 17.8KB(332줄).
> `Orchestrator.run_simulation` 은 stdout 을 `experiment_logs/` 에 보관만 하고 파싱하지
> 않으며, 대시보드는 `results_*.txt` 와 `trace_*.json` 을 읽으므로 기능 영향은 없다.
> 이벤트 스트림이 필요하면 `src/sim_src_upgrade/core/EventManager.py` 의
> `TRACE_PRINT = True` 로 켠다(느려진다).

## 5. 재검증 방법

```bash
# 원본 드리프트 (사본 vs src/sim_src)
python src/sim_src_upgrade/origin_sync.py --check

# 구 코어 vs 고속 코어 동치 (64룰 × N에피)
python src/sim_src_upgrade/verify/sim_equivalence.py --config "$CFG" --n_eps 10

# 산출물 바이트 대조
python src/sim_src/main.py --config_path "$CFG" --trace           # 구 코어
python src/sim_src_upgrade/drivers/run_sim_fast.py -- --config_path "$CFG" --trace
cmp old/results_X.txt new/results_X.txt
```

## 6. `is_use_time` 정합성 — 적용 범위 (사용자 확정 2026-08-14)

정합성 요구는 **"휴리스틱의 `Nearest` 가 `is_use_time` 과 일치할 것"** 하나다. 구급차 함대
구성과 파일 인덱스 정렬은 이 요구의 대상이 아니다.

### 6.1 요구 — 충족됨

병원을 "가까운 순"으로 고르는 모든 자리가 `ScenarioManager` 가 `is_use_time` 을 반영해 만든
**수단별 실제 평균 ETA**(`amb_HtoS_t[0]` / `uav_HtoS_t[0]`)를 기준으로 랭킹한다.

| 자리 | 근거 |
|---|---|
| `Universal_Rule` 의 `RedOnly`·`YellowNearest` × Red·Yellow 병원 순회 4곳 | `RuleManager._ordered_hospital_indices` → `RuleManager.py:126` `eta = uav_eta if mode==1 else amb_eta` |
| ReSTART `theta` | `nearest_roundtrip_mean(amb_eta)` / UAV 는 헬기장 한정 |
| G/B 일괄이송 후보 순회 (tier2 → tier3 → 무등급 폴백) | `EventManager.default_transportation_GB` → 수단별 `argsort(eta)` |

기준값은 AMB = API duration(`is_use_time=True`) 또는 `road_dist × 60/velocity`(False),
UAV = `euc_dist × 60/uav_velocity`(항상). 즉 **모드·라우팅 모드에 따라 자동으로 맞는 축**을 쓴다.

### 6.2 대상 아님 — 구급차 함대 선정과 인덱스 정렬

* `amb_station_info.csv` 는 계속 **도로 소요시간 오름차순**으로 저장하고, `ScenarioManager` 가
  `head(amb_num)` 으로 자른다. 구급차는 어차피 **전원이 t=0 에 출동해 현장으로 모이는** 자원이고
  (`EventManager.ev_onset` 이 대수만큼 `amb_arrival_site` 이벤트를 한 번에 생성), 어느 센터가
  뽑혔는지는 의사결정 변수가 아니다 — 현장 도착 후에는 `amb_wait[0]` 풀에서 꺼내 쓸 뿐이다.
* 병원 인덱스도 **도로 소요시간 오름차순 유지**. 순회는 위 6.1대로 매번 실제 ETA 로 재정렬하므로
  인덱스 순서는 슬롯 레이아웃일 뿐이고 결정에 영향이 없다.
* 참고 수치(정합성 문제가 아니라 정의 차이의 크기): MCI_UAV 시군구 250좌표에서 OSRM 모드일 때
  duration 순 상위 30대와 거리 순 상위 30대는 multiset 일치 31/250, 평균 2.40대 교체, 평균
  응답시간 차 +0.394분(최대 +6.05). **최속 1대는 전 좌표 동일**이라 차이는 함대 꼬리에서만 난다.

### 6.3 잠복 (현재 무해, 손대지 않음)

`ScenarioManager` 의 `hos_closest_second` / `hos_closest_third` / `hos_closest_*_fromH` 는
수단별 ETA 가 아니라 **거리** argmin 이다. `src/` · `tools/` 전수 검색 결과 **소비처 0곳**인
죽은 속성이라 현재 영향은 없다. 다만 나중에 휴리스틱에 배선하면 6.1 의 요구를 깨므로, 배선
전에 ETA 기준으로 바꿔야 한다. 지금 고치지 않는 이유는 두 저장소의 `src/sim_src` 바이트
동일성과 고속 사본의 G0 매니페스트가 함께 깨지기 때문이다 — 고칠 때는 **MCI_UAV 정본 →
ADV → `origin_sync.py --write` → 동치검증** 순서로 한다.
