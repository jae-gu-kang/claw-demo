/** 검증 탭 — DAL A 검증을 VectorCAST 문법으로 (M12).

이 탭에 온 사람의 주 질문은 하나다: **"이 코드를 믿어도 되나."**
판정판(대시보드)이 전면에, 유닛 그리드(파티션·통합·런타임 × TC·라인·분기·MC/DC)가
판독 시트에 늘 서고, 행을 누르면 **바로 아래에 커버리지 색칠 소스 뷰어**가 열린다
(마진 맵 칸→보드선도 드릴다운 선례). 다조건 결정 줄에는 MC/DC 진리표가 인라인으로
붙는다. 시험 케이스·대조·DO-178C 대응표·인쇄용 전체 보고서는 서랍이다.

검사는 서버 202 잡이다: 생성 → 정적 규율 → 엄격 컴파일 → 대조 미션(패리티와 같은
180 s) + 보강 벡터 + 유닛 시험 비트 대조 → 라인·분기·MC/DC 커버리지 → DAL A 판정.
**판정 문구·표는 전부 엔진이 낸다** — 화면은 리포트를 그릴 뿐이다. 요청 조립·표시
판단은 lib/verify.js(테스트).

검증 대상 선택이 없는 이유: 탑재코드는 형상 전체가 대상이다 (Autocode 탭과 같은
계약 — 같은 조립·같은 지문, 서버 테스트가 못박는다).
*/

import { api, errorText } from "../api.js";
import { clear, el, flagBadge } from "../dom.js";
import {
  buildVerifyRequest, caseGroups, covCell, failedRuleCount, firstFailKey,
  mcdcCell, mismatchedOutputCount, pct, sourceRows, statusFlag, truthTable,
  uncoveredBranchCount, unitGridRows, verdictModel,
} from "../lib/verify.js";
import { store } from "../store.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { createDrawers, drawerSection, tabStage, tabTop } from "./stage.js";

// 모듈 상태 — 탭 재진입 시 유지 (실행 중 작업 재부착 포함, 전 탭 관행)
let lastReport = null;
let runningJobId = null;
let openDrawer = null;
let selFile = null;   // 소스 뷰어에 열린 파일

const T_END = 180; // 대조 미션 길이 [s] — 패리티 테스트와 같은 정본 미션

let catalogCache = null; // /gains/catalog — 실패는 캐시하지 않는다 (autocode 관행)
async function gainsCatalog() {
  if (catalogCache === null) {
    try {
      catalogCache = await api.get("/gains/catalog");
    } catch {
      return null;
    }
  }
  return catalogCache || null;
}

/** 표 조립 헬퍼 — (머리, 행들). 괄호 미로는 사람이 진다. */
const table = (heads, rows) => el("div", { class: "scroll-x" }, el("table", {},
  el("thead", {}, el("tr", {}, heads.map((h) => el("th", {}, h)))),
  el("tbody", {}, rows)));

const chip = (f) => el("span", { class: `flag ${f.cls}` }, f.label);

export function render() {
  const boardBox = el("div");
  const gridBox = el("div");
  const viewerBox = el("div");
  const casesBox = el("div");
  const equivBox = el("div");
  const staticBox = el("div");
  const dalBox = el("div");
  const docBox = el("div");
  const progressBox = el("div");
  const errBox = el("div");
  const sheet = el("div", { class: "tab-sheet" }, gridBox, viewerBox);

  const runBtn = el("button", { class: "primary" }, "검증 실행");
  const syncRunBtn = () => {
    runBtn.disabled = !!runningJobId;
    clear(runBtn).append(runningJobId ? "검증 중…" : "검증 실행");
  };
  runBtn.onclick = () => run();

  const drawers = createDrawers({
    id: "verify-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "cases", label: "시험 케이스", group: "근거",
        title: "유닛·통합 시험 케이스별 판정 (VectorCAST 케이스 목록 대응)",
        count: () => {
          const cs = lastReport?.cases;
          return cs ? cs.filter((c) => c.status === "fail").length : null;
        },
        build: () => casesBox },
      { key: "equiv", label: "대조 상세", group: "근거",
        title: "출력별 비트 대조 · 대조가 밟은 경로",
        count: () => mismatchedOutputCount(lastReport),
        build: () => equivBox },
      { key: "static", label: "정적·컴파일 상세", group: "근거",
        title: "규칙별 지적 · 함수 지표 · 컴파일 경고",
        count: () => failedRuleCount(lastReport),
        build: () => staticBox },
      { key: "dal", label: "DO-178C 대응표", group: "증적",
        title: "목표별 자동/부분/범위 밖 — 조용한 누락 없이",
        build: () => dalBox },
      { key: "doc", label: "전체 보고서", group: "증적",
        title: "인쇄용 증적 문서 — 브라우저 인쇄로 PDF가 된다",
        build: () => docBox },
      { key: "about", label: "이 검증은 무엇인가", group: "설명",
        build: () => aboutBox() },
    ],
  });

  // 실패 요약 키 → 근거가 사는 가장 가까운 자리
  const drawerOf = (key) => (
    { static: "static", compile: "static", paths: "equiv", equiv: "equiv",
      coverage: "cases" }[key] ?? null);

  const paintViewer = () => renderViewer(viewerBox, lastReport, selFile, (name) => {
    selFile = name;
    paintViewer();
  });

  const paintResult = () => {
    sheet.style.display = lastReport ? "" : "none"; // 빈 시트는 빈 띠로 보인다
    renderBoard(boardBox, lastReport);
    renderGrid(gridBox, lastReport, (name) => {
      selFile = selFile === name ? null : name;
      paintViewer();
    });
    paintViewer();
    renderCases(casesBox, lastReport);
    renderEquiv(equivBox, lastReport);
    renderStatic(staticBox, lastReport);
    renderDal(dalBox, lastReport);
    renderDoc(docBox, lastReport);
    drawers.refresh();
    if (drawers.current()) drawers.repaint();
  };

  const run = async () => {
    if (runningJobId) return;
    clear(errBox);
    try {
      const req = buildVerifyRequest(store.get, await gainsCatalog(), { tEnd: T_END });
      const submitted = await api.post("/verify/flight", req);
      runningJobId = submitted.id;
      syncRunBtn();
      watch();
    } catch (e) {
      showError(errBox, e);
    }
  };

  const watch = () => attachProgress(progressBox, runningJobId, {
    onDone: async (job) => {
      runningJobId = null;
      syncRunBtn();
      try {
        if (job.status === "error") throw new Error(job.error);
        if (cancelledWithoutResult(job)) {
          showError(errBox, new Error("취소됨 — 반쪽 판정은 판정이 아니라 결과를 남기지 않습니다"));
          return;
        }
        const body = await api.get(`/results/${job.result_id}`);
        lastReport = body.report;
        selFile = firstMissFile(lastReport);
        paintResult();
        const open = drawerOf(firstFailKey(lastReport));
        if (open) drawers.open(open); // 실패의 근거가 사는 서랍부터
      } catch (e) {
        showError(errBox, e);
      }
    },
    onError: (e) => {
      runningJobId = null;
      syncRunBtn();
      showError(errBox, e);
    },
  });

  paintResult();
  syncRunBtn();
  if (runningJobId) watch(); // 재부착 — 실행 중 탭 이탈·재진입

  return el("div", { class: "tab-page" },
    tabTop({
      title: "검증",
      lead: "지금 편집 형상의 탑재 C를 실행으로 검증한다 — 정적 규율 → 엄격 컴파일 → "
        + `대조 미션 ${T_END}초 + 보강 벡터 + 유닛(파티션) 시험 비트 대조 → 라인·분기·`
        + "MC/DC → DAL A 판정. 판정 문구·DO-178C 표는 엔진이 낸다.",
      actions: runBtn,
      extra: [progressBox, errBox],
    }),
    tabStage(boardBox),
    sheet,
    drawers.root,
  );
}

function firstMissFile(report) {
  const u = report?.coverage?.uncovered_branches?.[0];
  return u ? u.file : null;
}

/** 전면 대시보드 — 판정 + 검사군 카드. 결과가 없으면 무엇이 그려질지 말한다. */
function renderBoard(box, report) {
  clear(box);
  if (!report) {
    box.append(el("p", { class: "hint" },
      "아직 실행하지 않았습니다 — [검증 실행]을 누르면 지금 형상(게인·AP·스케줄 편집 "
      + "반영)의 탑재 C를 생성해 정적·컴파일·유닛·통합 대조·커버리지를 돌리고, 판정판과 "
      + "유닛 그리드가 여기 섭니다. Autocode 탭이 보여 주는 코드와 같은 조립입니다."));
    return;
  }
  const v = verdictModel(report);
  box.append(
    el("div", { class: "vf-head" },
      el("span", { class: `flag ${v.cls} vf-verdict` }, `판정 — ${v.label}`),
      el("span", { class: "hint" }, v.line)),
    el("p", { class: "vf-ident hint" },
      `형상 지문 ${report.fingerprint} · 엔진 claw ${report.engine} · 제어주기 ${report.dt} s`
      + (report.steps ? ` · 통합 대조 ${report.steps.toLocaleString()}스텝` : "")),
    el("div", { class: "vf-cards" }, (report.summary ?? []).map((r) => {
      const f = statusFlag(r.status);
      const [name, sub] = r.label.split(" — ");
      return el("div", { class: "vf-card" },
        el("h3", {}, name, chip(f)),
        sub ? el("p", { class: "vf-sub" }, sub) : null,
        el("p", { class: "vf-detail" }, r.detail ?? ""));
    })),
  );
}

/** 유닛 그리드 — VectorCAST의 unit×coverage 표. 행 클릭 → 아래 소스 뷰어. */
function renderGrid(box, report, onPick) {
  clear(box);
  if (!report) return;
  const rows = unitGridRows(report).map((r) => el("tr", {
    class: "vf-unitrow",
    onclick: () => onPick(r.files.find((f) => f.endsWith(".c")) ?? r.files[0]),
  },
    el("td", { style: "text-align:left" },
      el("b", {}, r.unit), " ", el("span", { class: "hint" }, r.title)),
    el("td", { class: "num" }, r.files.join(" ")),
    el("td", { class: "num" }, r.tc),
    el("td", { class: "num" }, r.lines),
    el("td", { class: "num" }, r.branches),
    el("td", { class: "num" }, r.mcdc),
    el("td", {}, chip(r.status)),
  ));
  box.append(
    el("h2", { class: "vf-h" }, "유닛 그리드",
      el("span", { class: "hint" }, " — 행을 누르면 커버리지 소스가 아래 열립니다")),
    table(["유닛", "파일", "시험 TC", "라인", "분기", "MC/DC", "판정"], rows),
  );
}

/** 커버리지 소스 뷰어 — 실행 횟수 거터 + 줄 틴트 + MC/DC 진리표 인라인. */
function renderViewer(box, report, name, onPick) {
  clear(box);
  if (!report || !name) return;
  const rows = sourceRows(report, name);
  if (!rows) return;
  const fileBtns = (report.files ?? [])
    .filter((f) => f.name.endsWith(".c") || f.name === name)
    .map((f) => el("button", {
      class: `cv-tab${f.name === name ? "" : ""}`,
      "aria-selected": f.name === name ? "true" : "false",
      role: "tab", type: "button",
      onclick: () => onPick(f.name),
    }, f.name));
  const measured = report.coverage?.status === "measured";
  const body = rows.map((r) => {
    const kids = [el("div", { class: `vf-ln ${r.cls}` },
      el("span", { class: "vf-no" }, r.n),
      el("span", { class: "vf-cnt" },
        r.count == null ? "" : r.count.toLocaleString()),
      el("span", { class: "vf-codeln" }, r.text || " "))];
    if (r.dec) kids.push(truthTableBox(r.dec));
    return kids;
  });
  box.append(
    el("div", { class: "vf-viewer" },
      el("div", { class: "cv-tabs" }, fileBtns),
      measured
        ? el("p", { class: "hint", style: "margin:8px 2px" },
            "초록 = 실행 · 빨강 = 미실행 · 주황 = 분기 한쪽 미달 · 보라 = 분석 정당화 · ",
            "무색 = 비실행문. 거터 수치는 실행 횟수(통합+유닛 합산)입니다.")
        : el("p", { class: "hint", style: "margin:8px 2px" },
            "커버리지 미측정 — 소스만 표시합니다 (사유는 판정판의 커버리지 카드에)."),
      el("div", { class: "vf-src" }, body)),
  );
}

/** MC/DC 진리표 — 실행이 남긴 조건 벡터와 독립쌍 (VectorCAST의 MC/DC 뷰 대응). */
function truthTableBox(dec) {
  const t = truthTable(dec);
  const head = ["#", ...t.conds.map((_, i) => `c${i}`), "결과", "독립쌍"];
  const rows = t.rows.map((r, k) => el("tr", {},
    el("td", { class: "num" }, k + 1),
    r.cells.map((c) => el("td", { class: `num vf-tt-${c === "–" ? "x" : c}` }, c)),
    el("td", { class: "num" }, r.outcome),
    el("td", {}, r.inPair ? el("span", { class: "flag ok" }, "참여") : ""),
  ));
  return el("details", { class: "vf-tt", open: t.uncovered.some((u) => !u.justified) },
    el("summary", {}, `MC/DC 진리표 — ${dec.label} `,
      t.conds.every((c) => c.covered) ? el("span", { class: "flag ok" }, "전 조건")
        : t.uncovered.every((u) => u.justified)
          ? el("span", { class: "flag na" }, "정당화 포함")
          : el("span", { class: "flag bad" }, "미커버")),
    el("ol", { class: "hint vf-conds" }, t.conds.map((c, i) => el("li", {},
      el("code", {}, `c${i}: ${c.text}`), " ",
      c.covered ? el("span", { class: "flag ok" }, "독립쌍")
        : c.justified ? el("span", { class: "flag na" }, "분석 정당화")
          : el("span", { class: "flag bad" }, "미커버")))),
    table(head, rows),
    ...t.uncovered.map((u) => el("p", { class: "hint", style: "margin:6px 0 0" },
      `c${u.ci} ${u.justified ? "정당화" : "미커버"} — ${u.reason}`)),
  );
}

const emptyHint = (box) => clear(box).append(
  el("p", { class: "hint" }, "아직 결과가 없습니다 — [검증 실행] 후 채워집니다."));

function renderCases(box, report) {
  if (!report) return emptyHint(box);
  clear(box).append(
    el("p", { class: "hint", style: "margin:0 0 10px" },
      "케이스 = 결정적 입력 시퀀스 하나 (VectorCAST test case 대응). 기대값은 같은 IR의 "
      + "Python 실행이고 판정은 비트 일치다. 스텁·목은 없다 — 필요 없는 구조라서다"
      + " (파티션의 상류는 스텁이 아니라 임포트 값 그 자체)."),
    ...caseGroups(report).filter((g) => g.cases.length).map((g) =>
      drawerSection(`${g.unit} — ${g.title}`, null,
        table(["케이스", "목적", "스텝", "판정", "첫 불일치"], g.cases.map((c) => el("tr", {},
          el("td", { class: "num" }, c.id),
          el("td", { style: "text-align:left" }, c.title),
          el("td", { class: "num" }, c.steps.toLocaleString()),
          el("td", {}, flagBadge(c.status === "pass", "통과",
            c.status === "skip" ? "생략" : "불일치")),
          el("td", { class: "num" }, c.first_diff == null ? "—"
            : `스텝 ${c.first_diff.step} ${c.first_diff.output}: `
              + `C ${c.first_diff.c} vs Py ${c.first_diff.py}`)))))),
  );
}

function renderEquiv(box, report) {
  if (!report) return emptyHint(box);
  const eq = report.equivalence;
  const outRows = (eq?.outputs ?? []).map((o) => el("tr", {},
    el("td", { class: "num" }, o.name),
    el("td", { class: "num" }, o.steps.toLocaleString()),
    el("td", {}, flagBadge(o.first_diff == null, "전 스텝", "불일치")),
    el("td", { class: "num" },
      o.first_diff == null ? "0" : o.max_abs_err.toExponential(2)),
    el("td", { class: "num" }, o.first_diff == null ? "—"
      : `스텝 ${o.first_diff.step}: C ${o.first_diff.c} vs Py ${o.first_diff.py}`)));
  const pathRows = (report.exercised ?? []).map((r) => el("tr", {},
    el("td", { style: "text-align:left" }, r.title),
    el("td", {}, flagBadge(r.status === "pass", "밟음", "못 밟음")),
    el("td", { class: "num" }, r.detail)));
  clear(box).append(
    drawerSection("출력별 비트 대조 (통합 스트림)",
      "허용오차 없음 — 배정밀도·동일 연산 순서라 목표는 근사가 아니라 비트 일치다. "
      + "허용오차를 두면 진짜 어긋남이 그 아래 숨는다.",
      eq?.status === "skip"
        ? el("p", { class: "hint" }, eq.reason ?? "생략")
        // 실행 실패·행 수 불일치는 note에만 사유가 있다 — 안 그리면 빈 표만 남아
        // "왜 실패했는지"가 화면에서 사라진다 (rc·stderr가 여기 실린다)
        : [eq?.note ? el("div", { class: "error-box" }, eq.note) : null,
           outRows.length ? table(["출력", "스텝", "일치", "최대 |오차|", "첫 불일치"],
                                  outRows) : null]),
    drawerSection("대조 입력이 밟은 경로",
      "대조가 통과해도 그 경로를 안 밟았으면 의미가 없다 — 안 밟은 경로의 일치는 검증이 아니다.",
      table(["경로", "판정", "근거"], pathRows)),
  );
}

function renderStatic(box, report) {
  if (!report) return emptyHint(box);
  const st = report.static;
  const ruleRows = st.rules.map((r) => el("tr", {},
    el("td", { style: "text-align:left" }, r.title),
    el("td", {}, flagBadge(r.status === "pass", "통과", "위반")),
    el("td", { style: "text-align:left" }, r.hits.length
      ? el("ul", { class: "hint", style: "margin:0 0 0 16px" },
          r.hits.slice(0, 8).map((h) => el("li", { class: "vf-code" }, h)))
      : el("span", { class: "hint" }, r.note))));
  const fnRows = [...st.functions]
    .sort((a, b) => b.complexity - a.complexity)
    .map((f) => el("tr", {},
      el("td", { class: "num" }, f.file),
      el("td", { class: "num" }, f.name),
      el("td", { class: "num" }, f.lines),
      el("td", { class: "num" }, f.complexity)));
  clear(box).append(
    drawerSection("생성 코드 규율", "우리 생성기가 지키기로 한 규율이 산출물에서 지켜졌는가 — "
      + "MISRA 대응 항목이되 준수 주장이 아니라 검사한 규칙만 말한다.",
      table(["규칙", "판정", "지적"], ruleRows)),
    drawerSection("함수 지표", "복잡도 = 1 + 판정 지점(if·while·&&·||·?:) — 문턱 판정이 "
      + "아니라 리뷰 배분의 근거다.",
      table(["파일", "함수", "줄수", "복잡도"], fnRows)),
    drawerSection("엄격 컴파일", null, compileBody(report.compile)),
  );
}

function compileBody(comp) {
  if (!comp) return el("p", { class: "hint" }, "—");
  if (comp.status === "skip") return el("p", { class: "hint" }, comp.reason);
  const kids = [el("p", { class: "hint" },
    `${comp.cc} ${comp.flags.join(" ")} · 빌드 ${comp.builds}개(통합 + 유닛 하네스) · `
    + `경고 ${comp.warnings}건 · ` + (comp.ok ? "전부 성공" : "컴파일 실패"))];
  if (comp.log && (!comp.ok || comp.warnings > 0)) {
    kids.push(el("pre", { class: "vf-log" }, comp.log));
  }
  return kids;
}

const DAL_FLAG = {
  auto: { cls: "ok", label: "자동" },
  partial: { cls: "na", label: "부분" },
  out: { cls: "na", label: "범위 밖" },
  skip: { cls: "bad", label: "생략" },
};

function dalTable(report) {
  return table(["목표", "내용", "상태", "근거·사유"], (report.dal ?? []).map((r) => el("tr", {},
    el("td", { class: "num" }, r.ref),
    el("td", { style: "text-align:left" }, r.objective),
    el("td", {}, chip(DAL_FLAG[r.status] ?? { cls: "na", label: r.status })),
    el("td", { style: "text-align:left" }, el("span", { class: "hint" }, r.evidence)))));
}

function renderDal(box, report) {
  if (!report) return emptyHint(box);
  clear(box).append(
    el("p", { class: "hint", style: "margin:0 0 10px" },
      "DO-178C 목표별 이 도구의 자리 — 자동으로 채우는 것, 부분만 채우는 것, 범위 "
      + "밖(사유 명시)을 가른다. 조용한 누락이 없는 것이 이 표의 존재 이유다."),
    dalTable(report));
}

/** 전체 보고서 — 인쇄용 증적 문서. 목차는 8단 파이프라인 순서다. */
function renderDoc(box, report) {
  if (!report) return emptyHint(box);
  const v = verdictModel(report);
  const t = report.coverage?.totals;
  const mc = report.mcdc;
  const doc = el("div", { class: "vf-report" },
    el("h1", {}, "CLAW 탑재 C 검증 보고서"),
    el("p", { class: "vf-ident" },
      `산출물 ${report.artifact} · 형상 지문 ${report.fingerprint} · 엔진 claw `
      + `${report.engine} · 제어주기 ${report.dt} s · 대조 미션 ${report.t_end} s`),
    el("p", {}, el("span", { class: `flag ${v.cls} vf-verdict` }, `판정 — ${v.label}`),
      " ", el("span", { class: "hint" }, v.line)),

    el("h2", {}, "1. 요약"),
    table(["검사군", "판정", "근거"], (report.summary ?? []).map((r) => el("tr", {},
      el("td", { style: "text-align:left" }, r.label),
      el("td", {}, chip(statusFlag(r.status))),
      el("td", { style: "text-align:left" }, r.detail)))),

    el("h2", {}, "2. 구조 — 모델 → 검증된 IR → 생성 C"),
    el("p", { class: "hint" },
      "구조 정본은 IR 하나이고 Python 실행과 C 생성은 그 백엔드다. IR은 생성 "
      + "가능 제약(선언 순서 = 실행 순서, 대수 루프·죽은 코드·전방 참조 금지)을 "
      + "구성 시점에 강제한다 — 검사가 아니라 만들 수 없게 한다. "
      + `산출물 ${report.files.length}개 파일 · `
      + `${report.files.reduce((n, f) => n + f.lines, 0).toLocaleString()}줄.`),

    el("h2", {}, "3. 정적 — 규칙·결함·복잡도 (①~③)"),
    table(["규칙", "판정", "비고"], report.static.rules.map((r) => el("tr", {},
      el("td", { style: "text-align:left" }, r.title),
      el("td", {}, flagBadge(r.status === "pass", "통과", "위반")),
      el("td", { style: "text-align:left" }, el("span", { class: "hint" },
        r.hits.length ? r.hits.slice(0, 3).join(" · ") : r.note))))),
    el("p", { class: "hint" }, compileLine(report.compile)),

    el("h2", {}, "4. 유닛 시험·하네스 (④·⑤)"),
    el("p", { class: "hint" }, report.stubs?.note ?? ""),
    table(["유닛", "시험 TC", "라인", "분기", "MC/DC", "판정"],
      unitGridRows(report).map((r) => el("tr", {},
        el("td", { style: "text-align:left" }, `${r.unit} — ${r.title}`),
        el("td", { class: "num" }, r.tc),
        el("td", { class: "num" }, r.lines),
        el("td", { class: "num" }, r.branches),
        el("td", { class: "num" }, r.mcdc),
        el("td", {}, chip(r.status))))),
    ...caseGroups(report).filter((g) => g.cases.length).map((g) =>
      table([`${g.unit} 케이스`, "스텝", "판정"], g.cases.map((c) => el("tr", {},
        el("td", { style: "text-align:left" }, `${c.id} — ${c.title}`),
        el("td", { class: "num" }, c.steps.toLocaleString()),
        el("td", {}, flagBadge(c.status === "pass", "통과",
          c.status === "skip" ? "생략" : "불일치")))))),

    el("h2", {}, "5. 구조적 커버리지 (⑥)"),
    report.coverage?.status !== "measured"
      ? el("p", { class: "hint" }, `측정 생략 — ${report.coverage?.reason ?? ""}`)
      : el("div", {},
          el("p", { class: "hint" },
            `라인 ${pct(t.lines.percent)} (${t.lines.covered}/${t.lines.count}) · `
            + `분기 ${t.branches.covered}/${t.branches.count} `
            + `(+정당화 ${report.coverage.justified.length}) · `
            + `MC/DC 조건 ${mcdcCell(mc?.status === "measured"
                ? { total: mc.total, covered: mc.covered, justified: mc.justified }
                : null)} — 정당화는 측정 불가의 분석 대체이며 사유가 결정별로 남는다.`),
          table(["파일", "라인", "분기"], (report.coverage.files ?? []).map((f) => el("tr", {},
            el("td", { class: "num" }, f.name),
            el("td", { class: "num" }, covCell(f.lines)),
            el("td", { class: "num" }, covCell(f.branches))))),
          mcdcDocTables(mc),
          justifiedDoc(report.coverage)),

    el("h2", {}, "6. SIL 대조 (⑦) — PIL·타깃은 범위 밖"),
    el("p", { class: "hint" },
      "호스트에서 생성 C와 Python(IR)을 같은 입력으로 돌려 비트 단위로 대조했다. "
      + "타깃 보드 확인(PIL)과 소스↔오브젝트 추적성(⑧)은 이 도구 범위 밖이며 "
      + "생성 헤더의 빌드 조건 명시까지가 이쪽 몫이다."),
    table(["출력", "스텝", "판정"], (report.equivalence?.outputs ?? []).map((o) => el("tr", {},
      el("td", { class: "num" }, o.name),
      el("td", { class: "num" }, o.steps.toLocaleString()),
      el("td", {}, flagBadge(o.first_diff == null, "비트 일치", "불일치"))))),

    el("h2", {}, "7. DO-178C 목표 대응"),
    dalTable(report),
  );

  const printBtn = el("button", {
    onclick: () => {
      // 보고서만 인쇄 — 사본을 전용 오버레이로 띄우고 인쇄 후 걷는다
      const clone = doc.cloneNode(true);
      clone.querySelectorAll("details").forEach((d) => { d.open = true; });
      const overlay = el("div", { class: "vf-printonly" }, clone);
      document.body.append(overlay);
      document.body.classList.add("vf-printing");
      const done = () => {
        overlay.remove();
        document.body.classList.remove("vf-printing");
        window.removeEventListener("afterprint", done);
      };
      window.addEventListener("afterprint", done);
      window.print();
    },
  }, "인쇄 (PDF 저장)");
  clear(box).append(
    el("div", { class: "row", style: "margin-bottom:10px" }, printBtn,
      el("span", { class: "hint" },
        "저장된 결과 JSON이 소스까지 동봉한 자립 증적이라, 결과 탭에서 다시 열어도 같은 보고서가 나옵니다.")),
    doc);
}

function compileLine(comp) {
  if (!comp) return "";
  if (comp.status === "skip") return `엄격 컴파일 생략 — ${comp.reason}`;
  return `엄격 컴파일: ${comp.cc} ${comp.flags.join(" ")} · 빌드 ${comp.builds}개 · `
    + `경고 ${comp.warnings}건.`;
}

function mcdcDocTables(mc) {
  if (mc?.status !== "measured") return null;
  return el("div", {}, mc.decisions.map((d) => el("div", { class: "vf-doc-tt" },
    el("p", { class: "hint", style: "margin:10px 0 4px" },
      `${d.file}:L${d.line} — ${d.label} (${d.kind === "guard" ? "안티와인드업 가드" : "구간 스캔 루프"})`),
    truthTableBox(d))));
}

function justifiedDoc(cov) {
  if (!cov?.justified?.length) return null;
  return drawerSection("분석 정당화된 분기", null,
    table(["파일", "줄", "미실행", "코드"], cov.justified.map((u) => el("tr", {},
      el("td", { class: "num" }, u.file),
      el("td", { class: "num" }, `L${u.line}`),
      el("td", {}, u.missing),
      el("td", { class: "vf-code", style: "text-align:left" }, u.text)))));
}

function aboutBox() {
  return el("div", {},
    el("p", { class: "hint", style: "max-width:96ch" },
      "이 탭은 자체 검증 엔진이다 — 개발 중 반복 검증을 자동화해 그 80~90%를 여기서 "
      + "끝내는 자리이고, 화면 문법은 VectorCAST의 것(유닛 그리드·커버리지 소스 뷰어·"
      + "MC/DC 진리표·시험 케이스·증적 보고서)을 따른다. 대조 미션은 패리티 테스트와 "
      + "같은 180초 정본이고, 보강 벡터와 유닛(파티션) 시험이 미션이 못 밟는 방향을 "
      + "닫는다. 스텁·목 자동 생성이 없는 이유는 못 만들어서가 아니라 필요 없어서다 — "
      + "생성 법칙은 외부 의존이 0이라 파티션의 상류가 곧 임포트 값이다."),
    el("p", { class: "hint", style: "max-width:96ch" },
      "MC/DC는 생성 C를 직접 계측해 잰다 — 커버리지 빌드 사본의 다조건 결정에 기록 "
      + "프로브를 심고(줄 번호 보존), 실행이 남긴 진리 벡터에서 masking MC/DC 독립쌍을 "
      + "판정한다. 계측이 결과를 한 비트라도 바꾸면 그 측정은 버린다(무해성 자기검사). "
      + "단일 조건 결정은 MC/DC ≡ 분기 커버리지라 llvm 분기 데이터가 충족을 판정한다. "
      + "독립쌍이 수학적으로 존재하지 않는 조건(적분 클램프 불변식에 종속된 가드)은 "
      + "측정 대신 분석 정당화로 남고 그 사유가 결정별로 기록된다 — DO-178C가 허용하는 "
      + "커버 대체이고, 숨기는 것과 다르다.",),
    el("p", { class: "hint", style: "max-width:96ch" },
      "말하지 않는 것도 분명히 한다. 이 결과는 DO-330 도구 적격성 증거가 아니다 — 이 "
      + "검증기 자체가 틀리지 않는다는 입증은 별개 사업이고, 인증용 독립 검증은 적격성 "
      + "키트를 갖춘 상용 도구(LDRA·VectorCAST류)의 자리다. 비트 일치는 개발 머신 빌드 "
      + "조건에서의 결과다 — 타깃 확인(PIL)과 소스↔오브젝트 추적성은 FCC팀 몫으로 "
      + "남고, DO-178C 대응표가 그 경계를 목표별로 명시한다. 컴파일러·커버리지 툴이 "
      + "없는 배포에서는 해당 검사가 사유와 함께 생략으로 남는다 — 못 잰 것을 잰 척하지 "
      + "않는다."),
  );
}

function showError(errBox, e) {
  clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
}
