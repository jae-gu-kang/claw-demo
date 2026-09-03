/** 코드 생성 패널 — 생성 코드(Python·C) + 검토·설명 (블록도 탭에서 호출).

수치·문자열 생성은 lib/codegen.js — 여기는 DOM 조립과 표시 상태만.
생성 텍스트는 반드시 textContent 경로로만 넣는다(fromMarkup은 정적 마크업 전용 계약).
스타일은 인라인 — app.css는 병행 세션 작업 중이라 건드리지 않는다 (커밋 오염 방지).
*/

import { api } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import {
  diffParams, genCHeader, genPython, genSnapshotC, genSnapshotPython, numDisplay,
  paramWarnings, specLabel, traceRows,
} from "../lib/codegen.js";
import {
  excludedSpecs, flightRequest, groupByRole, mergeFiles, pickFile, summarize,
} from "../lib/flightcode.js";
import { store } from "../store.js";

// 뷰는 라우팅마다 재생성되므로 표시 상태는 모듈 스코프 (views/gains.js fitCfg 관행)
const cfg = { lang: "python", verbose: false, traceOpen: false, file: null };

// 생성 응답 캐시 — 패널은 선택마다 다시 조립되지만 형상이 같으면 코드도 같다
const flightCache = { key: null, data: null };

const LANGS = [
  ["python", "Python", "설계 형상의 코드 표현 — 엔진에 그대로 붙여 실행 가능"],
  ["c", "C 헤더", "설계 형상의 코드 표현 — 파라미터 매크로"],
  ["flight", "탑재 코드", "FCC에 통합되어 그대로 실릴 제어법칙 코드 — 구조·로직·파라미터 전부"],
];

const PRE_STYLE = "font-family: var(--mono); font-size: 12px; line-height: 1.5;"
  + " white-space: pre; background: #f7f8fa; border: 1px solid var(--line);"
  + " border-radius: 6px; padding: 10px 12px; margin: 8px 0; max-height: 420px;"
  + " overflow: auto; -webkit-user-select: text; user-select: text;";

/** 코드 패널 렌더 — host를 비우고 다시 채운다.
specs: lib/codegen 스펙 배열 (1개면 단일 블록, 여러 개면 전체 형상 스냅샷)
meta: {generatedAt, server, engine} · validation: [{key, ok, detail}] · gainTables: store 값 */
export function renderCodePanel(host, {
  specs, meta, validation = [], gainTables = null, scheduleOff = null,
  langs = LANGS.map((l) => l[0]), flightMerged = false,
}) {
  // 어떤 형식 탭을 노출할지는 부르는 쪽이 정한다 — Autocode 탭은 종류(형상/탑재)를
  // 이미 위에서 고르게 하므로 여기서 다시 세 개를 늘어놓으면 선택지가 흩어진다.
  // 블록도의 블록별 패널은 인자를 안 주므로 예전처럼 셋 다 나온다
  const allow = LANGS.filter((l) => langs.includes(l[0]));
  if (!langs.includes(cfg.lang)) cfg.lang = allow[0][0];
  const snapshot = specs.length > 1 || gainTables != null;
  const pre = el("pre", { style: PRE_STYLE });
  const copyNote = el("span", { class: "hint" });
  const fileBar = el("div", { class: "row", style: "margin: 8px 0 0; flex-wrap: wrap" });

  // 탑재 C는 엔진이 생성한다(웹이 C를 조립하지 않는다) — 받아 둔 응답과 그 상태.
  // 게인 스케줄은 형상 전체의 것이라 스냅샷이 아니어도 적용값을 읽는다:
  // 스케줄 유무가 구조를 바꾸므로 빼면 실제와 다른 코드를 보여 주게 된다.
  const flight = { data: null, error: null, loading: false };
  const flightTables = () => gainTables ?? store.get("gainTables") ?? null;
  // 스케줄 자리를 전부 끈 상태는 테이블 dict로 표현할 수 없다 (lib/gainsched.js) —
  // 빈 dict는 서버가 막고, 생략하면 설계 기본으로 되돌아간다. 별도 신호로 읽는다
  const flightOff = () => scheduleOff ?? store.get("gainScheduleOff") ?? false;

  const build = () => {
    const opts = { verbose: cfg.verbose, meta };
    if (cfg.lang === "flight") return flightView();
    if (cfg.lang === "c") {
      return snapshot ? genSnapshotC(specs, gainTables, opts) : genCHeader(specs[0], opts);
    }
    return snapshot ? genSnapshotPython(specs, gainTables, opts) : genPython(specs[0], opts);
  };

  const flightView = () => {
    if (flight.loading) return { code: "탑재 코드 생성 중…", lineOf: null };
    if (flight.error) return { code: `생성 실패 — ${flight.error}`, lineOf: null };
    if (!flight.data) return { code: "", lineOf: null };
    if (flightMerged) return { code: mergeFiles(flight.data), lineOf: null, file: null };
    const file = pickFile(flight.data.files, cfg.file, flight.data.artifact);
    return { code: file ? file.text : "생성된 파일이 없습니다.", lineOf: null, file };
  };

  const loadFlight = async () => {
    // 통합↔모듈별 전환은 표시만 바뀌는 일이다 — 같은 형상이면 서버를 다시 부르지
    // 않는다. 요청 본문이 곧 형상이므로 그걸 키로 쓴다(값을 고치면 자동으로 무효화)
    const req = flightRequest(specs, flightTables(), { scheduleOff: flightOff() });
    const key = JSON.stringify(req);
    if (flightCache.key === key && flightCache.data) {
      flight.data = flightCache.data;
      paint();
      return;
    }
    flight.loading = true;
    flight.error = null;
    paint();
    try {
      flight.data = await api.post("/codegen/flight", req);
      flightCache.key = key;
      flightCache.data = flight.data;
    } catch (e) {
      flight.error = e && e.message ? e.message : String(e);
    } finally {
      flight.loading = false;
      paint();
    }
  };

  let current = build();
  const paint = () => {
    current = build();
    pre.textContent = current.code; // 마크업 삽입 없음
    clear(copyNote);
    langBtns.forEach((b) => b.classList.toggle("primary", b.dataset.lang === cfg.lang));
    clear(fileBar).append(...fileTabs(flight, current.file, (name) => {
      cfg.file = name;
      paint();
    }, flightMerged));
    // 검토도 다시 — float32 정밀도 지적은 C 탭에서만 성립한다
    clear(reviewHost).append(reviewBox(specs, validation, snapshot));
    // 추적성 표는 파라미터→코드 라인 대응이라 탑재 C에는 다른 대응이 필요하다
    clear(traceBox);
    if (current.lineOf) traceBox.append(traceTable(specs, current.lineOf, snapshot));
    clear(footHost).append(
      footNote(flight, specs, { tables: flightTables(), off: flightOff() }));
  };

  const langBtns = allow.map(([id, label, title]) => el("button", {
    "data-lang": id,
    title,
    onclick: () => {
      cfg.lang = id;
      // 응답을 받아 둔 뒤에는 다시 부르지 않는다 — 값이 바뀌면 패널을 다시 연다
      if (id === "flight" && !flight.data && !flight.loading) loadFlight();
      else paint();
    },
  }, label));

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(current.code);
      copyNote.textContent = "복사됨.";
    } catch {
      // 클립보드 차단(비보안 컨텍스트·권한 거부·API 부재) — 선택 상태로 만들고 단축키 안내.
      // 선택마저 실패해도 코드는 화면에 그대로 있으므로 안내만 바꾸고 넘어간다.
      try {
        const range = document.createRange();
        range.selectNodeContents(pre);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        copyNote.textContent = "클립보드 권한 없음 — 선택해 두었습니다. ⌘C(Ctrl+C)로 복사하세요.";
      } catch {
        copyNote.textContent = "클립보드를 쓸 수 없습니다 — 위 코드를 직접 선택해 복사하세요.";
      }
    }
  };

  const reviewHost = el("div");
  const traceBox = el("div");
  const footHost = el("div");
  clear(host).append(
    el("div", { class: "row", style: "margin-top: 12px" },
      // 형식 선택지가 하나뿐이면 줄을 만들지 않는다 — 고를 게 없는 버튼은 잡음이다
      ...(langBtns.length > 1 ? [el("span", { class: "hint" }, "형식"), ...langBtns] : []),
      el("button", { onclick: copy }, "복사"),
      el("label", { class: "field check", title: "설명·단위·허용범위를 코드 주석에 포함" },
        el("input", {
          type: "checkbox", checked: cfg.verbose,
          onchange: (ev) => { cfg.verbose = ev.target.checked; paint(); },
        }), "상세 주석"),
      copyNote,
    ),
    fileBar,
    pre,
    reviewHost,
    traceBox,
    footHost,
  );
  if (cfg.lang === "flight" && !flight.data && !flight.loading) loadFlight();
  else paint();
}

/** 탑재 C 파일 탭 — 서버가 정한 읽는 순서 그대로 (진입점 → 자료형 → 조립부 → …). */
function fileTabs(flight, selected, onPick, merged) {
  // 다른 탭으로 옮겨도 받아 둔 응답은 남는다 — 파일 탭까지 따라가면 안 된다
  if (cfg.lang !== "flight" || merged || !flight.data || flight.error) return [];
  const { count, lines } = summarize(flight.data.files);
  // 파일 16개를 한 줄에 늘어놓으면 무엇이 무엇인지 안 보인다 — 역할이 읽는 단위다
  const groups = groupByRole(flight.data.files).flatMap(({ role, files }) => [
    el("span", { class: "hint", style: "margin: 0 2px 0 10px" }, role),
    ...files.map((f) => el("button", {
      class: f.name === selected?.name ? "primary" : "",
      title: `${f.role} · ${f.lines}줄`,
      onclick: () => onPick(f.name),
    }, f.name)),
  ]);
  return [
    ...groups,
    el("span", { class: "hint", style: "margin-left: 10px" },
      selected ? `— ${selected.lines}줄 / 전체 ${count}개 ${lines}줄`
        : `${count}개 파일 ${lines}줄`),
  ];
}

/** 지금 어떤 게인 스케줄 형상으로 생성했는지 — 게인 탭의 적용값이 말없이 실리면
 * "게인 탭에서 적용을 눌렀더니 코드가 바뀌었다"가 원인 불명이 된다. */
function schedNote(tables, off) {
  if (off) {
    return el("p", { class: "hint" },
      "게인 스케줄 없음으로 생성됨 (게인 탭 적용값) — 전 게인이 설계점 상수이고 ",
      "스케줄 서브시스템이 코드에 없습니다.");
  }
  const names = tables ? Object.keys(tables) : [];
  if (names.length === 0) {
    return el("p", { class: "hint" },
      "게인 스케줄은 설계 기본 형상입니다 — 게인 탭에서 자리를 바꾸거나 값을 고쳐 ",
      "적용하면 여기 코드에 바로 반영됩니다.");
  }
  return el("p", { class: "hint" },
    `게인 탭 적용값으로 생성됨 — 스케줄 ${names.length}자리: ${names.join(" · ")}. `,
    "나머지 게인은 설계점 상수로 코드에 박힙니다.");
}

/** 탭별 안내 — 두 탭이 내는 물건이 근본적으로 다르므로 같은 문구를 쓸 수 없다. */
function footNote(flight, specs, sched) {
  if (cfg.lang !== "flight") {
    return el("p", { class: "hint" },
      "현재 설계 형상의 코드 표현입니다 — 로직이 아니라 파라미터만 생성합니다. ",
      "구조·블록 로직까지 담긴 것은 탑재 코드 쪽입니다. ",
      "Python 코드는 엔진에 그대로 붙여 실행할 수 있고, ",
      "조립(결선)은 서버 routes/sim.py::_build 가 정본입니다.");
  }
  const excluded = excludedSpecs(specs);
  const d = flight.data;
  return el("div", {},
    el("p", { class: "hint" },
      "FCC에 통합되어 그대로 실릴 제어법칙 코드입니다 (02 §1) — 구조·블록 로직·",
      "파라미터가 전부 들어 있고, 구조 정본인 IR에서 엔진이 생성합니다. ",
      d ? `형상 지문 ${d.fingerprint} · 제어주기 ${d.dt} s.` : "",
      " 커밋된 산출물 정본은 flight/gen/ 이며, 같은 형상이면 여기 코드와 바이트 단위로 같습니다."),
    schedNote(sched.tables, sched.off),
    excluded.length > 0 && el("p", { class: "hint" },
      "이 화면의 블록 중 탑재 C에 없는 것: ",
      excluded.map((x) => `${x.key} (${x.why})`).join(", "),
      ". 우리가 내는 것은 제어법칙 한 덩이이고 FCC 전체가 아닙니다."),
    el("p", { class: "hint" },
      "비트 일치는 부동소수 축약(FMA) 금지 등 빌드 조건에서만 성립합니다 — ",
      "조건은 진입점 헤더에 적혀 있고, 타깃에서의 확인(PIL)은 FCC팀 몫입니다."),
  );
}

/** 검토 패널 — 엔진 검증 결과 → 변경 Δ → 경고. */
function reviewBox(specs, validation, snapshot) {
  // 라벨은 specLabel — SCAS 3축처럼 같은 스키마가 여러 줄이면 key로는 구분이 안 된다
  const changes = specs.flatMap((s) =>
    diffParams(s.fields, s.values).map((d) => ({ ...d, key: specLabel(s) })));
  const warns = specs.flatMap((s) =>
    paramWarnings(s.fields, s.values, { lang: cfg.lang }).map((w) => ({ ...w, key: specLabel(s) })));

  return el("div", {},
    el("h4", { style: "margin: 14px 0 6px" }, "검토"),
    ...validation.map((v) => v.ok
      ? el("p", { class: "hint" },
          `엔진 검증 통과 — ${v.key}: 범위·타입에 더해 생성자 교차 조건까지 실제 엔진이 판정했습니다.`)
      : el("div", { class: "error-box" },
          `엔진 검증 실패 — ${v.key}: ${v.detail}\n`
          + "(코드는 입력한 값 그대로 생성했습니다 — 시뮬 실행 시 같은 사유로 422가 납니다.)")),
    el("h5", { style: "margin: 12px 0 4px" }, "기본값 대비 변경"),
    changes.length === 0
      ? el("p", { class: "hint" }, "엔진 기본값과 동일 — 변경된 파라미터가 없습니다.")
      : el("div", { class: "scroll-x" }, el("table", {},
          el("thead", {}, el("tr", {},
            snapshot && el("th", {}, "컴포넌트"),
            el("th", {}, "파라미터"), el("th", {}, "엔진 기본값"), el("th", {}, "현재값"),
            el("th", {}, "Δ"), el("th", {}, "단위"))),
          el("tbody", {}, changes.map((d) => el("tr", {},
            snapshot && el("td", {}, d.key),
            el("td", { class: "num" }, d.name),
            el("td", { class: "num" }, numDisplay(d.from)),
            el("td", { class: "num" }, numDisplay(d.to)),
            el("td", { class: "num" }, d.deltaPct == null ? "—" : `${fmt(d.deltaPct, 1)} %`),
            el("td", {}, d.unit && d.unit !== "-" ? d.unit : ""),
          ))))),
    el("h5", { style: "margin: 12px 0 4px" }, "주의"),
    warns.length === 0
      ? el("p", { class: "hint" }, "한계 근접·정밀도 관련 지적 사항 없음.")
      : el("ul", { class: "hint", style: "margin: 4px 0 0 18px" }, warns.map((w) =>
          el("li", {}, `${w.level === "warn" ? "⚠ " : "· "}${w.name}: ${w.text}`))),
  );
}

/** 추적성 표 — 요구·파라미터·코드 라인 대응 (SDD 등 산출물에 그대로 옮기는 표). */
function traceTable(specs, lineOf, snapshot) {
  const rows = traceRows(specs, lineOf, { prefixed: snapshot });
  return el("details", {
    open: cfg.traceOpen,
    ontoggle: (ev) => { cfg.traceOpen = ev.target.open; },
    style: "margin-top: 12px",
  },
    el("summary", {}, `추적성 체크리스트 (${rows.length}개 파라미터 → 코드 라인)`),
    el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {},
        ["파라미터", "값", "단위", "허용범위", "출처 스키마 @ 엔진 심볼", "코드 줄", "설명"]
          .map((h) => el("th", {}, h)))),
      el("tbody", {}, rows.map((r) => el("tr", {},
        el("td", { class: "num" }, r.param),
        el("td", { class: "num" }, r.value),
        el("td", {}, r.unit),
        el("td", { class: "num" }, r.range),
        el("td", { class: "num" }, r.source),
        el("td", { class: "num" }, r.line == null ? "—" : `L${r.line}`),
        el("td", { style: "text-align: left" }, r.desc),
      ))))),
    el("p", { class: "hint" },
      "출처 스키마는 엔진 레지스트리(02 §2.3), 엔진 심볼은 서버가 실제 인스턴스에서 회신한 ",
      "값입니다 — 클래스명을 추측하지 않으므로 엔진 개명 시에도 이 표가 어긋나지 않습니다."),
  );
}
