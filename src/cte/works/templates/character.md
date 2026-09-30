---
id: $id
name: "$name"
aliases: []                 # 원고에서 이 인물을 부르는 다른 이름(예: [현우, 선배]) — 등장 인식에 쓰인다
role: support               # protagonist | main | support | antagonist | extra
status: active              # active | absent | dead | retired
introduced_in: null         # 첫 등장/언급 회차
age: ""
occupation: ""
appearance: []              # 원고에 나온 외형만
core: []                    # 불변 핵심(가치·욕망·두려움) — 바꾸려면 state.md arc_changes에 사유 필수
never: []                   # 절대 하지 않는 행동
voice:
  first_person: ""          # 나 / 저 / ...
  default_register: ""      # 반말 / 존댓말 / ...
  address: {}               # 인물id: "호칭, 말씨"  예) yuri: "유리야, 반말"
  catchphrases: []
  forbidden: []             # 이 인물이 절대 안 쓰는 말(lint가 대사에서 찾는다)
  profanity: 0              # 0 없음 ~ 3 거침
  sample_lines: []          # 원고에서 인용한 기준 대사
relationships: []           # - {to: 인물id, label: "관계", note: ""}
tags: []
---

# $name

## 요약

## 성격과 행동 방식

## 과거 [비공개]

## 속마음 [본인만]

## 둘만 아는 이야기 [공유: 인물id]
<!-- 제목 끝 [공유: a, b] → 이 인물과 a, b만 검색된다. 쓰지 않으면 이 섹션을 지운다. -->

## 변화 기록
<!-- 회차별 변화는 episodes/NNNN/state.md 의 arc_changes 에 기록하고, 여기에는 굵직한 흐름만 요약한다. -->
