"""LLM 라우트 — 미션 초안·결과 브리핑·교신 대본·화면 질문, 202 잡.

**이 라우터는 이 리포의 유일한 런타임 아웃바운드다.** routes/world.py가 세운
"서버는 바깥으로 나가지 않는다"는 그대로 자산 계약으로 유지되고, 예외는 여기
`call_llm` 하나뿐이다 — LLM 기능이 늘어도 아웃바운드는 이 함수를 거친다.
목적지는 백엔드 선택(`_backend`)으로 정해진다: Anthropic Messages API
(`CLAW_ANTHROPIC_API_KEY`) 또는 사내 OpenAI 호환 서버(`CLAW_LLM_BASE_URL` +
`CLAW_LLM_MODEL`) — 폐쇄망은 후자로 켠다(docs/deploy-airgap.md).
`CLAW_LLM_BASE_URL`이 있으면 로컬로 **커밋**된다: Anthropic 키가 함께 있어도
폴백하지 않는다(폐쇄망 의도 구성이 조용히 밖으로 나가면 안 된다). 아무것도
설정하지 않으면 LLM 기능만 사유와 함께 꺼지고 서버는 그대로 선다 — 지형 팩
없는 배포와 같은 degrade(`/llm/status`가 그 사유를 문장으로 낸다). 브리핑의
가지치기·프롬프트는 claw_server/brief.py.

**초안은 웹 폼 행 형식이다** (`modeRows`/`wpRows` — 값 전부 문자열). 서버
ModeIn(alt/pitch/hdot 3필드)이 아니라 웹 표의 lonAxis+lonValue 형식인 이유:
종방향 축 배타 위반이 **표현 자체가 안 되는** 형식이라(웹 표가 그 형식인 이유와
같다 — lib/mission.js LON_AXES 머리말) LLM의 실수 면적이 가장 작고, 응답이
그대로 표에 앉아 사용자가 고칠 수 있다. 검증 정본은 그대로 웹
lib/mission.js(buildModes·buildWaypoints)와 실행 시점 /sim/run 422다 — 여기서는
JSON 형상만 스키마로 강제하고(structured output) 의미 검증을 재구현하지 않는다.

키를 표준 `ANTHROPIC_API_KEY`가 아니라 CLAW_ 접두로 받는 이유: 개발 셸에
우연히 있는 키로 기능이 조용히 켜지는 것을 막는 명시적 옵트인이다 — 로컬
백엔드 변수 셋(`CLAW_LLM_*`)도 같은 이유로 CLAW_ 접두다.
"""

import json
import os

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from claw_server.ask import ASK_SCHEMA, ASK_SYSTEM, ask_user
from claw_server.brief import BRIEF_SCHEMA, BRIEF_SYSTEM, brief_user, prune
from claw_server.comms import (
    COMMS_SCHEMA, COMMS_SYSTEM, comms_user, flight_log, validate_lines,
)

router = APIRouter(tags=["llm"])

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-opus-5"
_TIMEOUT_S = 180.0  # 비스트리밍 1회 호출 — 추론이 길어질 여지를 준다 (두 백엔드 공유)
_MAX_TOKENS = 16000


def _api_key() -> str:
    # 요청마다 읽는다 — 모듈 상수로 올리면 앱 재생성 없이 환경을 못 바꿔
    # 테스트가 불가능하다 (routes/system.py deployed_commit·world.py _root와 같은 자리)
    return os.environ.get("CLAW_ANTHROPIC_API_KEY", "").strip()


def _model() -> str:
    return os.environ.get("CLAW_ANTHROPIC_MODEL", "").strip() or _DEFAULT_MODEL


def _local_base_url() -> str:
    # 사내 OpenAI 호환 서버 — 값 예: http://10.0.0.5:8000/v1 (서버가
    # /chat/completions를 뒤에 붙인다). **존재 자체가 로컬 백엔드 커밋**이다.
    return os.environ.get("CLAW_LLM_BASE_URL", "").strip().rstrip("/")


def _local_model() -> str:
    # 로컬 모델 이름에는 지어낼 기본값이 없다 — 비면 불가용 사유가 지목한다
    return os.environ.get("CLAW_LLM_MODEL", "").strip()


def _local_key() -> str:
    # 게이트웨이용 Bearer — 대부분의 사내 서버는 요구하지 않아 선택이다
    return os.environ.get("CLAW_LLM_API_KEY", "").strip()


def _backend() -> str | None:
    """백엔드 선택 — 명시 스위치 없이 **설정 존재**로 정한다(CLAW_ 옵트인 철학).

    스위치를 따로 두면 "스위치=로컬인데 URL 없음" 같은 모순 상태가 생겨 사유
    문장이 하나 더 필요해진다 — 존재=선택이면 모순이 표현 자체가 안 된다.
    BASE_URL이 있으면 로컬로 **커밋**이다: 모델 이름이 빠졌어도 Anthropic으로
    폴백하지 않는다(그 불가용 판정은 _require_backend·status가 사유로 낸다 —
    조용한 폴백 금지는 trim._CONDITIONS와 같은 규율).
    """
    if _local_base_url():
        return "openai"
    if _api_key():
        return "anthropic"
    return None


_UNAVAILABLE = (
    "LLM 백엔드가 설정되지 않았습니다 — LLM 기능(미션 초안·결과 브리핑·교신 "
    "대본·화면 질문·가이드 투어)이 꺼져 있습니다. 인터넷 배포는 "
    "CLAW_ANTHROPIC_API_KEY를, 폐쇄망은 사내 OpenAI 호환 서버의 "
    "CLAW_LLM_BASE_URL과 CLAW_LLM_MODEL을 설정하고 재기동하면 켜집니다. "
    "설정하지 않으면 이 기능만 꺼진 채 서버는 정상 동작합니다."
)
_UNAVAILABLE_LOCAL_MODEL = (
    "CLAW_LLM_BASE_URL은 설정됐으나 CLAW_LLM_MODEL이 없습니다 — 로컬 백엔드가 "
    "지정된 상태라 Anthropic으로 폴백하지 않습니다(폐쇄망 의도 구성이 조용히 "
    "밖으로 나가지 않게). 모델 이름을 넣고 재기동하십시오."
)


def _require_backend() -> tuple[str, str]:
    """생성 라우트 공용 게이트 — (model, api_key)를 주거나 503 사유로 거부한다.

    백엔드 미설정은 202 뒤 잡 오류보다 제출 시점 거부가 낫다(verify.py의 즉시
    422와 같은 판단). 503인 이유: 요청이 아니라 서버 구성이 원인이다.
    """
    b = _backend()
    if b == "openai":
        model = _local_model()
        if not model:
            raise HTTPException(status_code=503, detail=_UNAVAILABLE_LOCAL_MODEL)
        return model, _local_key()
    if b == "anthropic":
        return _model(), _api_key()
    raise HTTPException(status_code=503, detail=_UNAVAILABLE)

# ── LLM 출력 스키마 — 웹 폼 행 계약 (정본은 이 파일, 웹 normalizeDraft는 방어적 수용) ──
# 전부 required + additionalProperties:false (strict). 값은 전부 문자열이고
# 빈 문자열이 "칸 비움/폼 유지"다 — 웹 표의 규약 그대로 (lib/mission.js).
# 예외는 runConditions의 토글 둘(boolean) — 폼 체크박스라 셋째 상태가 없다.
_LON_AXES = ["", "alt", "pitch", "hdot"]  # lib/mission.js LON_AXES value와 동일
_EXIT_KINDS = [  # lib/mission.js COND_KINDS 키와 동일 (인자 수는 프롬프트가 말한다)
    "always", "time_ge", "alt_ge", "alt_le", "speed_ge", "speed_le",
    "hdot_ge", "hdot_le", "path_done", "on_ground", "airborne", "off_rail",
]
_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "modeRows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "speed": {"type": "string"},
                    "lonAxis": {"type": "string", "enum": _LON_AXES},
                    "lonValue": {"type": "string"},
                    "heading": {"type": "string"},
                    "exitKind": {"type": "string", "enum": _EXIT_KINDS},
                    "exitValue": {"type": "string"},
                    "next": {"type": "string"},
                },
                "required": ["name", "speed", "lonAxis", "lonValue", "heading",
                             "exitKind", "exitValue", "next"],
                "additionalProperties": False,
            },
        },
        "wpRows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "string"},
                    "e": {"type": "string"},
                    "d": {"type": "string"},
                },
                "required": ["n", "e", "d"],
                "additionalProperties": False,
            },
        },
        "runConditions": {
            "type": "object",
            "properties": {
                "mach": {"type": "string"},
                "alt": {"type": "string"},
                "fuel": {"type": "string"},
                "groundOn": {"type": "boolean"},
                "launchOn": {"type": "boolean"},
                "tEnd": {"type": "string"},
                "accept": {"type": "string"},
            },
            "required": ["mach", "alt", "fuel", "groundOn", "launchOn",
                         "tEnd", "accept"],
            "additionalProperties": False,
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "assumptions", "modeRows", "wpRows",
                 "runConditions", "warnings"],
    "additionalProperties": False,
}

# ── 시스템 프롬프트 — 미션 표의 의미 규칙 (형상은 위 스키마가 강제한다) ──────────
# 아래 수치·규칙의 출처는 웹(views/sim.js 기본 미션·lib/mission.js)과 엔진 검증이다.
# 기본 미션은 **미션 시나리오**라 02 §5.5 재기술 금지 대상이 아니지만(웹 주석과
# 같은 판단), sim.js 기본 미션이 바뀌면 아래 예시가 조용히 낡는다 — 그때 함께 고칠 것.
_SYSTEM = """너는 CLAW 비행제어 설계툴의 미션 초안 생성기다. 사용자의 자연어
의도를 시뮬레이션 탭의 편집 표에 그대로 앉는 초안으로 바꾼다. 초안은 실행되지
않는다 — 사람이 표에서 다듬고 실행 버튼을 누르며, 틀린 값은 엔진이 거부한다.
그래도 첫 초안이 한 번에 완주 가능해야 이 기능이 뜻이 있다.

## 기체·무대 (고정 사실)
- 델타윙 단발 무인기. 트림 실속속도 70.9 m/s, 발사 이탈속도 81.5 m/s(=1.15×Vs),
  순항 88 m/s 부근, 뱅크 한계 0.7 rad에서 선회 반경 약 940 m.
- 무대는 고흥 시험장. NED 좌표(미터), 원점 = 활주로 남단 임계
  (위도 34.601303, 경도 127.212067). 활주로는 원점에서 진방위 0.05964 rad
  (3.417°) 방향으로 1205 m. 지형 팩 core가 반경 12 km라 웨이포인트는
  |n|, |e| ≤ 12000 안에 두고, 벗어나면 warnings에 적는다.
- 각도는 전부 라디안. hdot(강하율)은 상승이 +라 강하는 음수다.

## 표의 의미 규칙 (위반하면 화면·엔진이 거부한다)
1. 모든 칸 값은 문자열이다. 빈 문자열 ""는 "그 축 끔"이다.
2. lonAxis(종방향 축)는 ""·alt·pitch·hdot 중 하나 — 모드마다 종방향 명령은
   딱 하나다. lonValue가 그 축의 값이다.
3. "path"는 두 곳에서만: heading 칸(수평 경로 추종), lonAxis가 alt일 때의
   lonValue(세로 프로파일 추종). pitch·hdot 칸의 "path"는 거부된다.
4. exitKind와 인자: time_ge·alt_ge·alt_le·speed_ge·speed_le·hdot_ge·hdot_le는
   exitValue에 수치가 필수다(빈 문자열이면 거부). always·path_done·on_ground·
   airborne·off_rail은 exitValue를 ""로 둔다.
5. next 사슬: 실행은 첫 행에서 시작해 next로만 넘어간다. 모든 행이 첫 행에서
   닿아야 한다 — 아무도 가리키지 않는 행은 절대 실행되지 않는다. 마지막 행은
   next를 ""로 둔다.
6. 웨이포인트 d(고도)는 전부 채우거나 전부 비운다. 비울 때는 ""로 둔다(화면이
   키를 지운다). 수평 경로만 따를 미션이면 d를 전부 비우는 쪽이 단순하다.
7. heading에 "path"를 쓴 모드가 있으면 wpRows가 비면 안 된다(엔진 거부).
   반대로 wpRows를 채웠는데 어느 모드도 "path"를 안 쓰면 기체는 웨이포인트를
   무시하고 직진한다 — 경로를 날라는 의도면 반드시 한 모드의 heading을
   "path"로 둔다. 세로 프로파일(d)까지 따르려면 그 모드의 lonAxis를 alt,
   lonValue를 "path"로 둔다.
8. accept(도달 반경)는 특별한 이유가 없으면 "100"을 유지한다 — 너무 작으면
   선회 반경 때문에 경로가 영영 끝나지 않는다(path_done 미발화).
9. tEnd는 미션이 끝나는(착륙이면 정지) 시각을 여유 있게 덮어야 한다. 상한 3600.
10. 지상 출발(groundOn=true)이면 mach는 반드시 "0"이고 alt는 비행 고도가
    아니라 활주로 표고(기본 "0")다. launchOn=true면 발사대에서 뜬다.
    공중 수평비행에서 시작하려면 groundOn=false·launchOn=false로 두고
    mach를 양수(예: "0.26"≈88 m/s), alt를 시작 고도로 둔다.
11. 착륙(on_ground·접지·활주 정지)이 있는 미션은 groundOn=true여야 한다 —
    지면이 없으면 접지 판정 자체가 성립하지 않는다.
12. runConditions의 문자열 칸을 ""로 두면 화면의 현재 값이 유지된다. 확신이
    없는 칸은 ""로 두는 쪽이 낫다.

## 답하는 법
- summary는 초안이 무엇을 하는지 한 문장.
- assumptions에는 사용자가 말하지 않아 네가 정한 것을 전부 적는다(고도·속도·
  방향 등). warnings에는 요청을 그대로 못 지킨 것·위험한 값을 적는다.
- 모드 이름은 소문자 영문(launch·climb·cruise 등 관례)을 따른다.

## 검증된 완주 예시 (발사 → 순항(경로 추종) → 접근 → 착륙 정지, 약 101 s)
{"summary":"발사대에서 떠서 활주로 축 웨이포인트를 따라 순항하고 되돌아와 정지",
"assumptions":["순항 고도 200 m","순항 속도 88 m/s"],
"modeRows":[
{"name":"launch","speed":"110","lonAxis":"pitch","lonValue":"0.3665","heading":"0.05964","exitKind":"off_rail","exitValue":"","next":"climb"},
{"name":"climb","speed":"110","lonAxis":"pitch","lonValue":"0.3665","heading":"0.05964","exitKind":"alt_ge","exitValue":"180","next":"cruise"},
{"name":"cruise","speed":"88","lonAxis":"alt","lonValue":"200","heading":"path","exitKind":"path_done","exitValue":"","next":"approach"},
{"name":"approach","speed":"88","lonAxis":"hdot","lonValue":"-4.8","heading":"0.05964","exitKind":"alt_le","exitValue":"20","next":"flare"},
{"name":"flare","speed":"80","lonAxis":"hdot","lonValue":"-0.8","heading":"0.05964","exitKind":"on_ground","exitValue":"","next":"rollout"},
{"name":"rollout","speed":"0","lonAxis":"pitch","lonValue":"0","heading":"0.05964","exitKind":"speed_le","exitValue":"0.5","next":"stopped"},
{"name":"stopped","speed":"0","lonAxis":"pitch","lonValue":"0","heading":"","exitKind":"time_ge","exitValue":"1e9","next":""}],
"wpRows":[{"n":"2596","e":"155","d":""},{"n":"3294","e":"197","d":""}],
"runConditions":{"mach":"0","alt":"0","fuel":"300","groundOn":true,"launchOn":true,"tEnd":"200","accept":"100"},
"warnings":[]}"""


def call_llm(*, api_key: str, model: str, system: str, user: str,
             schema: dict) -> dict:
    """선택된 백엔드에 1회 호출 — **Anthropic Messages 형상**의 dict를 돌려준다.

    프롬프트·스키마를 인자로 받는 이유: 네 기능이 이 한 함수를 공유해야
    "아웃바운드는 하나"라는 머리말 선언이 사실로 남는다. **테스트가 이 전역을
    monkeypatch로 갈아끼운다** (test_trim의 trim_batch 교체와 같은 형태).
    내부 계약을 Anthropic 형상으로 고정한 이유: 소비자(_extract_json과 라우트의
    usage 저장)가 형상 하나만 알면 되고, 로컬 응답은 _post_openai가 그 형상으로
    정규화한다 — 백엔드가 늘어도 라우트·저장·웹은 바뀌지 않는다.
    """
    if _backend() == "openai":
        return _post_openai(api_key=api_key, model=model, system=system,
                            user=user, schema=schema)
    return _post_anthropic(api_key=api_key, model=model, system=system,
                           user=user, schema=schema)


def _post_anthropic(*, api_key: str, model: str, system: str, user: str,
                    schema: dict) -> dict:
    """Anthropic Messages API 와이어. httpx는 _post_* 두 함수 안에서만 import
    한다 — 아웃바운드가 이 파일의 두 함수에 갇혀 있음을 코드 구조가 그대로
    말하게."""
    import httpx

    try:
        r = httpx.post(
            _ANTHROPIC_URL,
            timeout=_TIMEOUT_S,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": _MAX_TOKENS,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                # 응답 첫 text 블록이 스키마에 맞는 JSON임을 API가 보장한다
                # (structured outputs GA — 현행 이름은 output_config.format이고
                #  output_format은 구명칭·폐기, 베타 헤더 불요). 이 페이로드는
                #  테스트가 통짜로 고정한다(test_llm 「나가는 요청」) — 대부분의
                #  테스트가 call_llm을 통째로 갈아끼우므로, 그 경계 안쪽이
                #  틀려도 조용히 초록이 되는 것을 그 테스트 하나가 막는다
                "output_config": {"format": {"type": "json_schema",
                                             "schema": schema}},
            },
        )
    except httpx.HTTPError as e:  # 연결·타임아웃 — 원인을 한국어 한 줄로
        raise RuntimeError(f"Anthropic API 연결 실패 — {e}") from e
    if r.status_code != 200:
        try:
            detail = r.json()["error"]["message"]
        except Exception:
            detail = r.text[:300]
        raise RuntimeError(f"Anthropic API {r.status_code} — {detail}")
    return r.json()


def _post_openai(*, api_key: str, model: str, system: str, user: str,
                 schema: dict) -> dict:
    """OpenAI 호환(/chat/completions) 와이어 — 폐쇄망 사내 서버(vLLM 등)용.

    구조화 출력은 response_format.json_schema(strict)다 — 이 필드를 무시하는
    서버·모델이면 응답이 산문일 수 있고, 그때는 _extract_json의 JSON 가드가
    사유 문장으로 잡는다(트레이스백 금지). 스키마 4벌은 전 키 required +
    additionalProperties:false라 strict 형과 그대로 맞는다. 이 페이로드도
    골든 테스트가 통짜로 고정한다(test_llm 「로컬 백엔드로 나가는 요청」).
    """
    import httpx

    headers = {"content-type": "application/json"}
    if api_key:  # 게이트웨이만 요구한다 — 없으면 헤더 자체를 달지 않는다
        headers["authorization"] = f"Bearer {api_key}"
    try:
        r = httpx.post(
            f"{_local_base_url()}/chat/completions",
            timeout=_TIMEOUT_S,
            headers=headers,
            json={
                "model": model,
                "max_tokens": _MAX_TOKENS,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "claw_output",
                                                    "strict": True,
                                                    "schema": schema}},
            },
        )
    except httpx.HTTPError as e:
        raise RuntimeError(f"로컬 LLM 서버 연결 실패 — {e}") from e
    if r.status_code != 200:
        try:
            detail = r.json()["error"]["message"]
        except Exception:
            detail = r.text[:300]
        raise RuntimeError(f"로컬 LLM 서버 {r.status_code} — {detail}")
    return _to_anthropic_shape(r.json())


def _to_anthropic_shape(raw: dict) -> dict:
    """OpenAI 호환 응답 → 내부 계약(Anthropic 형상) 정규화.

    usage까지 옮기는 이유: 라우트가 raw.get("usage")를 그대로 저장한다 — 키
    이름이 갈리면(prompt_tokens ↔ input_tokens) 저장 형상이 백엔드마다 달라져
    조용히 깨진다(설계 조사가 찾은 유일한 누수 지점). content_filter는
    refusal로 옮긴다 — 거절이 백엔드와 무관하게 같은 사유 경로로 나온다.
    """
    choices = raw.get("choices") or []
    first = choices[0] if choices else {}
    text = (first.get("message") or {}).get("content")
    finish = first.get("finish_reason")
    usage = raw.get("usage") or {}
    return {
        "content": ([{"type": "text", "text": text}]
                    if isinstance(text, str) and text else []),
        # 어휘까지 하나로 옮긴다 — 반만 옮기면(content_filter만) stop_reason을
        # 보는 분기가 로컬 백엔드에서만 조용히 빠진다. 잘림 사유 분리
        # (_extract_json의 max_tokens 판정)가 바로 그 소비자다 (리뷰 지적)
        "stop_reason": {"content_filter": "refusal", "stop": "end_turn",
                        "length": "max_tokens"}.get(finish, finish),
        "usage": {"input_tokens": usage.get("prompt_tokens"),
                  "output_tokens": usage.get("completion_tokens")},
    }


def _strip_fence(text: str) -> str:
    """```json 펜스 벗기기 — 구조화 출력 강제가 약한 로컬 모델의 흔한 버릇.
    펜스가 아니면 그대로 돌려준다."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    t = t.split("\n", 1)[1] if "\n" in t else ""
    t = t.rstrip()
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


def _extract_json(raw: dict) -> dict:
    """원시 응답 → 구조화 출력 dict (네 기능 공용). 형상은 structured output이
    보장하는 것이 정상이지만, 거부(stop_reason refusal)·텍스트 블록 부재·JSON
    아님은 여기서 사유를 들어 실패시킨다 — 마지막 것은 강제가 약한 로컬
    백엔드가 처음 밟는 자리이고, 가드가 없으면 파이썬 트레이스백이 그대로
    화면까지 갔다(이 파일에서 유일하게 사유 문장 규약 밖이던 곳)."""
    if raw.get("stop_reason") == "refusal":
        # 네 기능 공용 경로다 — 특정 기능의 입력("의도 문장")을 지목하지 않는다
        raise RuntimeError("모델이 요청을 거절했습니다 — 입력을 바꿔 다시 시도하십시오.")
    text = next(
        (b.get("text") for b in raw.get("content", []) if b.get("type") == "text"),
        None,
    )
    if not text:
        raise RuntimeError(
            f"응답에 텍스트가 없습니다 (stop_reason={raw.get('stop_reason')})")
    text = _strip_fence(text)
    try:
        return json.loads(text)
    except ValueError as e:
        if raw.get("stop_reason") == "max_tokens":
            # 잘린 JSON을 "모델 탓"으로 오진하지 않는다 — 처방(입력 축소)이
            # 다르다. 로컬의 length는 _to_anthropic_shape가 이 어휘로 옮겨
            # 두 백엔드가 같은 길을 탄다 (리뷰 지적)
            raise RuntimeError(
                "모델 출력이 토큰 상한에서 잘렸습니다 — 입력(결과·질문)을 "
                "줄여 다시 시도하십시오.") from e
        raise RuntimeError(
            f"모델 응답이 JSON이 아닙니다 ({e}) — 응답 앞부분: {text[:200]}") from e


class MissionDraftIn(BaseModel):
    """초안 요청 — 자연어 의도 한 덩이."""

    intent: str = Field(min_length=1, max_length=4000)

    @field_validator("intent")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        # 공백만으로는 min_length를 통과한다 — 빈 의도로 실 API를 부르지 않는다
        if not v.strip():
            raise ValueError("의도 문장이 공백뿐입니다")
        return v


@router.get("/llm/status")
def llm_status() -> dict:
    """켜져 있는가 — 아니면 404가 아니라 **사유 문장** (world/manifest 규약).

    backend 키는 additive다(웹은 모르는 키를 무시한다) — 둘 다 설정된 배포에서
    어느 쪽이 이겼는지 화면에서 확인할 수 있게."""
    b = _backend()
    if b is None:
        return {"available": False, "model": None, "backend": None,
                "reason": _UNAVAILABLE}
    if b == "openai" and not _local_model():
        return {"available": False, "model": None, "backend": b,
                "reason": _UNAVAILABLE_LOCAL_MODEL}
    return {
        "available": True,
        "model": _local_model() if b == "openai" else _model(),
        "backend": b,
        "reason": None,
    }


@router.post("/llm/mission-draft", status_code=202)
def submit_mission_draft(req: MissionDraftIn, request: Request,
                         response: Response) -> dict:
    model, key = _require_backend()  # 백엔드 미설정은 제출 시점 503 + 사유
    store = request.app.state.store

    def work(job):
        # 단발 호출이라도 **보고를 두 번 이상** 한다 — 한 번도 안 하면
        # done==total==0이라 취소를 눌러도 상태가 done으로 남는다
        # (jobs.py _run의 completed 판정)
        if job.report(0, 2, message=f"{model} 호출 중"):
            return  # 협조적 취소 — 저장 없음
        raw = call_llm(api_key=key, model=model, system=_SYSTEM,
                       user=req.intent, schema=_DRAFT_SCHEMA)
        if job.report(1, 2, message="응답 정리 중"):
            return  # 호출 중 취소가 눌렸다 — 초안을 버린다
        draft = _extract_json(raw)
        store.save(
            job.id,
            {"kind": "mission_draft", "intent": req.intent, "draft": draft,
             "model": model, "usage": raw.get("usage")},
            meta={
                "kind": "mission_draft",
                "created": job.created,
                # 지문은 형상 계보 키인데 초안은 형상 산출물이 아니다 — 빈 값이
                # "계보 없음"을 그대로 말한다 (위장 금지)
                "fingerprint": "",
                "n": len(draft.get("modeRows") or [])
                if isinstance(draft, dict) else 0,
            },
        )
        job.result_id = job.id
        job.report(2, 2, message="완료")

    job = request.app.state.jobs.submit("mission_draft", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


class BriefIn(BaseModel):
    """소견서 요청 — 대상 결과 하나."""

    # store._ID_RE와 같은 문법 — 경로 조작이 여기서 이미 걸린다
    result_id: str = Field(min_length=1, max_length=64,
                           pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/llm/brief", status_code=202)
def submit_brief(req: BriefIn, request: Request, response: Response) -> dict:
    model, key = _require_backend()  # 백엔드 미설정은 제출 시점 503 + 사유
    store = request.app.state.store
    # 대상 확인은 메타로 한다 — 본문 로드는 잡 안에서 (sim 최대 54MB를 요청
    # 스레드에서 열지 않는다). 메타는 건당 ~130B라 전량 조회가 싸다.
    meta = next((m for m in store.list() if m["id"] == req.result_id), None)
    if meta is None:
        # 사유에 복구 단서까지 — design.py resume 404와 같은 규약
        raise HTTPException(
            status_code=404,
            detail=f"결과 없음: {req.result_id} — 저장소 보존 상한에 밀려났거나 "
                   "지워졌을 수 있습니다. 결과 탭을 새로고침하십시오.")
    if meta.get("kind") == "llm_brief":
        raise HTTPException(
            status_code=422,
            detail="소견서의 소견서는 만들지 않습니다 — 원 산출물에 브리핑을 거십시오.")

    def work(job):
        # 보고 최소 2회 규약 — 미션 초안과 같은 이유 (안 하면 취소가 done으로
        # 위장). 여기는 3단계다: sim 54MB는 읽기·가지치기만 수 초라 그 구간을
        # "호출 중"이라고 말하면 화면이 거짓말하고, 호출 직전 보고가 돈 쓰기 전
        # 마지막 취소 지점이 된다 (리뷰 지적).
        if job.report(0, 3, message="결과 읽는 중"):
            return
        try:
            payload = store.load(req.result_id)
        except KeyError:
            # 제출 시점 메타 확인과 이 로드 사이에 보존 상한이 대상을 밀어냈다 —
            # 트레이스백이 아니라 사유 문장으로 (design.py resume KeyError 선례)
            raise RuntimeError(
                f"결과가 사라졌습니다: {req.result_id} — 저장소 보존 상한에 "
                "밀려났거나 지워졌을 수 있습니다. 결과 탭을 새로고침하십시오.")
        kind = str(meta.get("kind") or payload.get("kind") or "")
        pruned = prune(payload, kind)
        del payload  # sim 54MB — 가지치기 뒤에는 들고 있지 않는다
        if job.report(1, 3, message=f"{model} 호출 중"):
            return  # 돈 쓰기 전 마지막 취소 지점
        raw = call_llm(api_key=key, model=model, system=BRIEF_SYSTEM,
                       user=brief_user(meta, pruned), schema=BRIEF_SCHEMA)
        if job.report(2, 3, message="소견서 정리 중"):
            return  # 호출 중 취소 — 소견서를 버린다
        brief = _extract_json(raw)
        look_at = brief.get("look_at")
        if not isinstance(look_at, list):
            look_at = []  # headline·body의 str() 강제와 같은 결 — 형상만 지킨다
        store.save(
            job.id,
            {"kind": "llm_brief", "parent": req.result_id, "parent_kind": kind,
             "headline": str(brief.get("headline") or ""),
             "body": str(brief.get("body") or ""),
             "look_at": [str(x) for x in look_at],
             "model": model, "usage": raw.get("usage")},
            meta={
                "kind": "llm_brief",
                "created": job.created,
                # 대상의 지문을 승계 — 목록에서 같은 계보로 묶인다. 대상에
                # 지문이 없으면 없는 그대로 (위장 금지)
                "fingerprint": meta.get("fingerprint", ""),
                # 어느 결과의 소견인지 — auto_design meta.parent 선례
                "parent": req.result_id,
            },
        )
        job.result_id = job.id
        job.report(3, 3, message="완료")

    job = request.app.state.jobs.submit("llm_brief", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


@router.post("/llm/comms", status_code=202)
def submit_comms(req: BriefIn, request: Request, response: Response) -> dict:
    """관제 교신 대본 — sim 런 하나의 비행 로그를 뽑아 LLM에 대본을 시킨다.

    요청 형상이 브리핑과 같아 BriefIn을 그대로 쓴다(result_id 하나).
    대상은 sim뿐이다 — 비행 로그 추출기(comms.flight_log)가 sim 신호 계약
    위에 서 있다.
    """
    model, key = _require_backend()  # 백엔드 미설정은 제출 시점 503 + 사유
    store = request.app.state.store
    meta = next((m for m in store.list() if m["id"] == req.result_id), None)
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"결과 없음: {req.result_id} — 저장소 보존 상한에 밀려났거나 "
                   "지워졌을 수 있습니다. 결과 탭을 새로고침하십시오.")
    if meta.get("kind") != "sim":
        raise HTTPException(
            status_code=422,
            detail=f"sim 결과가 아님: {req.result_id} ({meta.get('kind')}) — "
                   "교신 대본은 시뮬레이션 런에서만 만듭니다.")

    def work(job):
        # 3단계 보고 — 브리핑과 같은 이유 (읽기 구간을 "호출 중"으로 위장하지
        # 않고, 호출 직전 보고가 돈 쓰기 전 마지막 취소 지점)
        if job.report(0, 3, message="결과 읽는 중"):
            return
        try:
            payload = store.load(req.result_id)
        except KeyError:
            raise RuntimeError(
                f"결과가 사라졌습니다: {req.result_id} — 저장소 보존 상한에 "
                "밀려났거나 지워졌을 수 있습니다. 결과 탭을 새로고침하십시오.")
        log = flight_log(payload)
        del payload  # sim 54MB — 추출 뒤에는 들고 있지 않는다
        if job.report(1, 3, message=f"{model} 호출 중"):
            return  # 돈 쓰기 전 마지막 취소 지점
        raw = call_llm(api_key=key, model=model, system=COMMS_SYSTEM,
                       user=comms_user(meta, log), schema=COMMS_SCHEMA)
        if job.report(2, 3, message="대본 정리 중"):
            return  # 호출 중 취소 — 대본을 버린다
        data = _extract_json(raw)
        # 대본에는 웹 정규화가 없다(초안 normalizeDraft·문답 normalizeAnswer와
        # 달리) — 스키마 강제가 약한 로컬 백엔드에서 어긴 값이 저장되면 그대로
        # 자막·발화로 흐른다. 여기가 마지막 방어선이다
        lines = validate_lines(data)
        store.save(
            job.id,
            {"kind": "llm_comms", "parent": req.result_id, "parent_kind": "sim",
             "lines": lines, "warnings": data.get("warnings") or [],
             "model": model, "usage": raw.get("usage")},
            meta={
                "kind": "llm_comms",
                "created": job.created,
                "fingerprint": meta.get("fingerprint", ""),  # 대상 지문 승계
                "parent": req.result_id,
                "n": len(lines),  # 목록 건수 칸 = 대본 줄 수
            },
        )
        job.result_id = job.id
        job.report(3, 3, message="완료")

    job = request.app.state.jobs.submit("llm_comms", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()


class AskIn(BaseModel):
    """전역 질문 — 어느 탭에서든 묻는 한 줄."""

    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("질문이 공백뿐입니다")
        return v


@router.post("/llm/ask", status_code=202)
def submit_ask(req: AskIn, request: Request, response: Response) -> dict:
    """질문 → 답 + 화면 이동 액션 (Q&A 내비게이션 — 웹이 첫 액션으로 이동한다)."""
    model, key = _require_backend()  # 백엔드 미설정은 제출 시점 503 + 사유
    store = request.app.state.store

    def work(job):
        if job.report(0, 2, message=f"{model} 호출 중"):
            return  # 협조적 취소 — 보고 2회 규약은 미션 초안과 같은 이유
        # 최근 메타 머리 30건 — 건당 ~130B라 유계이고, "돌린 적 있나"류 질문의
        # 실재 근거가 된다 (본문 수치는 안 준다 — ask.py 규칙 3)
        metas = store.list()[:30]
        raw = call_llm(api_key=key, model=model, system=ASK_SYSTEM,
                       user=ask_user(req.question, metas),
                       schema=ASK_SCHEMA)
        if job.report(1, 2, message="답 정리 중"):
            return
        data = _extract_json(raw)
        actions = data.get("actions") or []
        store.save(
            job.id,
            {"kind": "llm_ask", "question": req.question,
             "answer": str(data.get("answer") or ""), "actions": actions,
             "model": model, "usage": raw.get("usage")},
            meta={
                "kind": "llm_ask",
                "created": job.created,
                "fingerprint": "",  # 문답은 형상 산출물이 아니다 — 계보 없음 그대로
                "n": len(actions),
            },
        )
        job.result_id = job.id
        job.report(2, 2, message="완료")

    job = request.app.state.jobs.submit("llm_ask", work)
    response.headers["Location"] = f"/api/jobs/{job.id}"
    return job.to_dict()
