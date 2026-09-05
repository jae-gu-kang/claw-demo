/** 검증 탭의 순수 로직 — 요청 조립·판정 표시 모델. DOM·통신 없음.

views/verify.js가 소비한다. 뷰는 테스트 면제(.claude/verify-fleet-exempt.txt)라
판단이 드는 부분은 전부 여기 둔다.

**판정 문구의 정본은 엔진이다** (claw.verify.autocode `_summary` — coverage_gaps
관례). 여기 있는 것은 그 리포트를 화면 어휘(플래그 색·배지 수·머리줄)로 바꾸는
표시 판단뿐이고, 검사 내용을 다시 적지 않는다.
*/

import { BLOCKS, codegenTargets } from "./blocks.js";
import { flightRequest } from "./flightcode.js";

/** 현재 편집 형상 → POST /verify/flight 요청 본문.

    Autocode 탭과 같은 재료(BLOCKS·store 편집값·카탈로그 설계 kwargs)에서 같은 규칙
    (lib/flightcode.js flightRequest)으로 조립한다 — 다르게 조립하면 "화면에 보인
    코드"와 "검증한 코드"가 갈라진다. 검증 대상 선택이 따로 없는 이유이기도 하다:
    탑재코드는 형상 전체가 대상이다. */
export function buildVerifyRequest(storeGet, catalog, { tEnd = 180 } = {}) {
  const specs = BLOCKS
    .filter((b) => b.detail.editable && b.detail.codegen)
    .flatMap((b) => codegenTargets(b, storeGet(b.detail.injectKey), catalog?.scas_design)
      .map((t) => ({
        key: `${b.detail.schema.category}/${b.detail.schema.name}`,
        group: t.cg.group ?? null,
        values: t.values,
      })));
  const req = flightRequest(specs, storeGet("gainTables") ?? null, {
    scheduleOff: storeGet("gainScheduleOff") ?? false,
  });
  return { ...req, t_end: tEnd };
}

/** 요약 행 status → 판정 플래그 3-상태 (dom.js flagBadge의 어휘).

    "측정"은 통과가 아니다 — 커버리지 수치는 판정이 아니라 근거이고, 문턱을 정하는
    것은 사람 몫이다. 그래서 ok가 아니라 na 색으로 선다. */
export function statusFlag(status) {
  return {
    pass: { cls: "ok", label: "통과" },
    fail: { cls: "bad", label: "실패" },
    skip: { cls: "na", label: "생략" },
    info: { cls: "na", label: "측정" },
    measured: { cls: "na", label: "측정" },
  }[status] ?? { cls: "na", label: status ?? "—" };
}

/** 리포트 전체의 머리줄 판정 — 색·라벨·한 줄 사유. */
export function verdictModel(report) {
  if (!report) return null;
  const skips = (report.summary ?? []).filter((r) => r.status === "skip");
  if (report.verdict === "fail") {
    const fails = (report.summary ?? []).filter((r) => r.status === "fail");
    return {
      cls: "bad", label: "실패",
      line: `실패 ${fails.length}건 — ${fails.map((r) => (r.label ?? "").split(" — ")[0]).join(", ")}`,
    };
  }
  if (report.verdict === "pass_with_skips") {
    return {
      cls: "na", label: "통과 (생략 있음)",
      line: `실패 0건 · 생략 ${skips.length}건 — 이 환경에서 못 잰 것은 잰 척하지 않는다`,
    };
  }
  return { cls: "ok", label: "통과", line: "전 검사군 통과 · 생략 0건" };
}

/** 처음 실패한 요약 행의 key — 잡이 끝나면 그 상세 서랍을 열어 준다. 없으면 null. */
export function firstFailKey(report) {
  return (report?.summary ?? []).find((r) => r.status === "fail")?.key ?? null;
}

/** 서랍 배지 수 — 셀 수 없으면 null (badgeOf 규약: 0도 못 센 것도 배지 없음). */
export function failedRuleCount(report) {
  const rules = report?.static?.rules;
  return rules ? rules.filter((r) => r.status === "fail").length : null;
}

export function uncoveredBranchCount(report) {
  const cov = report?.coverage;
  return cov && cov.status === "measured" ? (cov.uncovered_branches ?? []).length : null;
}

export function mismatchedOutputCount(report) {
  const outs = report?.equivalence?.outputs;
  return outs ? outs.filter((o) => o.first_diff != null).length : null;
}

/** 백분율 표시 — null(측정 불가)은 0%로 위장하지 않는다. */
export function pct(x) {
  return x == null || !Number.isFinite(x) ? "—" : `${x.toFixed(1)}%`;
}

// ── VectorCAST식 표시 모델 — 유닛 그리드·커버리지 소스 뷰어·진리표·케이스 묶음 ──

/** 커버리지 칸 — "75.0% (6/8)". 잴 것이 없으면 0%가 아니라 —. */
export function covCell(k) {
  return k && k.count ? `${pct(k.percent)} (${k.covered}/${k.count})` : "—";
}

/** MC/DC 칸 — "측정+정당화/전체". 정당화는 측정과 구분해 보인다 (2+2/4). */
export function mcdcCell(m) {
  if (!m || !m.total) return "—";
  const j = m.justified ? `+${m.justified}` : "";
  return `${m.covered}${j}/${m.total}`;
}

/** 유닛 그리드 행 — 유닛(파티션·통합·런타임) × [TC, 라인, 분기, MC/DC, 상태].

    유닛 상태는 **케이스 판정**이다 — 커버리지는 정당화가 얽혀 유닛 단위 100%
    요구가 성립하지 않으므로(전체 판정은 요약 행 몫) 여기서 색을 정하지 않는다. */
export function unitGridRows(report) {
  return (report?.units ?? []).map((u) => {
    const cs = u.cases ?? { total: 0, passed: 0, skipped: 0 };
    const status = cs.total === 0 ? { cls: "na", label: "—" }
      : cs.passed === cs.total ? { cls: "ok", label: "통과" }
      : cs.passed + (cs.skipped ?? 0) === cs.total ? { cls: "na", label: "생략" }
      : { cls: "bad", label: "실패" };
    return {
      unit: u.unit, title: u.title, files: u.files ?? [],
      tc: cs.total ? `${cs.passed}/${cs.total}` : "—",
      lines: covCell(u.lines), branches: covCell(u.branches),
      mcdc: mcdcCell(u.mcdc), status,
    };
  });
}

/** 커버리지 소스 뷰어 행 — [{n, count, text, cls, dec}]. 파일이 없으면 null.

    cls: hit(실행) / miss(미실행) / part(실행됐지만 분기 한쪽 미달) /
    jus(미달이 전부 분석 정당화) / ""(비실행문 또는 커버리지 미측정 — 0으로
    위장하지 않는다). MC/DC 결정이 있는 줄은 dec가 실려 진리표를 연다. */
export function sourceRows(report, name) {
  const f = (report?.files ?? []).find((x) => x.name === name);
  if (!f) return null;
  const cov = (report?.coverage?.files ?? []).find((x) => x.name === name);
  const counts = new Map(cov?.line_counts ?? []);
  const miss = new Set((report?.coverage?.uncovered_branches ?? [])
    .filter((u) => u.file === name).map((u) => u.line));
  const jus = new Set((report?.coverage?.justified ?? [])
    .filter((u) => u.file === name).map((u) => u.line));
  const decs = new Map((report?.mcdc?.decisions ?? [])
    .filter((d) => d.file === name).map((d) => [d.line, d]));
  return f.text.split("\n").map((text, i) => {
    const n = i + 1;
    const count = counts.has(n) ? counts.get(n) : null;
    let cls = "";
    if (count === 0) cls = "miss";
    else if (miss.has(n)) cls = "part";
    else if (jus.has(n)) cls = "jus";
    else if (count > 0) cls = "hit";
    return { n, count, text, cls, dec: decs.get(n) ?? null };
  });
}

/** MC/DC 진리표 모델 — 실행이 남긴 벡터들과 독립쌍 참여 여부. */
export function truthTable(dec) {
  const pairMasks = new Set((dec.pairs ?? []).flat().filter((x) => x != null));
  const jus = new Set(dec.justified_cis ?? []);
  return {
    conds: dec.conditions.map((text, ci) => ({
      text, covered: !!(dec.covered ?? [])[ci], justified: jus.has(ci),
    })),
    rows: (dec.vectors ?? []).map((v) => ({
      cells: v.conds.map((c) => (c == null ? "–" : c ? "T" : "F")),
      outcome: v.outcome ? "T" : "F",
      inPair: pairMasks.has(v.mask),
    })),
    uncovered: dec.uncovered ?? [],
  };
}

/** 시험 케이스를 유닛 순서로 묶는다 — [{unit, title, cases}]. */
export function caseGroups(report) {
  const units = report?.units ?? [];
  const cases = report?.cases ?? [];
  const order = units.map((u) => u.unit);
  for (const c of cases) {
    if (!order.includes(c.unit)) order.push(c.unit);
  }
  const titles = new Map(units.map((u) => [u.unit, u.title]));
  return order.map((unit) => ({
    unit,
    title: titles.get(unit) ?? (unit === "fcl" ? "통합 (SIL)" : unit),
    cases: cases.filter((c) => c.unit === unit),
  }));
}
