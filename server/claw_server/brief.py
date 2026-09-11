"""결과 브리핑 준비 — 가지치기·프롬프트·출력 스키마 (순수 로직, 아웃바운드 없음).

LLM 호출 자체는 routes/llm.py에 있다 — "이 리포의 유일한 런타임 아웃바운드"
선언(그 파일 머리말)을 지키려고 여기는 httpx를 모른다. 여기 있는 것은 "무엇을
보낼 것인가"다.

## 왜 가지치기가 이 기능의 본체인가 (server_data 232건 실측)

결과 본문은 종류마다 세 자릿수 배 차이가 난다 — sim이 중앙값 10MB·최대
54MB(40,000스텝 × 신호 80키)이고 나머지는 수십 KB다. 통째로는 못 보내고,
단순 head-N 절단은 판정 행(verify summary 5행·카드 7장·checks 9건)을 소리
없이 먹는다. 그리고 벌크의 절반은 배열이 아니라 **케이스명을 키로 한 dict**다
(auto_design margin_out.cases·trims, openloop params). 그래서 규칙은 둘이다:

1층 — kind 무관 크기 예산: 직렬화 4KB 이하 노드는 통째 유지(판정 묶음이
전부 이 경계 아래다), 초과하면 배열·동질 dict 공통으로 표본 5개 + `_n`(전체)·
`_omitted`(생략) 마커. **자른 사실이 데이터 안에 남아** 브리핑이 "전부 봤다"고
말하지 못한다(자동 설계 원장 절단 규약과 같은 자리 — design.py MAX_LEDGER_ROWS).
구조 dict(값 이질 — auto_design 최상위 22키 같은 것)는 키를 자르지 않고 값만
줄인다: 키를 표본화하면 report·status 같은 판정이 사라진다.

2층 — 배제 경로 (진짜 괴물 2종만, 도메인 로직이 아니라 경로 목록):
sim의 시계열(signals·t·envelope.stall_margin·flags)과 verify_flight의 소스
동봉(report.files). 표본 3개짜리 시계열 80줄은 순수 노이즈라 개수조차 싣지
않고 마커 한 줄로 대신한다. 모르는 kind·옛 스키마는 1층만 타고 지나간다
(구버전 evaluate에 checks가 없는 실측 사례 — 조용히 죽지 않는다).
"""

import json

KEEP_WHOLE_BYTES = 4096  # 판정 묶음(카드 7장 2.9KB 등)이 미절단으로 남는 경계
SAMPLE_K = 5
STR_MAX = 400
# 동질 dict(케이스명 키 컬렉션) 판정의 최소 키 수 — 이보다 작으면 구조 dict로 본다
_HOMOG_MIN_KEYS = 8

_EXCLUDED = "[제외 — 대용량 원자료, 브리핑에 싣지 않음]"
# 판정상 나쁜 항목의 표식 — 표본이 이것을 우선 담는다 (아래 _pick).
# "false"는 이 리포의 플래그가 전부 `*_ok`·`converged` 극성(true=정상)이라는
# 전제 위에 있다 — true=나쁨 플래그(예: stalled)가 생기면 우선순위만 퇴화할 뿐
# 계약(_omitted 정직성)은 유지되지만, 그때 이 표를 다시 볼 것.
_FAIL_MARKS = ('"fail"', '"warn"', "false")
# 이보다 큰 컬렉션은 판정 우선 스캔을 생략한다 — 스캔 자체가 예산이 되면 본말전도
_SCAN_MAX = 1000

# kind → 통째 배제할 경로(최상위부터의 키 튜플). 여기 없는 kind는 1층만 탄다.
EXCLUDE_PATHS = {
    "sim": {("t",), ("signals",),
            ("envelope", "stall_margin"), ("envelope", "flags")},
    "verify_flight": {("report", "files")},
}


def _exceeds(node, budget: int) -> bool:
    """직렬화 길이 어림이 예산을 넘는가 — 넘는 순간 멈춘다.

    정확한 크기는 필요 없다(경계 판정뿐이다). json.dumps로 재면 상위 노드마다
    아래 전체를 재직렬화해 54MB 본문에서 GIL을 초 단위로 쥔다(리뷰 실측 —
    깊이×크기). 어림 규칙: 문자열 len+2 · 키 len+4 · 수치 str 길이 · 컨테이너
    구두점 — ensure_ascii=False 기준 실제와 오차 몇 %라 4KB 경계 판정에 충분하고,
    판정 묶음(≤3KB)과 벌크(수십 KB~MB)는 그 오차로 갈리지 않는다."""
    total = 0
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, str):
            total += len(n) + 2
        elif isinstance(n, bool) or n is None:
            total += 5
        elif isinstance(n, (int, float)):
            total += len(str(n))
        elif isinstance(n, dict):
            total += 2
            for k, v in n.items():
                total += len(str(k)) + 4
                stack.append(v)
        elif isinstance(n, list):
            total += 2 + 2 * len(n)
            stack.extend(n)
        else:
            total += 8
        if total > budget:
            return True
    return False


def _bad(entry) -> bool:
    s = json.dumps(entry, ensure_ascii=False).lower()
    return any(m in s for m in _FAIL_MARKS)


def _pick(keys, value_of):
    """표본 선택 — 판정상 나쁜 항목(fail/warn/false)을 먼저, 나머지는 앞에서부터.

    앞 5개 고정이면 뒤쪽의 유일한 fail 케이스가 표본에서 빠진다(리뷰 실측 —
    _omitted가 정직하게 남긴 하지만 소견서가 그 fail을 인용할 수 없게 된다).
    스캔은 컬렉션이 작을 때만 — 4만 표본짜리 수치 배열을 항목별로 직렬화하며
    뒤지는 것은 가지치기가 막으려던 비용 그 자체다."""
    if len(keys) <= SAMPLE_K or len(keys) > _SCAN_MAX:
        return keys[:SAMPLE_K]
    # 나쁜 항목 K개를 채우면 스캔을 멈춘다 — 컴프리헨션으로 쓰면 다 찾은 뒤에도
    # 남은 항목 전부를 직렬화한다 (항목이 큰 컬렉션에서 전량 1회 직렬화 비용)
    picked = []
    for k in keys:
        if _bad(value_of(k)):
            picked.append(k)
            if len(picked) == SAMPLE_K:
                break
    if len(picked) < SAMPLE_K:
        chosen = set(picked)
        for k in keys:
            if k not in chosen:
                picked.append(k)
                if len(picked) == SAMPLE_K:
                    break
    return picked


def _homogeneous(d: dict) -> bool:
    """케이스명 키 컬렉션인가 — 키가 많고 값이 전부 같은 컨테이너 타입.

    구조 dict(값에 str·int·dict가 섞인 것)는 False가 되어 키를 안 자른다."""
    if len(d) < _HOMOG_MIN_KEYS:
        return False
    kinds = {type(v) for v in d.values()}
    return kinds == {dict} or kinds == {list}


def _prune(node, path, excl):
    if path in excl:
        return _EXCLUDED
    if isinstance(node, str):
        if len(node) <= STR_MAX:
            return node
        return node[:STR_MAX] + f"… [+{len(node) - STR_MAX}자 생략]"
    if not isinstance(node, (dict, list)):
        return node  # 수치·불리언·None — 400자리 int도 변환 없이 그대로 (실측 함정)
    if not _exceeds(node, KEEP_WHOLE_BYTES):
        return node  # 통째 유지 — 판정 행 5~9개짜리 묶음이 여기서 산다
    if isinstance(node, list):
        idx = _pick(list(range(len(node))), lambda i: node[i])
        return {
            "_sample": [_prune(node[i], path, excl) for i in idx],
            "_n": len(node),
            "_omitted": max(len(node) - SAMPLE_K, 0),
        }
    # dict — 동질(케이스명 키)이면 배열과 같은 규칙, 아니면 키 보존·값만 축소
    if _homogeneous(node):
        keys = _pick(list(node), lambda k: node[k])
        return {
            "_sample": {k: _prune(node[k], path + (k,), excl) for k in keys},
            "_n": len(node),
            "_omitted": max(len(node) - SAMPLE_K, 0),
        }
    return {k: _prune(v, path + (k,), excl) for k, v in node.items()}


def prune(payload: dict, kind: str) -> dict:
    """결과 본문 → LLM에 실을 수 있는 크기의 정직한 축약."""
    return _prune(payload, (), EXCLUDE_PATHS.get(kind, frozenset()))


# ── 소견서 출력 스키마 — headline 한 문장 · body 서술 · look_at 화면 안내 ──────
BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "body": {"type": "string"},
        "look_at": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "body", "look_at"],
    "additionalProperties": False,
}

BRIEF_SYSTEM = """너는 CLAW 비행제어 설계툴의 산출물 소견서 작성자다. 결과
JSON 하나를 읽고, 엔지니어가 30초 안에 상황을 잡는 한국어 소견서를 쓴다.

## 이 도구가 내는 산출물 종류 (kind)
- trim_batch: 격자 트림 배치 — 케이스별 수렴·플래그(잔차/포화/α여유/연속성)
- margin_map: 케이스 격자 × 개루프 마진(PM·GM)·모드 감쇠
- envelope_scan: 설계 엔벨로프 제어 가능 판정 (trim 가능 여부·사유)
- sim: 폐루프 미션 시뮬 — envelope 감시 스칼라(worst_margin·any_flag…)와
  착륙 단계 시각(meta.phases: launch_exit_t/touchdown_t/stop_t)
- auto_design: 자동 설계 루프 — report(점 배치·판정 수)·proposed_actions(처방)·
  ledger(미달 원장)·iterations
- verify_flight: 탑재 C의 DAL A 검증 — report.summary 5행 + verdict
- influence_evaluate: 케이스 격자 전체 6DOF 평가 — cards(대표 7)·checks·
  aggregate(hard_fail이면 불합격)
- influence_verify: 3단계 검증(강건성 코너 재트림) / influence_scan·sweep·
  openloop: 감도(흔들면 얼마나 움직이나)
- influence_prescribe: 정량 처방 — 수정안(singles/joint)·확인 런(confirm)
- llm_brief: 이 소견서 자신 / mission_draft: LLM 미션 초안

## 규칙
1. 수치·판정은 준 데이터에 있는 것만 인용한다 — 지어내지 않는다.
2. `_n`·`_omitted`·`_sample` 키와 "[제외 —"·"[+N자 생략" 문구는 가지치기
   흔적이다: 그 부분은 전량을 본 것이 아니므로 개수만 말하고 단정하지 않는다.
3. "inf"/"-inf" 문자열은 비유한값의 직렬화다 — 마진 ∞는 보통 그 축 무제약.
4. 판정 어휘: status·verdict·converged·hard_fail·flags·aborted·warnings.
   aborted가 참이거나 warnings가 있으면 반드시 언급한다.
5. look_at은 이 툴의 화면 자리로 안내한다 — 탭 이름: 블록도·엔벨로프·트림·
   게인·마진 맵·자동 설계·시뮬레이션·가상환경·영향성·Autocode·검증·결과.
   예: "시뮬레이션 탭 「재생 + 엔벨로프 감시」 패널에서 접지 구간 확인".
6. headline은 판정이 담긴 한 문장. body는 2~4문단 — 무엇을 돌렸나 → 판정 →
   눈에 띄는 것(최악점·경계 근접·경고). look_at은 1~4개."""


def brief_user(meta: dict, pruned: dict) -> str:
    """LLM 사용자 메시지 — 메타(종류·시각·지문)와 가지치기된 본문."""
    return (
        "다음 산출물의 소견서를 써라.\n"
        f"메타: {json.dumps(meta, ensure_ascii=False)}\n"
        f"본문(가지치기됨): {json.dumps(pruned, ensure_ascii=False)}"
    )
