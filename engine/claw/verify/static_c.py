"""생성 C 정적 검사 — 파서가 아니라 **생성 코드 규율 검사**다 (M12).

범용 C 정적 분석기(MISRA 전 규칙)가 아니다 — 그건 수년짜리 별개 사업이고, 최종
독립 검증은 상용 툴(LDRA/VectorCAST) 자리다. 여기서 검사하는 것은 우리 생성기가
지키기로 한 규율이 실제 산출물에서 지켜졌는가이며, 대상이 `emit_c.py`가 내는
제한된 형태(함수는 0열에서 시작, 매크로는 #define 상수뿐, 문자열 리터럴 없음)라
정규식 수준의 스캐너로 **거짓 통과 없이** 판정할 수 있다.

각 규칙은 안전 관련 코딩 표준(MISRA C·DO-178C 논점)의 대응 항목을 갖지만,
"MISRA 준수"를 주장하지 않는다 — 검사한 것만 말한다.
"""

import re

# 금지 토큰 — {토큰: 사유}. 호출·구문 이름 그대로 단어 경계로 잡는다.
BANNED = {
    "goto": "비구조적 분기 (MISRA 15.1 대응)",
    "setjmp": "비지역 점프 — 상태 일관성 파괴",
    "longjmp": "비지역 점프 — 상태 일관성 파괴",
    "malloc": "동적 메모리 (비행 중 할당 금지)",
    "calloc": "동적 메모리 (비행 중 할당 금지)",
    "realloc": "동적 메모리 (비행 중 할당 금지)",
    "free": "동적 메모리 (비행 중 할당 금지)",
    "alloca": "스택 동적 할당",
    "printf": "표준입출력 — 탑재 코드에 I/O 없음",
    "sprintf": "버퍼 안전성 + I/O",
    "exit": "프로세스 종료 — 비행 중 예외 금지 원칙",
    "abort": "프로세스 종료 — 비행 중 예외 금지 원칙",
    "assert": "런타임 중단 — 비행 중 예외 금지 원칙",
    "rand": "비결정 — 결정적 실행 원칙",
    "float": "단정밀도 — 전 연산 배정밀도(double) 원칙",
    "switch": "생성기 미사용 구문 — 나타나면 생성기 밖에서 온 코드다",
}

_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
_FN_DEF = re.compile(r"^(?:double|void|int)\s+(\w+)\s*\(", re.M)
# 판정 지점: if/while/for + 단락 논리 + 3항 (case는 switch 금지라 없다)
_DECISION = re.compile(r"\b(?:if|while|for)\b|&&|\|\||\?")
_CALL = re.compile(r"\b(\w+)\s*\(")
_KEYWORDS = frozenset("if while for return sizeof".split())


def strip_comments_strings(text: str) -> str:
    """주석·문자열 제거 — 줄 번호 보존(개행은 남긴다). 규칙 스캔은 이 결과 위에서."""
    def _blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))

    return _STRING.sub(_blank, _COMMENT.sub(_blank, text))


def functions_of(text: str) -> list:
    """함수 정의 목록 [{name, line, lines, body}] — 생성 스타일(0열 시작) 전제.

    본문은 여는 중괄호부터 짝 맞는 닫는 중괄호까지. 중괄호 짝이 안 맞으면
    ValueError — 조용히 일부만 보는 것보다 시끄럽게 끝나는 쪽이다.
    """
    clean = strip_comments_strings(text)
    out = []
    for m in _FN_DEF.finditer(clean):
        open_idx = clean.find("{", m.end())
        semi_idx = clean.find(";", m.end())
        if open_idx < 0 or (0 <= semi_idx < open_idx):
            continue  # 프로토타입 선언
        depth, i = 0, open_idx
        while i < len(clean):
            if clean[i] == "{":
                depth += 1
            elif clean[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            raise ValueError(f"{m.group(1)}: 중괄호 짝이 맞지 않는다")
        body = clean[open_idx:i + 1]
        line = clean.count("\n", 0, m.start()) + 1
        out.append({
            "name": m.group(1),
            "line": line,
            "lines": body.count("\n") + 1,
            "body": body,
        })
    return out


def cyclomatic(body: str) -> int:
    """순환 복잡도 — 1 + 판정 지점 수 (if·while·for·&&·||·?:)."""
    return 1 + len(_DECISION.findall(body))


def called_names(body: str) -> set:
    """본문이 부르는 식별자 집합 (키워드 제외) — 재귀 판정용 콜그래프의 간선."""
    return {n for n in _CALL.findall(body) if n not in _KEYWORDS}


def _find_recursion(fns: dict) -> list:
    """정의된 함수들 사이의 (간접 포함) 재귀 사이클 — 있으면 경로 목록."""
    calls = {name: called_names(f["body"]) & set(fns) for name, f in fns.items()}
    hits = []
    for start in sorted(calls):
        stack, seen = [(start, [start])], set()
        while stack:
            cur, path = stack.pop()
            for nxt in sorted(calls[cur]):
                if nxt == start:
                    hits.append(" → ".join(path + [start]))
                elif nxt not in seen:
                    seen.add(nxt)
                    stack.append((nxt, path + [nxt]))
    return hits


def _mutable_globals(text: str) -> list:
    """파일 스코프의 비-const 정의 — 생성 .c에는 const 파라미터 하나뿐이어야 한다."""
    clean = strip_comments_strings(text)
    hits, depth = [], 0
    for k, raw in enumerate(clean.split("\n"), start=1):
        line = raw.strip()
        at_top = depth == 0
        depth += raw.count("{") - raw.count("}")
        if not at_top or not line or line.startswith("#"):
            continue
        # 함수 정의·프로토타입·닫는 중괄호·초기화자 내부 행은 제외
        if "(" in line or line.startswith(("}", "{", ".", "typedef")):
            continue
        if re.match(r"^[A-Za-z_][\w\s\*]*\s[\w\*]+(\[[^\]]*\])?\s*(=|;)", line):
            if "const" not in line and "extern" not in line:
                hits.append(f"L{k}: {line[:80]}")
    return hits


def analyze(files: dict) -> dict:
    """생성 산출물 {파일명: 본문} → 규칙 판정 + 함수 지표.

    돌려주는 dict:
      rules      [{key, title, status "pass"/"fail", hits[], note}]
      functions  [{file, name, line, lines, complexity}]
      totals     {files, lines, functions, max_complexity}
    """
    gen = {n: t for n, t in files.items() if n.endswith((".c", ".h"))}
    fn_rows, banned_hits, global_hits, all_fns = [], [], [], {}
    for name in sorted(gen):
        clean = strip_comments_strings(gen[name])
        for tok, why in BANNED.items():
            for m in re.finditer(rf"\b{tok}\b", clean):
                line = clean.count("\n", 0, m.start()) + 1
                banned_hits.append(f"{name}:L{line} {tok} — {why}")
        if name.endswith(".c"):
            for f in functions_of(gen[name]):
                fn_rows.append({
                    "file": name, "name": f["name"], "line": f["line"],
                    "lines": f["lines"], "complexity": cyclomatic(f["body"]),
                })
                all_fns[f["name"]] = f
            global_hits.extend(f"{name}:{h}" for h in _mutable_globals(gen[name]))
    recursion = _find_recursion(all_fns)

    def rule(key, title, hits, note=""):
        return {"key": key, "title": title, "hits": hits, "note": note,
                "status": "pass" if not hits else "fail"}

    rules = [
        rule("banned", "금지 구문·호출 없음 (goto·동적 메모리·I/O·float·재귀 유발류)",
             banned_hits,
             "생성기가 내지 않기로 한 것들 — MISRA C 대응 항목이되 준수 주장이 아니라 "
             "검사한 규칙만 말한다."),
        rule("recursion", "재귀 없음 (직·간접 콜그래프)", recursion,
             "스택 상한을 정적으로 셀 수 있는 전제 (DO-178C 스택 해석 논점)."),
        rule("globals", "가변 전역 없음 (파라미터는 const, 상태는 포인터 전달)",
             global_hits,
             "재진입·초기화 순서 문제의 원천 차단 — 상태 소유는 통합 계층 하나다."),
    ]
    return {
        "rules": rules,
        "functions": fn_rows,
        "totals": {
            "files": len(gen),
            "lines": sum(t.count("\n") for t in gen.values()),
            "functions": len(fn_rows),
            "max_complexity": max((f["complexity"] for f in fn_rows), default=0),
        },
    }
