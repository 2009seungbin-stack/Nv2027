---
episode: 1
in_world_time: "23살 초여름, 강의 후 ~ 알바 출근 두 시간 뒤"
summary: >-
  복학생 장현우가 강의 후 귀갓길에 이상한 번호로 '마사지사로의 첫걸음' 튜토리얼 퀘스트 문자를 받는다(12시간 안에
  손 마사지로 1,000원 이상, 실패 시 엔씨디아 주가 하락). 친구의 장난이라 결론 내리고 알바에 가지만, 안마 이야기를
  아는 사람이 하민뿐이라는 점이 계속 걸린다. 생각은 후배 배유리의 아재개그에 끊기고, 유리는 우유 스팀 시범을 부탁한다.
events:
  - id: ev_0001_01
    summary: "귀갓길에 이상한 번호로 튜토리얼 퀘스트 문자를 받는다"
    participants: [hyunwoo]
    caused_by: []
    consequences: ["친구의 장난으로 결론 내리고 무시", "범인 후보로 하민·석호·진혁을 떠올림", "12시간 퀘스트 시한이 흐르기 시작"]
  - id: ev_0001_02
    summary: "알바 두 시간째에도 문자가 신경 쓰인다 — '마사지'를 아는 친구는 하민뿐"
    participants: [hyunwoo]
    place: cafe
    caused_by: [ev_0001_01]
    consequences: ["하민을 의심할 수도 믿을 수도 없는 찜찜함"]
  - id: ev_0001_03
    summary: "유리가 아재개그(세종대왕이 만든 우유)로 현우의 생각을 끊는다"
    participants: [yuri, hyunwoo]
    place: cafe
    caused_by: []
    consequences: ["범인 추리가 결론 없이 중단"]
  - id: ev_0001_04
    summary: "유리가 망한 카푸치노를 버리고 우유 스팀 시범을 부탁한다"
    participants: [yuri, hyunwoo]
    place: cafe
    caused_by: [ev_0001_03]
    consequences: ["현우의 손재주가 드러날 자리 — 손 마사지 퀘스트와 연결될 수 있음(인물은 모름)"]
characters:
  hyunwoo:
    location: cafe
    condition: ""
    emotion: "문자에 대한 찜찜함, 유리에게 설렘"
    goal: "유리에게 우유 스팀 시범을 보인다"
    knows_new: ["튜토리얼 퀘스트 내용(손 마사지로 12시간 안에 1,000원 이상, 미달성 시 엔씨디아 주가 하락)", "안마 이야기를 아는 친구는 하민뿐"]
    believes_wrongly: ["퀘스트 문자는 친구의 장난이다"]
  yuri:
    location: cafe
    emotion: "장난기"
    goal: "카푸치노 스팀을 제대로 배운다"
relationships: []
threads_opened:
  - {id: th_prank_culprit, summary: "퀘스트 문자는 누가 보냈나(현우는 친구의 장난이라 믿음)"}
  - {id: th_quest_deadline, summary: "12시간 안에 손 마사지로 1,000원 이상 벌 수 있나"}
threads_closed: []
foreshadowing:
  - {id: fs_sender_identity, action: planted, quote: "0부터 시작해서 15자리가 넘어가는 알 수 없는 번호."}
  - {id: fs_massage_story, action: planted, quote: "\"이 안마 썰은 하민이 말고는 말해준 적이 없는데 말이지.\""}
  - {id: fs_stock_penalty, action: planted, quote: "엔씨디아 주가 하락"}
  - {id: fs_apprentice_eye, action: planted, quote: "! ) 퀘스트가 진행되는 동안 사용자에게 [ 견습 마사지사의 눈 ] 이 적용됩니다."}
  - {id: fs_hand_skill, action: planted, quote: "내가 또 손재주가 좋은 편이라 이런 걸 잘 한다."}
new_settings: [massage_quest, ncdia_stock, apprentice_eye, master_eye, massage_app, cafe, hyunwoo_room]
arc_changes: []
---

# 1화 종료 상태

## 작가 메모

(1화 원고 기반으로 정리한 초기 기록. 발신자 정체·복선 회수 계획은 작가 기입 필요)
