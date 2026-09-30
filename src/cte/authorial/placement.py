"""PressurePlacer — 작가가 causal 세계에 쓰는 *유일한* 경로.

작가 압력(ScenePressure)은 결과가 아니라 세계 조건(WorldCondition)으로만 물질화된다.
causal 쪽에는 조건의 세계 내 기술만 들어가고, 작가 의도(rationale), 압력 id, 장면 계획은
들어가지 않는다. 연결 정보는 authorial 쪽 ``PressurePlacement`` 에만 남는다(단방향 참조).
"""

from __future__ import annotations

from cte.authorial.models import ConstraintKind, PressureKind, PressurePlacement, ScenePressure
from cte.authorial.store import AuthorialLedgerStore
from cte.causal.store import CausalLedgerStore
from cte.domain import ConditionKind, WorldCondition
from cte.ids import new_id
from cte.tracing import ModuleRunRecorder

_FORCE_TO_CONDITION: dict[PressureKind, ConditionKind] = {
    PressureKind.TIME_LIMIT: ConditionKind.TIME_PRESSURE,
    PressureKind.SCARCITY: ConditionKind.SCARCITY,
    PressureKind.EXPOSURE_RISK: ConditionKind.EXPOSURE_RISK,
    PressureKind.OBSTACLE: ConditionKind.OBSTACLE,
    PressureKind.THIRD_PARTY: ConditionKind.SOCIAL,
    PressureKind.ENVIRONMENT: ConditionKind.WEATHER,
    PressureKind.SOCIAL_OBLIGATION: ConditionKind.SOCIAL,
}

_CONSTRAINT_TO_CONDITION: dict[ConstraintKind, ConditionKind] = {k: ConditionKind.CONSTRAINT for k in ConstraintKind}

DEFAULT_BLOCKS: dict[ConstraintKind, list[str]] = {
    ConstraintKind.NO_EXIT: ["move"],
    ConstraintKind.COMMUNICATION_CUT: ["call"],
}
"""제약 종류별로 기본적으로 막히는 행동. 행동의 *결과* 가 아니라 *가능 공간* 만 좁힌다."""


def place_pressure(
    pressure: ScenePressure,
    *,
    authorial: AuthorialLedgerStore,
    causal: CausalLedgerStore,
    recorder: ModuleRunRecorder | None = None,
) -> PressurePlacement:
    """압력을 세계 조건으로 배치하고 배치 기록을 작가 원장에 남긴다."""

    def _do() -> PressurePlacement:
        world = causal.world()
        tick = world.tick
        conditions: list[WorldCondition] = []
        for force in pressure.forces:
            conditions.append(
                WorldCondition(
                    id=new_id("cond"),
                    condition_kind=_FORCE_TO_CONDITION[force.pressure_kind],
                    description=force.description,
                    location_id=force.location_id or pressure.location_id,
                    magnitude=force.magnitude,
                    disclosure=force.disclosure,
                    started_tick=tick,
                    expires_tick=tick + force.duration_ticks if force.duration_ticks else None,
                    manifests_at_tick=tick + force.manifests_after_ticks if force.manifests_after_ticks else None,
                    manifest_description=force.manifest_description,
                )
            )
        for constraint in pressure.constraints:
            conditions.append(
                WorldCondition(
                    id=new_id("cond"),
                    condition_kind=_CONSTRAINT_TO_CONDITION[constraint.constraint_kind],
                    description=constraint.description,
                    location_id=constraint.location_id or pressure.location_id,
                    magnitude=1.0,
                    disclosure=constraint.disclosure,
                    started_tick=tick,
                    blocks_actions=list(
                        constraint.blocks_actions if constraint.blocks_actions is not None else DEFAULT_BLOCKS.get(constraint.constraint_kind, [])
                    ),
                )
            )
        # causal에 남는 reason은 세계 내 중립 문구다. 작가 의도는 여기 쓰지 않는다.
        with causal.commit(module="author.pressure_placement", reason="world conditions changed") as tx:
            tx.put(world.evolve(conditions=[*world.conditions, *conditions]))
            commit_id = tx.commit_id
        placement = PressurePlacement(
            id=new_id("placement"),
            pressure_id=pressure.id,
            placed_tick=tick,
            causal_commit_id=commit_id,
            causal_condition_ids=[c.id for c in conditions],
        )
        authorial.put(pressure)
        authorial.put(placement)
        return placement

    if recorder is None:
        return _do()
    if recorder.sink.ledger_kind != "authorial":
        raise ValueError("압력 배치 로그는 authorial 싱크에만 기록한다")
    with recorder.run("author.pressure_placement", principal_kind="author", input=pressure, tick=causal.tick) as handle:
        placement = _do()
        handle.commit_id = placement.causal_commit_id
        handle.set_output(placement)
        return placement
