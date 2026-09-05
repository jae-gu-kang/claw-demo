"""MC/DC 자체 계측 — 생성 C의 다조건 결정에 프로브를 심어 진리 벡터를 수집한다 (M12).

이 툴체인(llvm 14)은 분기 커버리지까지만 낸다(-fcoverage-mcdc는 LLVM 18+).
DAL A의 MC/DC는 여기서 직접 잰다 — **측정 대상은 생성 C 그 자체다**: 커버리지
빌드의 사본에서 결정의 원자 조건을 기록 매크로로 감싸고, 실행이 남긴 진리 벡터
집합에서 masking MC/DC를 판정한다.

대상은 **다조건 결정뿐**이다. 단일 조건 결정(enable if·시드 if·3항·wrap_pi)은
MC/DC ≡ 분기 커버리지라(조건이 하나면 "그 조건이 홀로 결과를 바꿈" = 양방향
실행) llvm 분기 데이터가 이미 충족을 판정한다 — 그 등가성은 교과서적 사실이고
리포트가 명기한다. 에미터가 내는 다조건 형태는 둘뿐이다:

  GUARD  if ((c0 && c1) || (c2 && c3)) {      — PID 조건부 적분 가드
  AND2   while (c0 && c1) { …                 — 룩업·다항 구간 스캔

**변환은 줄을 보존한다** — 감싸기는 줄 안에서 끝나므로 llvm 라인·분기 좌표가
평문 산출물과 1:1로 남는다. 매크로 삽입 파일(claw_mcdc.h)은 `#include`가 아니라
`-include` 플래그로 공급한다(줄 번호 불변). 패턴을 못 찾으면 시끄럽게 실패한다 —
에미터가 바뀌었다는 뜻이고, 조용한 미측정이 최악이다.

단락(short-circuit)에서 평가되지 않은 조건은 벡터에 "평가 안 됨"으로 남고,
독립쌍 판정은 **두 벡터 모두에서 평가된 다른 조건들이 같을 것**만 요구한다 —
단락 의미론에서의 masking MC/DC 판정이다.
"""

import re

# 결정 id 상한 — 런타임 배열 크기와 같아야 한다 (claw_mcdc.c)
MAX_DECISIONS = 64

_GUARD = re.compile(
    r"^(?P<ind>\s*)if \(\((?P<c0>[^()]+?) && (?P<c1>[^()]+?)\)"
    r" \|\| \((?P<c2>[^()]+?) && (?P<c3>[^()]+?)\)\) \{$"
)
_AND2 = re.compile(
    r"^(?P<ind>\s*)while \((?P<c0>[^()]+?) && (?P<c1>[^()]+?)\) \{(?P<tail>.*)$"
)

RUNTIME_H = """/* CLAW MC/DC 계측 런타임 — 커버리지 빌드 전용 (-include로 공급, 탑재물 아님). */
#ifndef CLAW_MCDC_H
#define CLAW_MCDC_H
#define CLAW_MCDC_ENABLED 1
int claw_mcdc_rec(int did, int ci, int v);
void claw_mcdc_dump(void);
#define CLAW_MCDC(did, ci, expr) claw_mcdc_rec((did), (ci), (expr))
#endif /* CLAW_MCDC_H */
"""

RUNTIME_C = """/* CLAW MC/DC 계측 런타임 — 결정별 진리 벡터(값 4비트 + 평가됨 4비트) 집합 수집.
 * 좌단 조건(ci==0)은 단락과 무관하게 항상 먼저 평가되므로, ci==0 진입이 곧
 * "직전 평가 벡터 확정" 신호다. 남은 마지막 벡터는 dump가 확정한다. */
#include <stdio.h>

int claw_mcdc_rec(int did, int ci, int v);
void claw_mcdc_dump(void);

#define CLAW_MCDC_MAX %d
static unsigned char claw_mcdc_cur[CLAW_MCDC_MAX];
static unsigned char claw_mcdc_seen[CLAW_MCDC_MAX][256];
static unsigned char claw_mcdc_used[CLAW_MCDC_MAX];

int claw_mcdc_rec(int did, int ci, int v)
{
    if (ci == 0) {
        if (claw_mcdc_cur[did]) { claw_mcdc_seen[did][claw_mcdc_cur[did]] = 1; }
        claw_mcdc_cur[did] = 0;
        claw_mcdc_used[did] = 1;
    }
    claw_mcdc_cur[did] |= (unsigned char)(((v ? 1 : 0) << ci) | (1 << (ci + 4)));
    return v;
}

void claw_mcdc_dump(void)
{
    int d, m;
    for (d = 0; d < CLAW_MCDC_MAX; d++) {
        if (!claw_mcdc_used[d]) { continue; }
        if (claw_mcdc_cur[d]) {
            claw_mcdc_seen[d][claw_mcdc_cur[d]] = 1;
            claw_mcdc_cur[d] = 0;
        }
        printf("MCDC %%d", d);
        for (m = 1; m < 256; m++) {
            if (claw_mcdc_seen[d][m]) { printf(" %%02x", m); }
        }
        printf("\\n");
    }
}
""" % MAX_DECISIONS


#: 다조건 결정을 만드는 C 연산자 — 이 중 하나라도 있는 줄은 인벤토리에 잡혀야 한다
_MULTI = re.compile(r"&&|\|\|")


def find_decisions(files) -> list:
    """생성 산출물에서 다조건 결정 추출 — [{id, file, line, kind, conditions, label}].

    순서는 (파일명, 줄) 사전순으로 못박는다 — id가 곧 계측 배열 첨자라 결정적이어야
    실행 간 병합이 가능하다.

    **놓친 결정은 조용히 사라지지 않는다.** 인벤토리에서 빠지면 분모에도 안 들어가
    MC/DC가 100%로 남는다 — 측정 누락이 만점으로 보이는 최악의 실패다. 그래서
    `&&`·`||`가 있는 줄을 세어 두 패턴이 전부 잡았는지 대조하고, 못 잡은 줄이
    하나라도 있으면 시끄럽게 터진다(에미터가 새 형태를 내기 시작했다는 뜻).
    """
    out, unmatched = [], []
    for name in sorted(n for n in files if n.endswith(".c")):
        for lineno, text in enumerate(files[name].split("\n"), start=1):
            m = _GUARD.match(text)
            if m:
                conds = [m.group(k).strip() for k in ("c0", "c1", "c2", "c3")]
                out.append({"file": name, "line": lineno, "kind": "guard",
                            "conditions": conds, "label": conds[0].split()[0]})
                continue
            m = _AND2.match(text)
            if m:
                conds = [m.group(k).strip() for k in ("c0", "c1")]
                out.append({"file": name, "line": lineno, "kind": "and2",
                            "conditions": conds, "label": conds[1].split()[0]})
                continue
            # 주석은 제외한다 — 설명문의 `&&`가 결정은 아니다
            code = text.split("/*", 1)[0]
            if _MULTI.search(code):
                unmatched.append(f"{name}:L{lineno} {code.strip()[:100]}")
    if unmatched:
        raise ValueError(
            "인벤토리가 못 잡은 다조건 줄 — MC/DC 분모가 조용히 줄어든다:\n  "
            + "\n  ".join(unmatched[:10]))
    for i, d in enumerate(out):
        d["id"] = i
    if len(out) > MAX_DECISIONS:
        raise ValueError(f"다조건 결정 {len(out)}개 > 계측 상한 {MAX_DECISIONS}")
    return out


def instrument(files, decisions) -> dict:
    """결정 줄의 원자 조건을 CLAW_MCDC로 감싼 사본 — **줄 수·줄 번호 보존**.

    대상 줄이 예상 패턴과 다르면 ValueError — 인벤토리와 사본이 어긋난 채 계측되는
    것(엉뚱한 결정에 기록)이 최악이라 조용히 건너뛰지 않는다.
    """
    by_file = {}
    for d in decisions:
        by_file.setdefault(d["file"], []).append(d)
    out = dict(files)
    for name, decs in by_file.items():
        lines = files[name].split("\n")
        for d in decs:
            text = lines[d["line"] - 1]
            wrap = [f"CLAW_MCDC({d['id']}, {k}, ({c}))"
                    for k, c in enumerate(d["conditions"])]
            if d["kind"] == "guard":
                m = _GUARD.match(text)
                if not m:
                    raise ValueError(f"{name}:{d['line']} 가드 패턴 불일치: {text!r}")
                new = (f"{m.group('ind')}if (({wrap[0]} && {wrap[1]})"
                       f" || ({wrap[2]} && {wrap[3]})) {{")
            else:
                m = _AND2.match(text)
                if not m:
                    raise ValueError(f"{name}:{d['line']} 루프 패턴 불일치: {text!r}")
                new = (f"{m.group('ind')}while ({wrap[0]} && {wrap[1]})"
                       f" {{{m.group('tail')}")
            lines[d["line"] - 1] = new
        out[name] = "\n".join(lines)
    return out


def parse_dump(text) -> dict:
    """실행 stdout에서 MCDC 줄만 → {결정 id: set(벡터 바이트)}. 여러 실행분 병합용."""
    seen = {}
    for line in text.splitlines():
        if not line.startswith("MCDC "):
            continue
        parts = line.split()
        did = int(parts[1])
        seen.setdefault(did, set()).update(int(h, 16) for h in parts[2:])
    return seen


def merge_dumps(dumps) -> dict:
    """실행 여러 번(통합 + 유닛들)의 덤프 합집합 — 결정 id는 인벤토리로 고정돼 있다."""
    merged = {}
    for d in dumps:
        for did, vecs in d.items():
            merged.setdefault(did, set()).update(vecs)
    return merged


def _bits(mask, n):
    """벡터 바이트 → 조건별 (평가됨, 값). 평가 안 된 조건의 값 비트는 None."""
    out = []
    for ci in range(n):
        ev = bool(mask & (1 << (ci + 4)))
        out.append((ev, bool(mask & (1 << ci)) if ev else None))
    return out


def _outcome(kind, vals):
    """벡터의 결정 결과 — 단락 의미론 그대로 (평가 안 된 조건은 결과에 못 닿는다)."""
    if kind == "and2":
        c0, c1 = vals[0][1], vals[1][1]
        return bool(c0 and c1)
    c0, c1, c2, c3 = (v[1] for v in vals)
    if c0 and c1:
        return True
    return bool(c2 and c3)


def judge(decisions, seen, justified=None) -> dict:
    """masking MC/DC 판정 → {decisions: [...], covered, justified, total, percent}.

    조건 i의 독립쌍: 두 벡터 모두에서 i가 평가되고 값이 다르며, 결과가 다르고,
    **둘 다에서 평가된 다른 조건들의 값이 같다** — 단락 의미론의 masking 판정.

    justified={결정 id: {"cis": (...), "reason": 문구}} — 독립쌍이 **수학적으로
    존재하지 않는** 조건의 분석 정당화(DO-178C가 허용하는 커버 대체). 측정으로
    이미 커버된 조건에는 적용하지 않는다 — 정당화는 측정의 대체이지 장식이 아니다.
    """
    justified = justified or {}
    rows, n_cov, n_jus, n_tot = [], 0, 0, 0
    for d in decisions:
        n = len(d["conditions"])
        masks = sorted(seen.get(d["id"], set()))
        vecs = []
        for mask in masks:
            vals = _bits(mask, n)
            vecs.append({"mask": mask,
                         "conds": [v[1] for v in vals],
                         "outcome": _outcome(d["kind"], vals)})
        covered, pairs, uncovered, jus_cis = [], [], [], []
        for ci in range(n):
            pair = None
            for a in vecs:
                if a["conds"][ci] is None:
                    continue
                for b in vecs:
                    if b["conds"][ci] is None or a["conds"][ci] == b["conds"][ci]:
                        continue
                    if a["outcome"] == b["outcome"]:
                        continue
                    if all(a["conds"][j] == b["conds"][j]
                           for j in range(n)
                           if j != ci and a["conds"][j] is not None
                           and b["conds"][j] is not None):
                        pair = [a["mask"], b["mask"]]
                        break
                if pair:
                    break
            ok = pair is not None
            covered.append(ok)
            pairs.append(pair)
            jus = justified.get(d["id"], {})
            if not ok and ci in jus.get("cis", ()):
                jus_cis.append(ci)
                uncovered.append({"ci": ci, "text": d["conditions"][ci],
                                  "justified": True, "reason": jus["reason"]})
            elif not ok:
                vals_seen = {v["conds"][ci] for v in vecs} - {None}
                reason = ("평가된 적 없음" if not vals_seen
                          else "참이 된 적 없음" if True not in vals_seen
                          else "거짓이 된 적 없음" if False not in vals_seen
                          else "독립쌍 없음 — 다른 조건이 함께 움직였다")
                uncovered.append({"ci": ci, "text": d["conditions"][ci],
                                  "justified": False, "reason": reason})
        n_tot += n
        n_cov += sum(covered)
        n_jus += len(jus_cis)
        rows.append({**{k: d[k] for k in ("id", "file", "line", "kind",
                                          "conditions", "label")},
                     "vectors": vecs, "covered": covered, "pairs": pairs,
                     "justified_cis": jus_cis, "uncovered": uncovered})
    return {
        "decisions": rows,
        "covered": n_cov,
        "justified": n_jus,
        "total": n_tot,
        "percent": (100.0 * (n_cov + n_jus) / n_tot) if n_tot else None,
    }
