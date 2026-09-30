"""CTE 명령줄 도구(Typer).

cte init WORLD                      두 원장 파일 생성(마이그레이션)
cte seed-demo WORLD                 데모 세계 심기
cte context character WORLD ID      CharacterContext JSON 출력(모듈 로그 기록)
cte context narrator WORLD POV      NarratorContext JSON 출력
cte audit WORLD ID                  캐릭터/narrator context 누출 검사
cte snapshot WORLD LABEL            스냅샷
cte snapshots WORLD                 스냅샷 목록
cte diff WORLD A [B]                스냅샷 A → B(생략 시 현재) diff
cte rollback WORLD SNAP             스냅샷으로 되돌리기(보상 commit)
cte ledger WORLD                    원장 항목 출력
cte trace WORLD NODE [--forward]    provenance 추적
cte assess WORLD                    오신념 판정(시뮬레이터 전용 출력)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from cte.access import ContextBuilder, LeakAuditor, Principal
from cte.causal.provenance import ProvenanceGraph
from cte.causal.store import CausalLedgerStore
from cte.causal.truth import assess_all
from cte.demo import seed_demo
from cte.ids import new_id
from cte.phase2.interfaces import StepResult
from cte.sim import SceneStepper, SoftmaxSelector, run_branches
from cte.tracing import ModuleRunRecorder
from cte.workspace import Workspace

app = typer.Typer(help="WR9 Causal Taste Engine — Phase 1 Causal Core", no_args_is_help=True)
context_app = typer.Typer(help="agent별 Context DTO 생성", no_args_is_help=True)
app.add_typer(context_app, name="context")

WorldArg = Annotated[Path, typer.Argument(help="world 디렉터리(causal.db / authorial.db 위치)")]


def _echo_json(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False))


@app.command()
def init(world: WorldArg) -> None:
    """두 원장 파일을 만들고 마이그레이션한다."""
    ws = Workspace(world)
    with ws.open_causal() as c, ws.open_authorial() as a:
        typer.echo(f"causal:    {c.path}\nauthorial: {a.path}")


@app.command("seed-demo")
def seed_demo_cmd(world: WorldArg) -> None:
    """데모 세계(장맛비 한옥, 위조 편지)를 심는다."""
    ws = Workspace(world)
    with ws.open_causal() as c, ws.open_authorial() as a:
        ids = seed_demo(c, a, authorial_recorder=ws.authorial_recorder(a))
        typer.echo(f"seeded: {ids} (tick={c.tick})")


@context_app.command("character")
def context_character(world: WorldArg, character_id: str) -> None:
    """CharacterContext를 JSON으로 출력한다."""
    ws = Workspace(world)
    with ws.open_causal() as c, ws.open_authorial() as a:
        builder = ContextBuilder(c, recorder=ws.causal_recorder(c), extra_secret_strings=list(a.iter_strings()))
        _echo_json(builder.character_context(character_id).model_dump(mode="json"))


@context_app.command("narrator")
def context_narrator(world: WorldArg, pov_character_id: str, since_tick: Annotated[int | None, typer.Option(help="구간 시작 tick")] = None) -> None:
    """NarratorContext를 JSON으로 출력한다."""
    ws = Workspace(world)
    with ws.open_causal() as c, ws.open_authorial() as a:
        builder = ContextBuilder(c, recorder=ws.causal_recorder(c), extra_secret_strings=list(a.iter_strings()))
        _echo_json(builder.narrator_context(pov_character_id, since_tick=since_tick).model_dump(mode="json"))


@app.command()
def audit(world: WorldArg, character_id: str) -> None:
    """캐릭터와 그 인물 POV narrator context의 누출 여부를 검사한다."""
    ws = Workspace(world)
    with ws.open_causal() as c, ws.open_authorial() as a:
        secrets = list(a.iter_strings())
        builder = ContextBuilder(c, audit=False)
        auditor = LeakAuditor(c, extra_secret_strings=secrets)
        results = {
            "character": auditor.find_leaks(builder.character_context(character_id), Principal.character(character_id)),
            "narrator": auditor.find_leaks(builder.narrator_context(character_id), Principal.narrator(character_id)),
        }
        forbidden = len(auditor.forbidden_tokens(Principal.character(character_id)))
        _echo_json({k: [leak.model_dump() for leak in v] for k, v in results.items()} | {"forbidden_token_count": forbidden})
        if any(results.values()):
            raise typer.Exit(code=1)


@app.command()
def snapshot(world: WorldArg, label: str) -> None:
    """현재 상태에 스냅샷을 찍는다."""
    with Workspace(world).open_causal() as c:
        _echo_json(c.snapshot(label).model_dump())


@app.command()
def snapshots(world: WorldArg) -> None:
    """스냅샷 목록."""
    with Workspace(world).open_causal() as c:
        _echo_json([s.model_dump() for s in c.snapshots()])


@app.command()
def diff(world: WorldArg, from_snapshot: str, to_snapshot: Annotated[str | None, typer.Argument()] = None) -> None:
    """스냅샷 간(또는 스냅샷→현재) 상태 차이."""
    from cte.causal.diff import diff_states

    with Workspace(world).open_causal() as c:
        before = c.snapshot_state(from_snapshot)
        after = c.snapshot_state(to_snapshot) if to_snapshot else c.materialize()
        result = diff_states(before, after)
        _echo_json({"summary": result.summary(), "changes": [ch.model_dump() for ch in result.changes]})


@app.command()
def rollback(world: WorldArg, snapshot_ref: str, reason: str = "manual rollback") -> None:
    """스냅샷 시점으로 되돌린다(이력은 보상 commit으로 남는다)."""
    with Workspace(world).open_causal() as c:
        _echo_json(c.rollback_to(snapshot_ref, reason=reason).model_dump())


@app.command()
def ledger(world: WorldArg, since: int = 0, entity: Annotated[str | None, typer.Option(help="NodeRef 필터(kind:id)")] = None) -> None:
    """원장 항목을 출력한다."""
    with Workspace(world).open_causal() as c:
        for e in c.ledger_entries(since_seq=since, entity_ref=entity):
            typer.echo(f"#{e.seq:>4} t={e.tick:<3} {e.op:<6} {e.entity_kind.value}:{e.entity_id}  (commit {e.commit_id})")


@app.command()
def trace(world: WorldArg, node: str, forward: bool = False, depth: int = 12) -> None:
    """provenance 추적: 기본은 원인 방향(왜?), --forward는 결과 방향."""
    with Workspace(world).open_causal() as c:
        g = ProvenanceGraph(c)
        typer.echo((g.consequences(node, depth) if forward else g.why(node, depth)).render())


@app.command()
def assess(world: WorldArg) -> None:
    """모든 활성 믿음의 진실성을 판정한다(시뮬레이터 전용 정보)."""
    with Workspace(world).open_causal() as c:
        _echo_json([a.model_dump(mode="json") for a in assess_all(c)])


if __name__ == "__main__":  # pragma: no cover
    app()


def _stepper_factory(
    scene: str, softmax: float | None, recorder_for: Callable[[CausalLedgerStore], ModuleRunRecorder]
) -> Callable[[CausalLedgerStore, object], SceneStepper]:
    def make(store: CausalLedgerStore, seed: object) -> SceneStepper:
        selector = SoftmaxSelector(softmax) if softmax else None
        return SceneStepper(store, scene_id=scene, seed=seed, selector=selector, recorder=recorder_for(store))

    return make


def _summarize(result: StepResult) -> dict[str, object]:
    return {
        "tick": result.tick,
        "events": [f"[{e.outcome.value}] {e.objective_description}" for e in result.outcome.events],
        "residues": len(result.residue_ids),
        "beliefs": len(result.belief_ids),
        "rejected": result.rejected,
    }


@app.command()
def step(
    world: WorldArg,
    scene: Annotated[str, typer.Option(help="장면 id")] = "scene_1",
    n: Annotated[int, typer.Option("-n", help="진행할 tick 수")] = 1,
    seed: Annotated[str, typer.Option(help="branch seed")] = "0",
    softmax: Annotated[float | None, typer.Option(help="후보 선택 softmax 온도(없으면 가장 긴급한 후보)")] = None,
) -> None:
    """장면을 n tick 진행한다(모든 모듈 입출력은 module_runs/JSONL에 기록)."""
    ws = Workspace(world)
    with ws.open_causal() as c:
        stepper = _stepper_factory(scene, softmax, ws.causal_recorder)(c, seed)
        _echo_json([_summarize(r) for r in stepper.run(n)])


@app.command()
def branches(
    world: WorldArg,
    seeds: Annotated[str, typer.Option(help="쉼표로 구분한 seed 목록")] = "0,1,2",
    n: Annotated[int, typer.Option("-n", help="branch당 tick 수")] = 3,
    scene: Annotated[str, typer.Option(help="장면 id")] = "scene_1",
    softmax: Annotated[float | None, typer.Option(help="후보 선택 softmax 온도")] = 0.3,
) -> None:
    """현재 상태에서 seed별 branch를 만든다(world/branches/<run>/branch_<seed>.db). 원본 원장은 바뀌지 않는다."""
    ws = Workspace(world)
    out_dir = ws.root / "branches" / new_id("run")
    with ws.open_causal() as c:
        runs = run_branches(
            c,
            seeds=[s.strip() for s in seeds.split(",") if s.strip()],
            steps=n,
            directory=out_dir,
            make_stepper=_stepper_factory(scene, softmax, lambda store: ModuleRunRecorder(store)),
        )
        _echo_json([{"seed": r.seed, "path": r.path, "state_hash": r.state_hash, "steps": [_summarize(s) for s in r.steps]} for r in runs])
