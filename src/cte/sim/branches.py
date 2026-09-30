"""Branch 실행기: 같은 출발점에서 seed만 바꿔 여러 가지를 인과 시뮬레이션으로 생성한다.

Taste Miner(Phase 3)는 여기서 나온 branch들을 *비교만* 한다(원칙 11). 이 모듈은 branch를
만들 뿐 평가하지 않는다. 각 branch는 원장을 fork한 독립 SQLite 파일이다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from cte.causal.store import CausalLedgerStore, state_hash
from cte.phase2.interfaces import StepResult
from cte.sim.stepper import SceneStepper


class BranchRun(BaseModel):
    """branch 하나의 실행 결과."""

    seed: str = Field(description="이 branch의 seed.")
    path: str = Field(description="branch 원장 파일.")
    final_tick: int = Field(description="마지막 tick.")
    state_hash: str = Field(description="최종 상태 해시(재현성 검증).")
    steps: list[StepResult] = Field(description="step 결과들.")


def run_branches(
    store: CausalLedgerStore,
    *,
    seeds: list[object],
    steps: int,
    directory: str | Path,
    make_stepper: Callable[[CausalLedgerStore, object], SceneStepper],
) -> list[BranchRun]:
    """store의 현재 상태에서 seed별로 fork해 steps만큼 진행한다. 원본 store는 바뀌지 않는다."""
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs: list[BranchRun] = []
    for seed in seeds:
        path = out_dir / f"branch_{seed}.db"
        if path.exists():
            raise FileExistsError(f"{path}가 이미 있다(branch를 덮어쓰지 않는다)")
        branch = store.fork(path)
        try:
            results = make_stepper(branch, seed).run(steps)
            runs.append(BranchRun(seed=str(seed), path=str(path), final_tick=branch.tick, state_hash=state_hash(branch.materialize()), steps=results))
        finally:
            branch.close()
    return runs
