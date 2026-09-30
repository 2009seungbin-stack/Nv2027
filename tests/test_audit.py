"""Metallic Auditor: 기준 원고 프로필 고정, 대조 샘플 신호, 주석 무결성, 장면 구조 진단."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cte.access import CharacterContext
from cte.audit import audit_scene, compare, parse_chapter, profile
from cte.audit.prose import ParagraphKind
from cte.cli import app
from cte.phase2.interfaces import ActionCandidate, ActionKind
from cte.sim import SceneStepper
from cte.tracing import ModuleRunRecorder

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "corpus" / "reference" / "massage_001.txt"
CONTRAST = ROOT / "corpus" / "contrast" / "massage_001_llm_default.txt"
ANNOTATIONS = ROOT / "corpus" / "reference" / "massage_001.annotations.json"


@pytest.fixture(scope="module")
def ref():
    return profile(REFERENCE.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 기준 원고


def test_reference_structure_is_pinned(ref):
    ch = parse_chapter(REFERENCE.read_text(encoding="utf-8"))
    assert ch.title == "마사지 해드립니다 001. 스팸 문자인 줄 알았는데, 주식이 박살났다"
    assert (ref.paragraphs, ref.narration, ref.dialogue, ref.inner, ref.system, ref.scene_breaks) == (96, 61, 33, 2, 15, 1)
    assert ref.one_sentence_narration_ratio == pytest.approx(0.918, abs=0.001)
    assert ref.ellipsis == 23 and ref.unfinished_narration == 4
    assert ref.similes == ["마치", "난 듯", "백옥같이", "않은 듯"]
    assert ref.emotion_labels == ["분노가 치밀"]  # 사람 원고에도 한 번 있다
    assert ref.summary_closers == ref.explained_jokes == ref.abstract_stakes == []
    assert len(ref.profanity) == 8 and "선배선배선배" in ref.orthographic_play
    assert ref.repeated_phrases["신경이 쓰였다"] == 2
    assert any(p.kind is ParagraphKind.SYSTEM and "최소 금액" in p.text for p in ch.paragraphs)


def test_reference_against_itself_has_no_signal(ref):
    assert compare(ref, ref) == []


def test_contrast_sample_triggers_metallic_signals(ref):
    signals = {s.code: s for s in compare(profile(CONTRAST.read_text(encoding="utf-8")), ref)}
    assert set(signals) == {
        "dense_paragraphs",
        "emotion_labeling",
        "simile_density",
        "summary_closer",
        "explained_joke",
        "abstract_stakes",
        "no_concrete_numbers",
        "all_sentences_closed",
        "repetition_avoided",
    }
    # 문장 층 증상이라도 원인은 시뮬레이션 층일 수 있다(원칙 14)
    assert signals["abstract_stakes"].layer == "state" and signals["summary_closer"].layer == "collision"
    assert "그때까지만 해도 나는 몰랐다" in signals["summary_closer"].evidence
    assert "가슴 한켠" in signals["emotion_labeling"].evidence


def test_annotations_quote_the_reference_verbatim():
    text = REFERENCE.read_text(encoding="utf-8")
    doc = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))
    anns = doc["annotations"]
    assert len({a["id"] for a in anns}) == len(anns)
    assert [a["id"] for a in anns if a["quote"] not in text] == []
    assert {a["category"] for a in anns} == {"design", "character", "prose", "noise"}
    assert all(a["learn"] is (a["category"] != "noise") for a in anns)  # 노이즈는 배우지 않는다


# ------------------------------------------------------------------ 장면 구조


class Scripted:
    def __init__(self, drafts):
        self.drafts = drafts

    def propose(self, context: CharacterContext):
        return [
            ActionCandidate(candidate_id=f"{context.character_id}_{context.tick}_{i}", actor_id=context.character_id, **d) for i, d in enumerate(self.drafts)
        ]


CHAT = dict(action_kind=ActionKind.SPEAK, intent="잡담한다", approach="지영에게 말을 건다", speech="날씨 좋네", target_ids=["b"], urgency=0.5)
NOD = dict(action_kind=ActionKind.OTHER, intent="맞장구친다", approach="고개를 끄덕인다", urgency=0.5)


def test_flat_scene_is_diagnosed(mini):
    stepper = SceneStepper(mini, scene_id="flat", actors=["a", "b"], proposers={"a": Scripted([CHAT]), "b": Scripted([NOD])}, recorder=ModuleRunRecorder(mini))
    stepper.run(4)
    head = mini.head_seq()
    report = audit_scene(mini, "flat")
    assert mini.head_seq() == head  # 읽기 전용
    codes = {i.code: i for i in report.issues}
    assert {"no_world_interruption", "no_failure", "no_wavering", "no_misbelief", "no_alternatives", "monotone_actor"} <= set(codes)
    assert codes["no_world_interruption"].layer == "world" and codes["no_failure"].layer == "pressure"
    assert codes["no_alternatives"].layer == "decision" and set(codes["monotone_actor"].evidence) == {"a", "b"}
    assert report.single_option_choices == 8 and report.choice_points == 0


def test_demo_scene_has_the_textures_the_flat_one_lacks(demo):
    causal, _ = demo
    SceneStepper(causal, scene_id="scene_1", seed=1, recorder=ModuleRunRecorder(causal)).run(5)
    report = audit_scene(causal, "scene_1")
    codes = {i.code for i in report.issues}
    assert report.world_events >= 1 and report.failed_or_interrupted >= 1 and report.wavering >= 1 and report.active_misbeliefs >= 1
    assert not {"no_world_interruption", "no_failure", "no_wavering", "no_misbelief", "no_alternatives"} & codes
    assert "monotone_actor" in codes  # 규칙 기반 제안기의 알려진 한계를 Auditor가 잡는다


def test_cli_audit_commands(tmp_path):
    runner = CliRunner()
    out = runner.invoke(app, ["prose-profile", str(CONTRAST), "--reference", str(REFERENCE)])
    assert out.exit_code == 0, out.output
    assert "summary_closer" in {s["code"] for s in json.loads(out.output)["signals"]}
    w = tmp_path / "w"
    for args in (["init", str(w)], ["seed-demo", str(w)], ["step", str(w), "-n", "3"]):
        assert runner.invoke(app, args).exit_code == 0
    rep = json.loads(runner.invoke(app, ["structure-audit", str(w), "--scene", "scene_1"]).output)
    assert rep["scene_id"] == "scene_1" and rep["actors"] == ["junho", "seoyeon"]
