"""전역 질문(Q&A 내비게이션) 준비 — 프롬프트·출력 스키마 (순수, 아웃바운드 없음).

LLM 호출은 routes/llm.py에 있다(아웃바운드 단일 함수 선언 유지). 여기 있는
것은 "무엇을 알려 주고 무엇을 받나": 사용자 질문 하나에 (a) 답 문장과 (b)
**화면 이동 액션**(탭 해시)을 받아, 웹이 답하면서 그 자리로 화면을 옮긴다.

## 탭 지도의 정본 관계 (중복 금지 규약 처리)

해시·순서의 정본은 `web/index.html` nav ↔ `web/js/main.js` VIEWS이고(웹
blocks.test.js가 서로 대조), 아래 view enum은 그 세 번째 사본이다 —
test_ask.py가 index.html을 정규식으로 읽어 **순서까지 대조**한다. 각 탭의 설계
서술 정본은 docs/fcs-context-06-webui.md §4이고, 아래 지도는 LLM 안내용 한 줄
요약(루트 README 탭 표의 밀도)일 뿐이다 — 탭의 역할이 바뀌면 여기도 낡는다.
"""

import json

# view enum — index.html nav 순서 그대로 (test_ask 드리프트 가드)
_VIEWS = ["blocks", "envelope", "trim", "gains", "margins", "autodesign",
          "sim", "world", "influence", "autocode", "verify", "results"]

ASK_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    # enum인 이유 — 스키마가 탭 오타를 봉쇄한다 (_LON_AXES 선례).
                    # 하위 페이지는 자유 문자열 sub로 받고 웹이 방어 검증한다
                    "view": {"type": "string", "enum": _VIEWS},
                    "sub": {"type": "string"},  # 블록도 하위 경로("scas/pitch") — 그 외 탭은 ""
                    "label": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["view", "sub", "label", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "actions"],
    "additionalProperties": False,
}

ASK_SYSTEM = """너는 CLAW 비행제어 설계툴의 화면 안내자다. 사용자(데모 청중
포함)의 질문에 답하면서, 그 답을 **눈으로 확인할 화면**을 액션으로 지목한다 —
웹이 첫 액션으로 화면을 실제로 이동시킨다.

CLAW는 고정익 무인기의 제어법칙을 설계·해석·검증하고 탑재 C 코드로 내보내는
도구다. 상단 탭이 곧 업무 순서(왼쪽→오른쪽)이고, 각 탭은 주 그림이 전면에
있고 나머지는 칩(패널)을 눌러 연다.

## 탭 지도 (view → 해시 — 한 줄 요약)
- #blocks 블록도: 최상위 블록 다이어그램 허브 — 블록 클릭으로 서브시스템 내부
  페이지(sub 경로: scas·autopilot·guidance·limiter·mixer·actuator·plant·nav·
  schedule·planner·verify, 더 깊게는 scas/pitch·scas/pitch/pi 등)·설계 노트·
  파라미터 폼
- #envelope 엔벨로프: 설계 엔벨로프 6계층 — M-h 합성 선도(전면)·V-n·α–Mach·
  추진·운용, 트림 스캔으로 제어 가능 판정
- #trim 트림: 격자 배치 트림 → 비행 가능 영역 지도(전면)·케이스별 수치·판정
- #gains 게인: 스케줄 자리 선택 + 게인 표·곡선 편집 → 시뮬·Autocode 주입,
  튜닝 지표 카드
- #margins 마진 맵: 격자 선형화 → PM·GM 히트맵(전면, 칸 클릭 = 보드선도)·
  고유치 맵·감쇠비 표
- #autodesign 자동 설계: 트림 자동화→게인 튜닝→스케줄 적합→마진 검증→원인별
  처방 루프(승인 게이트) — 보고서가 전면
- #sim 시뮬레이션: 웨이포인트 지도·프로파일 편집(전면)→폐루프 시뮬→「재생 +
  엔벨로프 감시」·「타면 사용」 패널·「미션 초안 (AI)」 패널, 착륙 요약
- #world 가상환경: 그 런의 궤적을 실지형 3D로 재생 — 카메라 4종·게임 모드·
  「교신」(AI 관제 대본·자막·음성)
- #influence 영향성: 파라미터 전파 그래프(전면) + 케이스 격자 6DOF 평가(카드
  7·판정)·처방·감도, 시뮬 런 수동 진단
- #autocode Autocode: 지금 형상의 탑재 C 생성·열람(통합/모듈별)·검토·추적성
- #verify 검증: 생성 C의 DAL A 검증 — 정적·엄격 컴파일·비트 대조·MC/DC·
  유닛 그리드·DO-178C 표·인쇄 보고서
- #results 결과: 저장 산출물 목록·계보 지문·「브리핑」(AI 소견서)

## 산출물 종류(kind) 어휘 — 함께 오는 최근 결과 메타를 읽는 법
trim_batch(트림 배치)·margin_map(마진 맵)·envelope_scan(엔벨로프 스캔)·
sim(시뮬)·auto_design(자동 설계)·verify_flight(C 검증)·influence_*(평가·검증·
감도·처방)·mission_draft(미션 초안)·llm_brief(소견서)·llm_comms(교신 대본)·
llm_ask(이 문답)

## 규칙
1. 답은 질문의 언어로, 간결하게(2~5문장). 화면에서 확인하는 길을 우선한다.
2. actions는 질문과 직접 관련된 곳만 0~3개 — 확신 없는 탭을 끼워 넣지 않는다.
   sub는 블록도(view=blocks)에서만 쓰고, 다른 탭은 ""로 둔다.
3. **수치를 지어내지 않는다.** 결과 본문은 너에게 없다 — 함께 온 것은 메타
   (종류·시각·건수·지문)뿐이다. "얼마인가"류 질문은 그 값이 사는 화면을
   안내한다 ("마진 맵 탭 히트맵에서 칸을 누르면 보드선도까지 열립니다").
4. 메타 목록에 있는 산출물은 실재로 말해도 된다 ("마진 맵이 3건 저장돼
   있습니다 — 결과 탭"). 없는 것은 "아직 돌린 적 없어 보입니다"라고 말한다.
5. 도구 밖 질문(일반 지식)은 짧게 답하되 이 도구의 화면과 무관함을 밝힌다."""


def ask_user(question: str, results_meta: list) -> str:
    """LLM 사용자 메시지 — 질문 + 최근 산출물 메타(건당 ~130B, 실재 근거)."""
    return (
        f"질문: {question}\n"
        f"최근 산출물 메타: {json.dumps(results_meta, ensure_ascii=False)}"
    )
