"""Phase 2 시뮬레이터: Decision · Collision · Residue 루프(규칙 기반 구현 + LLM 제안기).

이 패키지는 ``cte.authorial`` 을 import하지 않는다. 입력은 Causal Ledger와 Context DTO뿐이다.
"""

from cte.sim.belief import RuleBeliefUpdater
from cte.sim.branches import BranchRun, run_branches
from cte.sim.collision import RuleCollisionResolver
from cte.sim.interrupter import ConditionInterrupter
from cte.sim.memory import RuleMemoryEncoder
from cte.sim.observation import RuleObservationDistributor
from cte.sim.proposers import HeuristicActionProposer, HighestUrgencySelector, LLMActionProposer, SoftmaxSelector
from cte.sim.residue import RuleResidueDeriver
from cte.sim.stepper import SceneStepper

__all__ = [
    "BranchRun",
    "ConditionInterrupter",
    "HeuristicActionProposer",
    "HighestUrgencySelector",
    "LLMActionProposer",
    "RuleBeliefUpdater",
    "RuleCollisionResolver",
    "RuleMemoryEncoder",
    "RuleObservationDistributor",
    "RuleResidueDeriver",
    "SceneStepper",
    "SoftmaxSelector",
    "run_branches",
]
