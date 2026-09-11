"""전역 질문(Q&A 내비게이션) 준비 모듈 — 스키마·프롬프트의 드리프트 가드.

여기서 지키는 것:
  ① 액션 view enum이 **실제 탭 목록과 같다** — 해시 정본은 index.html nav ↔
     main.js VIEWS(웹 blocks.test.js가 서로 대조)이고, 이 스키마는 그 세 번째
     사본이다. 사본을 들이는 대가로 원문 대조 가드를 단다(웹과 같은 방식의
     파이썬판 — 문서만 고치고 여기를 놔두면 LLM이 죽은 탭으로 안내한다).
  ② 프롬프트가 전 탭을 말한다 — 지도에 빠진 탭은 LLM이 안내할 수 없다.
  ③ 사용자 메시지에 질문·산출물 메타가 실제로 실린다.
"""

import re
from pathlib import Path

from claw_server.ask import ASK_SCHEMA, ASK_SYSTEM, ask_user

_REPO = Path(__file__).resolve().parents[3]


def _view_enum():
    return ASK_SCHEMA["properties"]["actions"]["items"]["properties"]["view"]["enum"]


def test_액션_view_enum은_실제_탭_목록과_순서까지_같다():
    nav = re.findall(r'data-view="([\w-]+)"',
                     (_REPO / "web" / "index.html").read_text(encoding="utf-8"))
    assert nav, "index.html nav를 읽지 못했다 — 가드 자체가 죽으면 안 된다"
    assert _view_enum() == nav


def test_프롬프트_지도가_전_탭을_말한다():
    for view in _view_enum():
        assert f"#{view}" in ASK_SYSTEM, f"프롬프트 지도에 #{view}가 없다"


def test_사용자_메시지에_질문과_산출물_메타가_실린다():
    u = ask_user("실속 마진은 어디서 봐?",
                 [{"id": "abc", "kind": "margin_map", "created": 1.0}])
    assert "실속 마진은 어디서 봐?" in u
    assert "margin_map" in u
