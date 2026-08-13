"""`src/sim_src/main.py` 를 **한 줄도 안 고치고** 고속 코어로 실행하는 런처 (MCI_ADV 판).

원리
----
`main.py` 는 flat import 를 쓴다:

    from ScenarioManager import ScenarioManager
    from RuleManager import RuleManager
    from MCIEnvironment_gymnasium import MCIEnvironment_gym

이 런처는 `main.py` 를 실행하기 **전에** 그 flat 이름들을 `sys.modules` 에 고속 코어
모듈로 미리 등록한다. 그러면 `main.py` 의 import 가 고속판으로 해석되고, 실행 루프·
결과 파일(`results_*.txt` / `results_*_stat.txt` / `trace_*.json`)·로그는 원본 그대로다.

고속 코어는 패키지 상대 import(`from .EntityManager import ...`)라 flat 이름 주입에
간섭받지 않는다 — 그래서 구·신 코어를 한 프로세스에 동시에 올릴 수 있고, 그게 사전점검
(동치검증)의 전제다.

안전장치
--------
1. **G0 드리프트 검사** — 사본이 파생된 `src/sim_src` 해시가 그대로인지 확인. 원본이
   바뀌었으면 즉시 중단한다(`origin_sync.py --write` 로만 기준 갱신).
2. **사전점검** — 실제 실행 전에 같은 config 를 구·신 코어로 소규모(규칙 2 × 에피 3)
   돌려 지표가 완전히 같은지 확인한다. 다르면 중단(`--skip_preflight` 로만 생략).

사용
----
    # main.py 와 완전히 같은 인자를 그대로 넘긴다
    python src/sim_src_upgrade/drivers/run_sim_fast.py -- \\
        --config_path scenarios/exp_XXX/'(37.5665,126.978)'/config_'(37.5665,126.978)'.yaml

    # trace JSON 까지
    python src/sim_src_upgrade/drivers/run_sim_fast.py -- --config_path <cfg> --trace

    # 사전점검 규모 조정 / 생략
    python src/sim_src_upgrade/drivers/run_sim_fast.py --preflight_eps 5 -- --config_path <cfg>
    python src/sim_src_upgrade/drivers/run_sim_fast.py --skip_preflight -- --config_path <cfg>

주의
----
* 작업 디렉터리는 바꾸지 않는다. `main.py` 와 YAML 의 상대경로 규약이 그대로 유지되도록
  **저장소 루트에서** 실행할 것(대시보드/orchestrator 와 동일).
* BLAS 스레드 수는 건드리지 않는다 — 대시보드가 부르는 평소 `main.py` 실행과 환경을
  동일하게 두어 결과 비교가 항상 사과 대 사과가 되게 한다. 필요하면 `--pin_threads`.
"""
from __future__ import annotations

import argparse
import os
import runpy
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir)))  # → src/

from sim_src_upgrade._paths import SIM_SRC, ensure_paths  # noqa: E402

# 주입할 flat 이름 → 고속 코어 모듈 경로
FLAT_MODULES = {
    "EntityManager": "sim_src_upgrade.core.EntityManager",
    "EventManager": "sim_src_upgrade.core.EventManager",
    "ScenarioManager": "sim_src_upgrade.core.ScenarioManager",
    "RuleManager": "sim_src_upgrade.core.RuleManager",
    "MCIEnvironment_gymnasium": "sim_src_upgrade.core.MCIEnvironment_gymnasium",
}


def install_fast_core() -> list[str]:
    """flat 이름을 고속 코어 모듈로 `sys.modules` 에 등록. 등록된 이름 목록 반환."""
    import importlib

    installed = []
    for flat, dotted in FLAT_MODULES.items():
        if flat in sys.modules:
            # 이미 구 코어가 로드돼 있으면 교체한다(사전점검 후 이 상황이 정상).
            del sys.modules[flat]
        sys.modules[flat] = importlib.import_module(dotted)
        installed.append(flat)
    return installed


def _extract_config_path(passthrough: list[str]) -> str:
    """main.py 로 넘길 인자에서 --config_path 값을 뽑는다(사전점검용)."""
    for i, tok in enumerate(passthrough):
        if tok == "--config_path" and i + 1 < len(passthrough):
            return passthrough[i + 1]
        if tok.startswith("--config_path="):
            return tok.split("=", 1)[1]
    return "./config.yaml"   # main.py 기본값


def main() -> int:
    p = argparse.ArgumentParser(
        description="sim_src/main.py 를 고속 코어로 실행 (결과 동일, 시간만 단축)",
        epilog="`--` 뒤의 인자는 main.py 로 그대로 전달된다.")
    p.add_argument("--skip_preflight", action="store_true",
                   help="사전 동치검증 생략 (권장하지 않음)")
    p.add_argument("--preflight_eps", type=int, default=3, help="사전점검 에피소드 수 (기본 3)")
    p.add_argument("--preflight_rules", type=int, default=2, help="사전점검 규칙 수 (기본 2)")
    p.add_argument("--pin_threads", action="store_true",
                   help="BLAS 스레드를 1로 고정 (기본 off — 평소 main.py 실행과 환경 동일 유지)")
    args, passthrough = p.parse_known_args()
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]

    if args.pin_threads:
        for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS",
                  "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            os.environ.setdefault(v, "1")

    ensure_paths(rl=False, old_sim=True)

    # ---------- G0: 원본 드리프트 ----------
    from sim_src_upgrade import origin_sync
    try:
        origin_sync.check()
        print("[G0] PASS — 고속 사본이 현재 src/sim_src 에서 파생된 상태")
    except Exception as e:
        print(f"[G0] FAIL — {e}", file=sys.stderr)
        return 2

    config_path = _extract_config_path(passthrough)

    # ---------- 사전점검: 구·신 코어 지표 완전일치 ----------
    if not args.skip_preflight:
        if not os.path.isfile(config_path):
            print(f"[preflight] config 를 찾을 수 없어 사전점검 생략: {config_path}",
                  file=sys.stderr)
        else:
            from sim_src_upgrade.verify import sim_equivalence
            t0 = time.time()
            res = sim_equivalence.preflight(config_path,
                                            n_eps=args.preflight_eps,
                                            n_rules=args.preflight_rules)
            print(f"[preflight] {time.time() - t0:.1f}s")
            if not res["pass"]:
                print("[preflight] 지표 불일치 — 고속 실행을 중단한다.", file=sys.stderr)
                return 3

    # ---------- 고속 코어 주입 후 main.py 실행 ----------
    installed = install_fast_core()
    print(f"[fastcore] flat 모듈 {len(installed)}개 고속판으로 대체: {', '.join(installed)}")

    main_py = os.path.join(SIM_SRC, "main.py")
    sys.argv = [main_py] + passthrough
    t0 = time.time()
    runpy.run_path(main_py, run_name="__main__")
    print(f"[fastcore] main.py 완료 ({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
