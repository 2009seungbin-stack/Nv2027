"""문장 층 표면 지표(ProseProfile)와 기준 원고 대비 신호.

원칙 13: Auditor는 문장을 고치지 않는다. 측정하고, 어긋난 지표마다 *어느 층으로 돌아가야 하는지*
(layer)와 원인(cause)을 돌려줄 뿐이다. 문장 층 지표라도 원인이 시뮬레이션 층에 있으면 그 층을 가리킨다
(예: 구체 수치가 없다 → narrator가 아니라 인물 상태에 구체적 판돈이 없다).

정규식 지표는 근사치다. 신호는 '확정 판정'이 아니라 사람이 확인할 단서이며, 모든 신호는 근거(evidence)로
실제 일치한 문자열을 함께 싣는다.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ParagraphKind(StrEnum):
    """원고 문단 종류."""

    NARRATION = "narration"
    DIALOGUE = "dialogue"
    INNER = "inner"
    SYSTEM = "system"
    SCENE_BREAK = "scene_break"


class Paragraph(BaseModel):
    """문단 하나."""

    kind: ParagraphKind
    text: str


class ParsedChapter(BaseModel):
    """파싱된 회차(corpus/README.md의 표기 규약)."""

    title: str | None = None
    paragraphs: list[Paragraph]

    def of(self, *kinds: ParagraphKind) -> list[Paragraph]:
        return [p for p in self.paragraphs if p.kind in kinds]


def parse_chapter(text: str) -> ParsedChapter:
    """빈 줄로 문단을 나누고 종류를 붙인다. ``=====`` 사이는 시스템 창, ``> `` 줄은 UI 박스."""
    title: str | None = None
    paragraphs: list[Paragraph] = []
    in_system = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# ") and title is None and not paragraphs:
            title = line[2:].strip()
            continue
        if set(line) == {"="}:
            in_system = not in_system
            continue
        if in_system or line.startswith(">"):
            paragraphs.append(Paragraph(kind=ParagraphKind.SYSTEM, text=line.lstrip("> ").strip()))
        elif set(line) == {"-"}:
            paragraphs.append(Paragraph(kind=ParagraphKind.SCENE_BREAK, text=line))
        elif line[0] in '"“':
            paragraphs.append(Paragraph(kind=ParagraphKind.DIALOGUE, text=line))
        elif line[0] in "'‘":
            paragraphs.append(Paragraph(kind=ParagraphKind.INNER, text=line))
        else:
            paragraphs.append(Paragraph(kind=ParagraphKind.NARRATION, text=line))
    return ParsedChapter(title=title, paragraphs=paragraphs)


_SENTENCE_SPLIT = re.compile(r"(?<=[.?!…])\s+")
_SIMILE = re.compile(r"마치\s|\S+(?:처럼|같이)(?=[\s,.]|$)|\S+\s듯(?:이)?(?=\s)")
_NUMBER = re.compile(r"\d[\d,.]*\s?(?:%|cm|kg|원|만원|살|자리|초|분|시간|개|명|층)?")
_EMOTION_LABEL = re.compile(
    r"(?:불안|안도|초조|설렘|두려움|분노|슬픔|기쁨|긴장|위화)(?:감|함)?(?:이|을|가)\s?(?:밀려|스치|스쳤|차오르|피어오르|피어올|감돌|치밀|솟구)"
    r"|가슴\s?한켠|마음\s?한구석|묘한\s(?:기분|감정|느낌)"
)
_SUMMARY_CLOSER = re.compile(r"그때까지만 해도 [^.]*몰랐다|그렇게 [^.]*(?:일상|이야기|하루)[^.]*(?:끝|시작)|송두리째|모든 것이 (?:바뀌|달라)")
_EXPLAINED_JOKE = re.compile(r"(?:농담|개그|장난)에\s?(?:나도 모르게\s)?(?:웃음|피식)")
_ABSTRACT_STAKES = re.compile(r"모든 것을 잃|인생을 송두리째|돌이킬 수 없는")
_PROFANITY = ("새끼", "개같", "뒤질", "죽이고 싶", "개열받", "망할", "젠장", "씨발", "아나", "선 넘")
_ORTHO_PLAY = re.compile(r"(\S{1,2})\1{2,}|[~]{1}")


class ProseProfile(BaseModel):
    """회차 하나의 표면 지표."""

    paragraphs: int = Field(description="문단 수(시스템·장면 구분 제외).")
    narration: int
    dialogue: int
    inner: int
    system: int
    scene_breaks: int
    one_sentence_narration_ratio: float = Field(description="서술 문단 중 한 문장짜리 비율(모바일 웹소설 박자).")
    paragraph_len_mean: float
    paragraph_len_median: float
    paragraph_len_stdev: float
    paragraph_len_cv: float = Field(description="문단 길이 변동계수(stdev/mean). 낮을수록 문단이 균질하다.")
    dialogue_ratio: float = Field(description="대사 문단 비율.")
    ellipsis: int = Field(description="말줄임(… 또는 ...) 수.")
    unfinished_narration: int = Field(description="…로 끝나 문장을 닫지 않은 서술 문단 수.")
    chars: int = Field(description="본문 글자 수(시스템 제외).")
    similes: list[str] = Field(description="직유/양태 비유 표지.")
    numbers: list[str] = Field(description="구체 수치.")
    emotion_labels: list[str] = Field(description="감정 명명 표현.")
    summary_closers: list[str] = Field(description="요약·예고형 마무리('그때까지만 해도 나는 몰랐다').")
    explained_jokes: list[str] = Field(description="개그 뒤의 해설('농담에 나도 모르게 웃음이').")
    abstract_stakes: list[str] = Field(description="추상적 판돈('모든 것을 잃').")
    profanity: list[str] = Field(description="거친 말.")
    orthographic_play: list[str] = Field(description="표기 놀이(반복 음절, 물결).")
    repeated_phrases: dict[str, int] = Field(description="서술에서 2회 이상 반복된 어절 2-gram(의도적 반복의 흔적).")

    def per_1k(self, count: int) -> float:
        return round(1000 * count / self.chars, 3) if self.chars else 0.0


def profile(text: str) -> ProseProfile:
    """원고 텍스트의 표면 지표를 잰다."""
    ch = parse_chapter(text)
    body = ch.of(ParagraphKind.NARRATION, ParagraphKind.DIALOGUE, ParagraphKind.INNER)
    narration = ch.of(ParagraphKind.NARRATION)
    joined = "\n".join(p.text for p in body)
    lens = [len(p.text) for p in body] or [0]
    mean = statistics.mean(lens)
    one = sum(1 for p in narration if len([s for s in _SENTENCE_SPLIT.split(p.text) if s]) == 1)
    words = [w.strip(".,?!…\"'") for p in narration for w in p.text.split()]
    bigrams = Counter(f"{a} {b}" for a, b in zip(words, words[1:], strict=False) if a and b)
    return ProseProfile(
        paragraphs=len(body),
        narration=len(narration),
        dialogue=len(ch.of(ParagraphKind.DIALOGUE)),
        inner=len(ch.of(ParagraphKind.INNER)),
        system=len(ch.of(ParagraphKind.SYSTEM)),
        scene_breaks=len(ch.of(ParagraphKind.SCENE_BREAK)),
        one_sentence_narration_ratio=round(one / len(narration), 3) if narration else 0.0,
        paragraph_len_mean=round(mean, 1),
        paragraph_len_median=float(statistics.median(lens)),
        paragraph_len_stdev=round(statistics.pstdev(lens), 1),
        paragraph_len_cv=round(statistics.pstdev(lens) / mean, 3) if mean else 0.0,
        dialogue_ratio=round(len(ch.of(ParagraphKind.DIALOGUE)) / len(body), 3) if body else 0.0,
        ellipsis=joined.count("…") + joined.count("..."),
        unfinished_narration=sum(1 for p in narration if p.text.endswith(("…", "..."))),
        chars=len(joined),
        similes=[m.group(0).strip() for m in _SIMILE.finditer(joined)],
        numbers=[m.group(0).strip() for m in _NUMBER.finditer(joined)],
        emotion_labels=[m.group(0) for m in _EMOTION_LABEL.finditer(joined)],
        summary_closers=[m.group(0) for m in _SUMMARY_CLOSER.finditer(joined)],
        explained_jokes=[m.group(0) for m in _EXPLAINED_JOKE.finditer(joined)],
        abstract_stakes=[m.group(0) for m in _ABSTRACT_STAKES.finditer(joined)],
        profanity=[w for w in _PROFANITY if w in joined],
        orthographic_play=[m.group(0) for m in _ORTHO_PLAY.finditer(joined)],
        repeated_phrases={k: v for k, v in bigrams.most_common() if v >= 2},
    )


Layer = Literal["pressure", "decision", "collision", "world", "state", "residue", "narrator"]


class ProseSignal(BaseModel):
    """기준 원고 대비 어긋난 지표 하나. 고칠 층과 원인을 가리킨다."""

    code: str = Field(description="신호 코드.")
    layer: Layer = Field(description="되돌아갈 층(원칙 14).")
    cause: str = Field(description="원인 가설.")
    sample: float = Field(description="검사 대상 값.")
    reference: float = Field(description="기준 원고 값.")
    evidence: list[str] = Field(default_factory=list, description="실제 일치 문자열.")


def compare(sample: ProseProfile, reference: ProseProfile) -> list[ProseSignal]:
    """기준 원고 대비 신호. 기준과 같은 텍스트면 신호가 없어야 한다."""
    out: list[ProseSignal] = []

    def add(code: str, layer: Layer, cause: str, s: float, r: float, evidence: list[str] | None = None) -> None:
        out.append(ProseSignal(code=code, layer=layer, cause=cause, sample=s, reference=r, evidence=evidence or []))

    if sample.one_sentence_narration_ratio < reference.one_sentence_narration_ratio * 0.6:
        add(
            "dense_paragraphs",
            "narrator",
            "서술이 여러 문장씩 묶여 박자가 사라졌다",
            sample.one_sentence_narration_ratio,
            reference.one_sentence_narration_ratio,
        )
    if sample.paragraph_len_cv < reference.paragraph_len_cv * 0.6:
        add("uniform_paragraphs", "narrator", "문단 길이가 균질하다(강약 없음)", sample.paragraph_len_cv, reference.paragraph_len_cv)
    s_emo, r_emo = sample.per_1k(len(sample.emotion_labels)), reference.per_1k(len(reference.emotion_labels))
    if len(sample.emotion_labels) >= 2 and s_emo > r_emo * 2:
        add(
            "emotion_labeling",
            "narrator",
            "행동·관찰 대신 감정 상태를 이름으로 읽어준다(렌더링 입력이 상태 값뿐일 때 생김)",
            s_emo,
            r_emo,
            sample.emotion_labels,
        )
    s_sim, r_sim = sample.per_1k(len(sample.similes)), reference.per_1k(len(reference.similes))
    if len(sample.similes) >= 3 and s_sim > r_sim * 2:
        add("simile_density", "narrator", "비유가 사실 진술을 대신한다", s_sim, r_sim, sample.similes)
    if sample.summary_closers and not reference.summary_closers:
        add(
            "summary_closer",
            "collision",
            "장면이 끊기지 않고 요약·예고로 닫힌다(미해결 스레드·중단 부재)",
            len(sample.summary_closers),
            0,
            sample.summary_closers,
        )
    if sample.explained_jokes and not reference.explained_jokes:
        add("explained_joke", "narrator", "개그 뒤에 반응을 해설한다(반응은 행동/대사로)", len(sample.explained_jokes), 0, sample.explained_jokes)
    if sample.abstract_stakes and not reference.abstract_stakes:
        add("abstract_stakes", "state", "욕망·두려움에 구체적 대상과 수치가 없다", len(sample.abstract_stakes), 0, sample.abstract_stakes)
    if not sample.numbers and reference.numbers:
        add("no_concrete_numbers", "state", "인물 상태·세계에 구체 수치가 없다", 0, len(reference.numbers))
    if sample.unfinished_narration == 0 and reference.unfinished_narration > 0:
        add("all_sentences_closed", "narrator", "생각이 끊기는 자리가 없다(중단·잔여물이 문장에 반영되지 않음)", 0, reference.unfinished_narration)
    if not sample.repeated_phrases and reference.repeated_phrases:
        add("repetition_avoided", "narrator", "의도적 반복이 없다(동의어 돌려막기)", 0, len(reference.repeated_phrases))
    return out
