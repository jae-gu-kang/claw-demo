/** 기체 탭 (02 §8 0단계) — 기체 프로파일 목록·선택·복제·편집·내보내기/가져오기 (06 §8).

모든 탭의 계산이 **헤더에서 고른 기체**를 쓴다(lib/profile.js가 요청마다 싣는다). 이 탭은 그 기체
문서를 만들고 고치는 자리다. 문서는 서버가 검증해 리비전으로 쌓는다(02 §5.6) — 검증 규칙을 여기서
다시 적지 않는다: [검증]은 서버 `/profiles/validate`(저장과 같은 규칙)의 답을 경로째 보여 줄 뿐이다.

배치(06 §2): **대표 그림과 목록이 전면**이고 문서·형상 변형·가져오기는 패널이다. 대표 그림은 지금 계산에 쓰는
기체를 크게 제자리에서 돌리고, ‹ ›로 목록의 다른 기체·형상 변형을 그 자리에서 미리 본다 — three는 가상환경 번들에만
있어 그 번들의 두 번째 진입점을 부른다(lib/aircrafthero.js). 문서 패널은 절별 폼(views/profileform.js)과
JSON 글이 같은 문서를 고친다.

예제 기체는 엔진 패키지 데이터라 읽기 전용이다. 보여 주되 검증을 부르지 않는다(검증은 저장 규칙이라
예제 표시를 거부한다) — 고치려면 복제한다.
*/

import { ApiError, api, errorText } from "../api.js";
import { heroEntries, heroFacts, heroPlan, stepIndex, variantNote } from "../lib/aircrafthero.js";
import { clear, el } from "../dom.js";
import {
  EXAMPLE_ID, cloneDocument, currentSelection, exportFileName, parseDocumentText, profileErrorText,
  sameSelection, saveSelection, setSelection,
} from "../lib/profile.js";
import { effectiveOf, formUpdate, sliceBody, stallNote } from "../lib/profileform.js";
import { lineChartCanvas } from "./plots.js";
import { renderProfileForm } from "./profileform.js";
import {
  browserStorage, refresh as refreshPicker, restoredNotice, selectedDocument, switchTo,
} from "./profilepick.js";
import { createDrawers, drawerSection, tabStage, tabTop } from "./stage.js";
import { deriveSummary, deTrimStatus, designSource, seedSummary } from "../lib/quickseed.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";

// 탭 재진입에도 목록·열어 둔 문서·편집 중 글·열린 패널 유지 (모듈 스코프 규약)
let list = null;
let volatile = false;
let opened = null; // {id, body: GET·PUT 응답, text: 편집 중 글, dirty, check: {ok, lines}|null, conflict: 최신 리비전|null}
let openDrawer = null;
let importText = "";
// 절별 폼 서술(엔진 claw.profile.form)·예제 문서(비어 있던 묶음을 만들 때만)·레지스트리 스키마 — 한 번 받는다
let formSpec = null;
let formAssets = null; // 진행 중인 요청 — 다시 그리기가 겹쳐도 한 번만 받는다
let exampleDoc = null;
const schemaCache = new Map();
// 공력 DB 뷰어 칸·마지막 곡선 — 탭을 떠났다 와도 그대로 (곡선은 그린 기체·문서의 것임을 forId로 대조한다)
const viewer = {
  along: "alpha", start: "-0.2", stop: "0.6", n: "81", coef: "CL",
  fixed: { alpha: "0", beta: "0", mach: "0.5", alt: "0", de: "0", da: "0", dr: "0" },
  result: null, forId: null, error: null,
};
const AXIS_UNIT = { alpha: "rad", beta: "rad", de: "rad", da: "rad", dr: "rad", mach: "", alt: "m" };
// 기체를 고치는 잡(초기 게인 탐색·δe_trim 도출) — 도는 잡(탭을 떠났다 와도 진행바를 다시 붙인다)·마지막 결과·
// 시뮬 확인 체크. 한 번에 하나만 돈다(둘 다 같은 기준 리비전 위에 쓰므로 나중 것이 충돌한다)
let seedJob = null; // {id, profileId, kind: "quick_seed"|"derive_de_trim"}
let seedResult = null; // {profileId, kind, body}
let seedSimCheck = false;
// 대표 그림 — 가상환경 번들(three)의 두 번째 진입점을 쓴다. 떠날 때 WebGL 컨텍스트를 반납한다(main.js dispose 규약)
const BUNDLE = "/world/build/world.js";
let hero = null; // {session, handle} — 늦게 도착한 문서·번들이 떠난 화면에 렌더러를 만들지 않게 세션으로 대조한다
let heroPick = null; // ‹ ›로 옮겨 보고 있는 {id, variant} — null이면 지금 계산에 쓰는 기체. 탭을 떠났다 와도 유지
const heroDocs = new Map(); // 기체 id → 문서 받기 약속 — 오갈 때마다 다시 받지 않는다(목록을 다시 받으면 비운다)
const AP_SOURCE = { heuristic: "휴리스틱", registry_default: "레지스트리 기본값", document: "문서 값",
  structural_limit: "구조 한계로 깎음" };

const failText = (e) => (e instanceof ApiError && profileErrorText(e.detail)) || errorText(e);
const path = (id) => `/profiles/${encodeURIComponent(id)}`;
const fresh = (body) => ({
  id: body.document.id, body, text: JSON.stringify(body.document, null, 1),
  obj: JSON.parse(JSON.stringify(body.document)), // 폼이 고치는 문서 — 고칠 때마다 text와 맞춘다
  mode: "form", editVariant: null, formError: null,
  dirty: false, check: null, conflict: null,
});
// 지금 계산에 쓰이는 기체 id — 고르지 않았으면 예제
const selectedId = () => currentSelection()?.id ?? EXAMPLE_ID;

export function dispose() {
  if (hero == null) return;
  const handle = hero.handle;
  hero = null; // 진행 중인 받기가 스스로 물러나도록 먼저 끊는다
  handle?.dispose?.();
}

export function render() {
  dispose(); // 같은 뷰를 다시 그리면 main.js가 dispose를 부르지 않는다 — 옛 렌더러를 여기서 놓는다
  const heroBox = el("div", { class: "hero-block" });
  const statusLine = el("p", { class: "hint", style: "margin:4px 0 0" });
  const errBox = el("div");
  const noticeBox = el("div");
  const listBox = el("div");
  const docBox = el("div");
  const variantBox = el("div");
  const viewerBox = el("div");
  const seedBox = el("div");
  const importBox = el("div");

  const showError = (e) => clear(errBox).append(
    el("div", { class: "error-box" }, typeof e === "string" ? e : failText(e)));

  const paintNotices = () => {
    const restored = restoredNotice();
    // 네이티브 append는 null을 글자 "null"로 넣는다(el()과 다르다) — 없는 알림은 목록에서 뺀다
    clear(noticeBox).append(...[
      restored ? el("p", { class: "notice" }, restored) : null,
      volatile
        ? el("p", { class: "notice" },
          "이 서버는 기체 저장소가 재시작마다 비워집니다(공개 데모) — 저장한 기체는 재배포·절전 복귀 때 "
          + "사라집니다. 남겨야 할 기체는 [내보내기]로 JSON을 받아 두고 「가져오기」 패널로 되살립니다. "
          + "예제 기체는 사라지지 않습니다.")
        : null,
    ].filter(Boolean));
  };

  const load = async () => {
    clear(errBox);
    statusLine.textContent = "불러오는 중…";
    try {
      const [items, health] = await Promise.all([
        api.get("/profiles"), api.get("/health").catch(() => null)]);
      list = items;
      volatile = !!health?.profile_store?.volatile;
      statusLine.textContent = ""; // 무엇으로 계산하나는 대표 그림 캡션·목록·헤더가 말한다 — 머리줄에 겹쳐 적지 않는다
      paintNotices();
      paintList();
      drawers.refresh();
      heroDocs.clear(); // 저장·삭제 뒤의 새 리비전을 대표 그림도 보게
      heroNav();
    } catch (e) {
      statusLine.textContent = "";
      showError(e);
    }
  };

  // ── 목록 (전면) ──────────────────────────────────────────────────────────
  const paintList = () => {
    if (!list) return;
    const sel = selectedId();
    clear(listBox).append(el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "이름"), el("th", {}, "id"), el("th", {}, "리비전"), el("th", {}, "형상 변형"),
        el("th", {}, "지문"), el("th", {}, ""))),
      el("tbody", {}, list.map((p) => (p.unreadable
        ? el("tr", { class: "unreadable" },
          el("td", {}, "읽을 수 없음"), el("td", { class: "num" }, p.id),
          el("td", { colspan: 3 }, p.reason ?? ""),
          el("td", {}, el("button", {
            onclick: () => remove(p.id),
            title: "손상된 기체는 고칠 수 없다 — 지운 뒤 같은 id로 다시 만들거나 내보내 둔 JSON을 가져온다",
          }, "삭제")))
        : el("tr", { class: p.id === sel ? "selected" : null },
          el("td", {}, p.name,
            p.is_example ? el("span", { class: "hint", style: "margin-left:6px" }, "예제 · 읽기 전용") : null,
            p.design_source === null ? el("span", { class: "hint", style: "margin-left:6px" }, "게인 미설계") : null,
            p.design_source === "quick_seed"
              ? el("span", { class: "hint", style: "margin-left:6px" }, "초기 탐색 게인 — 자동 설계 전") : null,
            p.id === sel ? el("span", { class: "hint", style: "margin-left:6px" }, "← 계산에 쓰는 중") : null),
          el("td", { class: "num" }, p.id),
          el("td", { class: "num" }, p.revision),
          el("td", { class: "num" }, p.variants?.length ?? 0),
          el("td", { class: "num" }, p.fingerprint),
          el("td", { style: "white-space:nowrap" },
            el("button", {
              disabled: p.id === sel && !currentSelection()?.variant,
              title: "모든 탭의 계산에 이 기체(기본 형상)를 쓴다 — 페이지를 다시 읽는다",
              onclick: () => {
                const r = switchTo({ id: p.id, variant: null });
                if (r.reason) showError(r.reason);
              },
            }, "고르기"), " ",
            el("button", { onclick: () => openDoc(p.id) }, "열기"), " ",
            el("button", { onclick: () => clone(p) }, "복제"), " ",
            el("button", { onclick: () => exportDoc(p.id) }, "내보내기"), " ",
            p.is_example ? null : el("button", { onclick: () => remove(p.id) }, "삭제")))))),
    )));
  };

  // ── 문서 (패널) ──────────────────────────────────────────────────────────
  // 편집 중인 글을 버리는 길(다른 기체 열기·복제·가져오기·최신 불러오기)은 모두 이 질문을 거친다.
  // confirm이 없는 환경이면 버리지 않는다
  const discardOk = (then) => !opened?.dirty
    || !!globalThis.confirm?.(`「${opened.id}」에 저장하지 않은 편집이 있습니다 — 버리고 ${then}`);

  const openDoc = async (id) => {
    if (opened?.id === id && opened.dirty) {
      // 편집 중인 그 문서다 — 다시 받지 않는다. 받으면 패널을 닫았다 돌아온 사람의 글이 조용히 사라진다.
      // 편집이 없으면 아래로 내려가 다시 받는다(다른 곳에서 저장한 새 리비전을 보여 준다)
      drawers.open("doc");
      return;
    }
    if (opened?.id !== id && !discardOk("다른 기체를 열까요?")) return;
    try {
      clear(errBox);
      opened = fresh(await api.get(path(id)));
      drawers.open("doc");
    } catch (e) {
      showError(e);
    } finally {
      // 실패해도 다시 그린다 — 최신 불러오기가 비운 자리에 옛 편집기가 남으면 키 입력마다 오류가 난다
      paintDoc();
      paintVariants();
      paintViewer();
      paintSeed();
    }
  };

  const checkLine = (ok, text) => el("p", { class: ok ? "hint" : "error-box", style: "margin:8px 0 0" }, text);

  const validate = async () => {
    const target = opened; // 응답이 오는 사이 다른 문서를 열었으면 그 문서에 결과를 쓰지 않는다
    const { doc, error } = parseDocumentText(target.text);
    if (error) {
      target.check = { ok: false, lines: [error] };
    } else {
      try {
        const r = await api.post("/profiles/validate", { document: doc });
        const vs = Object.entries(r.variants ?? {});
        target.check = { ok: true, lines: [
          `통과 — 지문 ${r.fingerprint} · 플랜트 지문 ${r.plant_fingerprint}`
            + (vs.length ? ` · 형상 변형 ${vs.map(([k, fp]) => `${k} ${fp}`).join(", ")}` : ""),
          // 오류가 아닌 알림(저속 가림 등) — 저장·계산은 된다
          ...(r.warnings ?? []).map((w) => `주의${w.variant ? ` [형상 변형 ${w.variant}]` : ""} ${w.path} — ${w.message}`),
        ] };
      } catch (e) {
        target.check = { ok: false, lines: [failText(e)] };
      }
    }
    if (opened === target) paintDoc();
  };

  const save = async () => {
    const target = opened;
    const sentText = target.text;
    const { doc, error } = parseDocumentText(sentText);
    if (error) {
      target.check = { ok: false, lines: [error] };
      paintDoc();
      return;
    }
    const wasSelected = currentSelection()?.id === target.id;
    try {
      const body = await api.put(path(target.id), { base_revision: target.body.revision, document: doc });
      flushFocused(); // 저장하는 사이 친 값을 기록을 바꾸기 전에 target에 넣는다 — 아래 sentText 대조가 그것을 본다
      if (opened === target) {
        const next = fresh(body);
        next.mode = target.mode;
        next.editVariant = target.editVariant;
        next.check = { ok: true, lines: [`리비전 ${body.revision}로 저장했습니다 — 지문 ${body.fingerprint}`,
          ...(body.warnings ?? []).map((w) => `주의${w.variant ? ` [형상 변형 ${w.variant}]` : ""} ${w.path} — ${w.message}`)] };
        if (target.text !== sentText) {
          // 저장하는 사이 더 친 글은 버리지 않는다 — 새 리비전 위의 편집으로 남긴다
          next.text = target.text;
          next.obj = target.obj;
          next.dirty = true;
        }
        opened = next;
      }
      paintDoc();
      paintVariants();
      paintSeed(); // 리비전이 바뀌었다 — 탐색은 저장한 리비전에서 돈다
      await load();
      refreshPicker();
      // 지금 고른 기체를 고쳤다 — 다른 탭이 옛 리비전에서 만든 상태(게인 카탈로그 등)를 들고 있을 수 있다.
      // 다음 계산부터 새 리비전이 쓰이지만, 섞이지 않게 하는 확실한 길은 다시 읽기다 (profilepick.js 머리말)
      if (wasSelected && globalThis.confirm?.(
        `지금 계산에 쓰는 기체를 리비전 ${body.revision}로 저장했습니다. 다른 탭이 옛 리비전에서 만든 `
        + "상태를 들고 있을 수 있어 페이지를 다시 읽는 것이 안전합니다."
        + (opened?.dirty ? " 저장하는 사이 더 친 편집은 저장되지 않았고, 다시 읽으면 사라집니다." : "")
        + " 다시 읽을까요?")) {
        globalThis.location.reload();
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail?.head != null) {
        target.conflict = e.detail.head; // 다른 곳에서 먼저 저장했다 — 조용히 덮지 않는다
      } else {
        target.check = { ok: false, lines: [failText(e)] };
      }
      if (opened === target) paintDoc();
    }
  };

  const reloadLatest = async () => {
    if (!discardOk("최신 리비전을 불러올까요? (필요하면 글을 먼저 복사해 두세요)")) return;
    const id = opened.id;
    opened = null;
    await openDoc(id);
  };

  const ensureFormAssets = () => {
    formAssets ??= Promise.all([
      api.get("/profiles/_form"),
      api.get(path(EXAMPLE_ID)).then((b) => b.document).catch(() => null),
    ]).then(([spec, example]) => {
      formSpec = spec;
      exampleDoc = example;
    }).finally(() => { formAssets = null; });
    return formAssets;
  };

  const getSchema = (category, name) => {
    const key = `${category}/${name}`;
    if (!schemaCache.has(key)) {
      schemaCache.set(key, api.get(`/registry/${encodeURIComponent(category)}/${encodeURIComponent(name)}/schema`)
        .catch((e) => {
          schemaCache.delete(key); // 실패는 기억하지 않는다 — 다음에 다시 받는다
          throw e;
        }));
    }
    return schemaCache.get(key);
  };

  // 폼 ⇄ JSON 글은 같은 문서를 고친다. 글에서 폼으로 올 때만 글을 다시 읽는다(글이 틀렸으면 글에 머문다)
  const setMode = (mode) => {
    if (mode === "form" && opened.mode === "json") {
      const { doc, error } = parseDocumentText(opened.text);
      if (error) {
        opened.formError = `JSON 글을 폼으로 옮길 수 없습니다 — ${error}`;
        paintDoc();
        return;
      }
      opened.obj = doc;
    }
    opened.formError = null;
    opened.mode = mode;
    paintDoc();
  };

  // 수치 칸 쓰기가 다시 그리지 않고 고치는 자리 — 상태줄·결과 상자·폼 오류 줄 (paintDoc이 채운다)
  let statusEl = null;
  let checksBox = null;
  let formErrorEl = null;

  // 포커스가 폼 칸에 있으면 친 값이 아직 change를 안 냈다. 기다린 응답(검증·저장·CSV·형식 변경)이 폼을
  // 다시 그리거나 편집 기록을 바꾸기 **전에** blur로 그 change를 먼저 내게 한다 — 그리는 도중 칸이 떨어지며
  // change가 늦게 오면 새 폼은 옛 값을 보이고(문서엔 친 값), 기록이 바뀐 뒤면 조용히 거절돼 친 값이 사라진다
  const flushFocused = () => {
    const a = globalThis.document?.activeElement;
    if (a && a !== globalThis.document.body && docBox.contains?.(a)) a.blur?.();
  };
  // 모양이 바뀌는 조작(행 추가·없음 등) 뒤 키보드 포커스를 같은 칸 줄의 같은 조작으로 되돌린다 — 안 그러면
  // <body>로 떨어져 다음 Tab이 폼 맨 위에서 시작한다
  const focusKeyOf = (node) => {
    const row = node?.closest?.("[data-pf-path]");
    return row && docBox.contains?.(node)
      ? { path: row.getAttribute("data-pf-path"), tag: node.tagName, type: node.type, text: node.textContent } : null;
  };
  const restoreFocus = (key) => {
    if (!key) return;
    const row = [...(docBox.querySelectorAll?.("[data-pf-path]") ?? [])]
      .find((r) => r.getAttribute("data-pf-path") === key.path);
    if (!row) return;
    const same = [...row.querySelectorAll(key.tag)].find((n) => n.type === key.type && n.textContent === key.text);
    (same ?? row.querySelector("button, input, select, textarea"))?.focus();
  };

  const buildForm = () => {
    const owner = opened;
    const variants = Array.isArray(opened.obj.variants) ? opened.obj.variants : [];
    const known = variants.some((v) => v?.id === opened.editVariant);
    try {
      return renderProfileForm({
        spec: formSpec, doc: opened.obj, editVariant: known ? opened.editVariant : null,
        example: exampleDoc, readOnly: !!opened.body.is_example, getSchema,
        update: (fn, opts) => updateForm(owner, fn, opts),
        setEditVariant: (id) => {
          opened.editVariant = id;
          paintDoc();
        },
      });
    } catch (e) {
      // JSON 글로 만든 모양이 칸과 맞지 않는다(목록 자리에 수치 등) — 폼을 멈춘 채 두지 않고 글로 돌아간다
      opened.mode = "json";
      opened.formError = `폼으로 그릴 수 없는 모양입니다 — ${e.message}. JSON 글에서 고친 뒤 폼으로 오세요 `
        + "([검증]이 경로를 짚어 줍니다).";
      return null;
    }
  };

  // 폼 쓰기 — 받을지는 lib/profileform.js formUpdate가 정한다(그 순간의 문서에 적용, 다른 기록이면 거절).
  // **수치 칸의 쓰기는 아무것도 다시 그리지 않고 레이아웃도 바꾸지 않는다.** 칸의 change는 blur, 곧 [저장]의
  // mousedown에 온다 — 그때 다시 그리면 누르던 버튼이 사라지고, 결과 줄을 지우면 페이지가 줄어 버튼이 포인터
  // 밑에서 밀려난다. 둘 다 클릭이 없어진다. 그래서 결과 줄은 흐리게만 하고, 오류 줄은 자리를 남긴 채 감춘다.
  // 모양이 바뀌는 쓰기(structural — 행 추가·없음·형식 변경)만 다시 그린다: 클릭이 끝난 뒤라 잃을 것이 없다
  const updateForm = (owner, fn, { structural = false, async = false, editVariant } = {}) => {
    const out = formUpdate({ state: opened, owner, fn, async });
    if (out.reject) {
      if (opened === owner) {
        opened.formError = out.reject;
        paintDoc();
      }
      return;
    }
    if (out.error) {
      opened.formError = out.error;
      paintDoc();
      return;
    }
    opened.obj = out.obj;
    opened.text = out.text;
    opened.dirty = true;
    opened.check = null;
    if (editVariant !== undefined) opened.editVariant = editVariant;
    if (structural || editVariant !== undefined) {
      opened.formError = null;
      const focus = focusKeyOf(globalThis.document?.activeElement);
      paintDoc();
      restoreFocus(focus);
      return;
    }
    if (statusEl) statusEl.textContent = "저장하지 않은 편집 있음";
    checksBox?.classList.add("stale");
    if (opened.formError) {
      opened.formError = null;
      if (formErrorEl) formErrorEl.style.visibility = "hidden";
    }
  };

  const paintDoc = () => {
    flushFocused();
    if (!opened) {
      clear(docBox).append(el("p", { class: "hint" }, "목록에서 [열기]를 누르면 문서가 여기 열립니다."));
      return;
    }
    const b = opened.body;
    const readOnly = !!b.is_example;
    const head = el("p", { class: "hint", style: "margin:0 0 8px" },
      `${b.document.name} · ${b.document.id} · 리비전 ${b.revision} · 지문 ${b.fingerprint} · `
      + `플랜트 지문 ${b.plant_fingerprint}`);
    const modeBar = el("div", { class: "row", style: "gap:6px;margin:0 0 8px;align-items:center" },
      el("button", { class: opened.mode === "form" ? "primary" : null, onclick: () => setMode("form") }, "절별 폼"),
      el("button", { class: opened.mode === "json" ? "primary" : null, onclick: () => setMode("json") }, "JSON 글"),
      el("span", { class: "hint" }, "둘은 같은 문서를 고칩니다 — 폼에서 고친 값이 JSON 글에 그대로 들어갑니다. "
        + "null은 「없음」이고 예제 값으로 채워지지 않습니다(문서 규격 02 §5.6)."));

    let editor;
    if (opened.mode === "form" && formSpec) {
      const node = buildForm();
      if (!node) {
        paintDoc(); // 글로 돌아갔다 — 사유와 함께 다시 그린다
        return;
      }
      editor = node;
    } else if (opened.mode === "form") {
      {
        editor = el("p", { class: "hint" }, "폼 서술을 불러오는 중…");
        ensureFormAssets().then(() => { if (opened) paintDoc(); }).catch((e) => {
          if (!opened) return;
          opened.mode = "json";
          opened.formError = `폼 서술을 못 받아 JSON 글로 엽니다 — ${failText(e)}`;
          paintDoc();
        });
      }
    } else if (readOnly) {
      editor = el("textarea", { class: "doc", readonly: "readonly", value: opened.text });
    } else {
      editor = el("textarea", {
        class: "doc", spellcheck: "false", value: opened.text,
        oninput: (e) => {
          opened.text = e.target.value;
          opened.dirty = true;
          status.textContent = "저장하지 않은 편집 있음";
        },
      });
    }
    const status = el("span", { class: "hint" }, opened.dirty ? "저장하지 않은 편집 있음" : "");
    statusEl = status;
    checksBox = el("div", {}, ...(opened.check ? opened.check.lines.map((t) => checkLine(opened.check.ok, t)) : []));
    clear(docBox).append(head,
      readOnly
        ? el("p", { class: "notice" }, "예제 기체는 읽기 전용입니다 — 엔진에 딸린 문서이고 실기체 값이 아닙니다. ",
          el("button", { onclick: () => clone({ id: b.document.id, name: b.document.name }) }, "복제해서 고치기"))
        : null,
      modeBar,
      (formErrorEl = opened.formError ? el("div", { class: "error-box", style: "margin:0 0 8px" }, opened.formError) : null),
      editor,
      readOnly ? null : el("div", { class: "row", style: "gap:8px;margin-top:8px;align-items:center" },
        el("button", { onclick: validate, title: "저장하지 않고 서버 검증만 — 저장과 같은 규칙" }, "검증"),
        el("button", { class: "primary", onclick: save,
          title: `리비전 ${b.revision} 위에 저장한다 — 그사이 다른 곳에서 저장했으면 충돌로 알린다` }, "저장"),
        el("button", { onclick: reloadLatest }, "최신 불러오기"),
        status),
      opened.conflict != null
        ? el("div", { class: "error-box", style: "margin-top:8px" },
          `다른 곳에서 먼저 저장했습니다 — 최신은 리비전 ${opened.conflict}이고 이 편집은 리비전 ${b.revision} 위의 것입니다. `
          + "덮어쓰지 않았습니다. 편집을 복사해 두고 [최신 불러오기] 뒤에 다시 적용하세요.")
        : null,
      checksBox);
  };

  // ── 형상 변형 (패널) ──────────────────────────────────────────────────────
  const paintVariants = () => {
    if (!opened) {
      clear(variantBox).append(el("p", { class: "hint" }, "목록에서 [열기]로 기체를 열면 형상 변형이 여기 섭니다."));
      return;
    }
    const doc = opened.body.document;
    const sel = currentSelection();
    if (!doc.variants?.length) {
      clear(variantBox).append(el("p", { class: "hint" },
        `「${doc.name}」에는 형상 변형이 없습니다 — 문서 패널 절별 폼의 [새 형상 변형]으로 만듭니다.`));
      return;
    }
    clear(variantBox).append(el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "이름"), el("th", {}, "id"), el("th", {}, "덮어쓴 경로"),
        el("th", {}, "지문"), el("th", {}, ""))),
      el("tbody", {}, doc.variants.map((v) => el("tr", {},
        el("td", {}, v.name), el("td", { class: "num" }, v.id),
        el("td", { class: "num" }, Object.keys(v.patch ?? {}).join(", ") || "—"),
        el("td", { class: "num" }, opened.body.variants?.[v.id] ?? "—"),
        el("td", {}, el("button", {
          disabled: sel?.id === doc.id && sel?.variant === v.id,
          title: "모든 탭의 계산에 이 형상 변형을 쓴다 — 페이지를 다시 읽는다",
          onclick: () => {
            const r = switchTo({ id: doc.id, variant: v.id });
            if (r.reason) showError(r.reason);
          },
        }, "이 변형 고르기"), " ",
        el("button", {
          title: "문서 패널의 절별 폼에서 이 변형이 덮어쓴 값을 고친다 (저장된 문서 기준 목록)",
          onclick: () => {
            opened.editVariant = v.id;
            setMode("form");
            drawers.open("doc");
          },
        }, "폼에서 고치기")))))));
  };

  // ── 공력 DB 뷰어 (패널) ─────────────────────────────────────────────────
  // 연 문서의 계수 계산기로 한 축을 따라 곡선을 낸다 — 표를 반입한 직후 저장하지 않고도 본다(서버가 본문 문서로
  // 계산한다). 표를 따로 그리지 않는다: 시뮬·트림이 쓰는 같은 계산기라 곡선이 곧 기체가 느끼는 계수다
  const paintViewer = () => {
    if (!opened) {
      clear(viewerBox).append(el("p", { class: "hint" }, "목록에서 [열기]로 기체를 열면 그 문서의 공력 곡선을 봅니다."));
      return;
    }
    if (!formSpec?.slice) {
      clear(viewerBox).append(el("p", { class: "hint" }, "뷰어 서술을 불러오는 중…"));
      ensureFormAssets().then(() => { if (opened) paintViewer(); }).catch((e) => showError(e));
      return;
    }
    const { axes, coefficients, max_points: maxPoints } = formSpec.slice;
    if (viewer.forId !== opened.id) {
      viewer.result = null;
      viewer.error = null;
    }
    const input = (value, onValue, cls = "pf-num") => el("input", {
      class: cls, value, spellcheck: "false", oninput: (e) => onValue(e.target.value),
    });
    const chartBox = el("div");
    const paintChart = () => {
      const res = viewer.result;
      if (!res) {
        clear(chartBox).append(viewer.error ? el("p", { class: "error-box" }, viewer.error)
          : el("p", { class: "hint" }, "[그리기]를 누르면 곡선이 섭니다."));
        return;
      }
      const range = res.db_ranges?.[res.along];
      clear(chartBox).append(
        lineChartCanvas(res.x, [{ data: res.coefficients[viewer.coef], color: "#0a84ff", label: viewer.coef }],
          { title: `${viewer.coef} — ${res.along}`, xUnit: AXIS_UNIT[res.along] ?? "", width: 640, height: 240 }),
        res.stall?.table_curve
          ? lineChartCanvas(res.x, [{ data: res.stall.table_curve, color: "#ff9f0a", label: "α_stall" }],
            { title: "실속 표 α_stall(M)", xUnit: "", width: 640, height: 160 })
          : null,
        el("p", { class: "hint" }, stallNote(res)),
        el("p", { class: "hint" },
          `고정: ${Object.entries(res.fixed).map(([k, v]) => `${k} ${v}`).join(" · ")} · 무차원 각속도 0 · V = 마하 × 그 고도 음속`
          + (range ? ` · DB 유효 범위 ${res.along} [${range[0]}, ${range[1]}]` : "")),
      );
    };
    // 못 그린 사유는 옛 곡선을 지우고 적는다 — 곡선을 남기면 누른 것이 아무 일도 안 한 것처럼 보이고, 글을 고친 뒤라면
    // 고친 것이 반영되지 않은 것처럼 보인다. 사유도 이 기체의 것으로 묶는다(다른 기체를 열면 지워진다)
    const fail = (text) => {
      viewer.result = null;
      viewer.error = text;
      viewer.forId = opened?.id ?? null;
      paintChart();
    };
    const draw = async () => {
      if (!opened) {
        paintViewer(); // 그사이 연 문서를 지웠다 — 안내로 바꾼다
        return;
      }
      const b = sliceBody(viewer, axes);
      if (b.error) return fail(b.error);
      if (b.value.n > maxPoints) return fail(`점 수는 ${maxPoints}까지입니다`);
      // JSON 글 편집 중이면 글이 정본이다 — 폼 객체는 글에서 폼으로 올 때만 맞춰진다
      const parsed = opened.mode === "json" ? parseDocumentText(opened.text) : { doc: opened.obj };
      if (parsed.error) return fail(`JSON 글을 읽을 수 없어 그리지 않았습니다 — ${parsed.error}`);
      const target = opened;
      try {
        const res = await api.post("/profiles/aero-slice", {
          document: parsed.doc, ...(opened.editVariant ? { variant: opened.editVariant } : {}), ...b.value,
        });
        if (opened !== target) return; // 그사이 다른 기체를 열었다
        viewer.result = res;
        viewer.forId = target.id;
        viewer.error = null;
      } catch (e) {
        if (opened !== target) return;
        return fail(failText(e));
      }
      paintChart();
    };
    clear(viewerBox).append(
      el("div", { class: "row", style: "gap:8px;flex-wrap:wrap;align-items:flex-end" },
        el("label", { class: "field" }, "따라갈 축", el("select", {
          onchange: (e) => { viewer.along = e.target.value; paintViewer(); },
        }, axes.map((a) => el("option", { value: a, selected: a === viewer.along }, a)))),
        el("label", { class: "field" }, "시작", input(viewer.start, (v) => { viewer.start = v; })),
        el("label", { class: "field" }, "끝", input(viewer.stop, (v) => { viewer.stop = v; })),
        el("label", { class: "field" }, "점 수", input(viewer.n, (v) => { viewer.n = v; })),
        el("label", { class: "field" }, "계수", el("select", {
          onchange: (e) => { viewer.coef = e.target.value; paintChart(); },
        }, coefficients.map((c) => el("option", { value: c, selected: c === viewer.coef }, c)))),
        el("button", { class: "primary", onclick: draw }, "그리기")),
      el("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-top:6px" },
        axes.filter((a) => a !== viewer.along).map((a) => el("label", { class: "field" },
          `${a}${AXIS_UNIT[a] ? ` [${AXIS_UNIT[a]}]` : ""}`,
          input(viewer.fixed[a] ?? "0", (v) => { viewer.fixed[a] = v; })))),
      el("p", { class: "hint", style: "margin:6px 0" },
        opened.editVariant ? `형상 변형 「${opened.editVariant}」을 적용한 문서로 계산합니다(편집 중인 글 기준). `
          : "편집 중인 글(저장 전 포함)로 계산합니다. ",
        "실속 추출은 참고용이고 정본은 공력팀 실속 표다(01 §2.3)."),
      chartBox);
    paintChart();
  };

  // ── 초기 게인 빠른 탐색 (패널) ─────────────────────────────────────────────
  // 저장된 리비전에서 서버 잡이 돈다(편집 중 글은 보내지 않는다). 채택되면 서버가 새 리비전으로 쓰고, 여기서는
  // 목록·열린 문서를 다시 받는다. 부호·크기·출처는 엔진이 정한다 — 이 패널은 결과를 줄 세울 뿐이다
  const seedResultView = (body) => {
    const s = seedSummary(body);
    const num = (v) => (typeof v === "number" ? Number(v.toPrecision(4)).toString() : "—");
    return el("div", { style: "margin-top:8px" },
      el("p", { class: s.ok ? "notice" : "error-box" }, s.headline),
      s.rows.length ? el("div", { class: "scroll-x" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "자리"), el("th", {}, "값"), el("th", {}, "부호 근거"),
          el("th", {}, "쓴 앵커"), el("th", {}, "사유"))),
        el("tbody", {}, s.rows.map((r) => el("tr", {},
          el("td", { class: "num" }, r.name), el("td", { class: "num" }, num(r.value)),
          el("td", { class: "num" }, r.basis), el("td", { class: "num" }, r.used),
          el("td", {}, r.reason ? `${r.reason} — ${r.reasonText ?? ""}` : "")))))) : null,
      s.anchors.length ? el("p", { class: "hint" }, `앵커(q̄ 중앙·최저·최고): ${s.anchors.join(" · ")}`) : null,
      Object.keys(s.autopilotSources).length
        ? el("p", { class: "hint" }, "자동조종 자리 출처: "
          + Object.entries(s.autopilotSources).map(([k, n]) => `${AP_SOURCE[k] ?? k} ${n}`).join(" · ")
          + (s.scheduleCreated ? " · 게인 스케줄을 새로 만들었습니다(q̄ 역비)" : ""))
        : null,
      s.warnings.length ? el("details", {}, el("summary", {}, `검증 경고 ${s.warnings.length}건`),
        el("ul", {}, s.warnings.map((w) => el("li", {}, w)))) : null,
      s.notes.map((n) => el("p", { class: "hint" }, n)));
  };

  const deriveResultView = (body) => {
    const s = deriveSummary(body);
    const st = s.stats;
    const deg = (v) => (typeof v === "number" ? `${(v * 180 / Math.PI).toFixed(2)}°` : "—");
    return el("div", { style: "margin-top:8px" },
      el("p", { class: s.ok ? "notice" : "error-box" }, s.headline),
      s.rows.length ? el("div", { class: "scroll-x" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "마하"), el("th", {}, "δe_trim [rad]"), el("th", {}, "[°]"))),
        el("tbody", {}, s.rows.map((r) => el("tr", {}, el("td", { class: "num" }, r.mach),
          el("td", { class: "num" }, Number(r.value.toPrecision(5)).toString()), el("td", { class: "num" }, deg(r.value))))))) : null,
      st ? el("p", { class: "hint" },
        `검사 ${st.checks}점 · 요구 미달 ${st.shortfall} · 과잉 최대 ${deg(st.excessMax)} · 보정 ${st.iterations}회 · `
        + `뺀 트림(미수렴·포화) ${st.excluded}`
        + (st.undefined.length ? ` · 요구가 없어 이웃 값으로 채운 마하 ${st.undefined.join(", ")}` : "")) : null);
  };

  const seedDone = async (job) => {
    // 같은 잡에 감시자가 여럿 붙는다(도는 동안 패널을 다시 그릴 때마다) — 지금 잡이 아니면 이미 처리했거나 다음
    // 잡이 돌고 있다. 그대로 두면 늦은 감시자가 다음 잡을 자기 대상으로 알고 지운다
    if (seedJob?.id !== job.id) {
      paintSeed();
      return;
    }
    const target = seedJob;
    seedJob = null;
    if (job.status === "error") showError(`초기 게인 탐색 작업 오류 — ${job.error ?? ""}`);
    if (!target || cancelledWithoutResult(job) || !job.result_id) {
      paintSeed();
      return;
    }
    try {
      const body = await api.get(`/results/${encodeURIComponent(job.result_id)}`);
      seedResult = { profileId: target.profileId, kind: target.kind, body };
      if (body.written) {
        await load();
        refreshPicker();
        if (opened?.id === target.profileId && !opened.dirty) {
          opened = fresh(await api.get(path(target.profileId)));
          paintDoc();
          paintVariants();
          paintViewer();
        }
        if (currentSelection()?.id === target.profileId && globalThis.confirm?.(
          `지금 계산에 쓰는 기체에 ${target.kind === "derive_de_trim" ? "δe_trim 표" : "초기 게인"}을 리비전 `
          + `${body.profile?.revision}로 저장했습니다. 다른 탭이 옛 리비전에서 `
          + "만든 상태를 들고 있을 수 있어 페이지를 다시 읽는 것이 안전합니다. 다시 읽을까요?")) {
          globalThis.location.reload();
          return;
        }
      }
    } catch (e) {
      showError(e);
    }
    paintSeed();
  };

  const runSeed = async () => {
    if (!opened || opened.body.is_example) return;
    if (opened.dirty) {
      showError("저장하지 않은 편집이 있습니다 — 초기 게인 탐색은 저장한 리비전에서만 돕니다. 먼저 저장합니다.");
      return;
    }
    if (opened.body.document.law?.design != null && !globalThis.confirm?.(
      "지금 게인을 탐색 결과로 바꿔 새 리비전으로 저장합니다(옛 리비전은 남습니다). 탐색할까요?")) return;
    try {
      clear(errBox);
      const job = await api.post(`${path(opened.id)}/quick-seed`,
        { base_revision: opened.body.revision, sim_check: seedSimCheck });
      seedJob = { id: job.id, profileId: opened.id, kind: "quick_seed" };
      seedResult = null;
      paintSeed();
    } catch (e) {
      showError(e);
    }
  };

  const runDerive = async () => {
    if (!opened || opened.body.is_example) return;
    if (opened.dirty) {
      showError("저장하지 않은 편집이 있습니다 — δe_trim 표 도출은 저장한 리비전의 플랜트로 돕니다. 먼저 저장합니다.");
      return;
    }
    if (opened.body.document.law?.alloc?.de_trim != null && !globalThis.confirm?.(
      "지금 δe_trim 표를 도출 결과로 바꿔 새 리비전으로 저장합니다(옛 리비전은 남습니다). 도출할까요? "
      + "(마하 검사 격자 × 연료 × 고도로 트림을 돌려 수십 초 걸릴 수 있습니다)")) return;
    try {
      clear(errBox);
      const job = await api.post(`${path(opened.id)}/derive-de-trim`, { base_revision: opened.body.revision });
      seedJob = { id: job.id, profileId: opened.id, kind: "derive_de_trim" };
      seedResult = null;
      paintSeed();
    } catch (e) {
      showError(e);
    }
  };

  const paintSeed = () => {
    if (!opened) {
      clear(seedBox).append(el("p", { class: "hint" }, "목록에서 [열기]로 기체를 열면 게인 출처와 초기 게인 빠른 탐색이 여기 섭니다."));
      return;
    }
    const doc = opened.body.document;
    const src = designSource(doc);
    const trim = deTrimStatus(doc, list?.find((p) => p.id === opened.id));
    const busy = seedJob != null;
    const progress = el("div");
    const res = seedResult?.profileId === opened.id ? seedResult : null;
    clear(seedBox).append(
      el("p", {}, el("strong", {}, src.label), ` · 저장된 리비전 ${opened.body.revision}`),
      el("p", { class: "hint" },
        "부호는 선형 모델의 조종효율(B)에서, 크기는 설계 격자 앵커(q̄ 중앙·최저·최고)마다 튜닝한 값의 중앙값에서, "
        + "자동조종은 시간척도 분리 휴리스틱에서 옵니다. 채택되면 새 리비전으로 저장하고(옛 리비전은 남습니다) 결과 "
        + "탭에도 남깁니다. 자동 설계가 이 게인에서 출발해 다듬습니다."),
      opened.body.is_example
        ? el("p", { class: "hint" }, "예제 기체는 고칠 수 없습니다 — 복제한 기체에서 탐색합니다.")
        : el("div", { class: "row", style: "gap:8px;align-items:center;flex-wrap:wrap" },
          el("button", { class: "primary", disabled: busy, onclick: runSeed,
            title: busy ? "기체를 고치는 잡이 이미 돌고 있다 — 끝난 뒤 돌린다" : "" },
            doc.law?.design ? "초기 게인 다시 탐색" : "초기 게인 빠른 탐색"),
          el("label", { class: "field", title: "중앙 앵커 한 케이스로 평가(시뮬 포함)를 돌려 결과에 싣는다 — 채택 판정에는 쓰지 않는다" },
            el("input", { type: "checkbox", checked: seedSimCheck, onchange: (e) => { seedSimCheck = e.target.checked; } }),
            " 시뮬 확인도 싣기(수 초 더)")),
      el("h4", { style: "margin:14px 0 4px" }, "할당 δe_trim 표"),
      el("p", {}, el("strong", { class: trim.stale ? "error-box" : null }, trim.label)),
      el("p", { class: "hint" },
        "선회 하중에서 롤 예산의 피치 몫을 먼저 떼는 1g 트림 승강타 표입니다(R = δe_trim(M)·n). 마하마다 연료 × 고도 "
        + "격자의 최악 |δe|를 요구로 삼고, 표 보간이 검사 격자(마하 0.005 간격)의 요구를 밑돌지 않을 때까지 올립니다. "
        + "도출한 표는 플랜트 지문을 남겨, 플랜트를 고치면 법칙 조립이 낡은 표를 거부합니다."),
      opened.body.is_example ? null : el("div", { class: "row", style: "gap:8px;align-items:center" },
        el("button", { disabled: busy, onclick: runDerive,
          title: busy ? "기체를 고치는 잡이 이미 돌고 있다 — 끝난 뒤 돌린다" : "" },
        doc.law?.alloc?.de_trim ? "δe_trim 표 다시 도출" : "δe_trim 표 도출")),
      progress,
      res ? (res.kind === "derive_de_trim" ? deriveResultView(res.body) : seedResultView(res.body)) : null);
    if (busy && seedJob.profileId === opened.id) {
      attachProgress(progress, seedJob.id, {
        onDone: seedDone,
        onError: (e) => {
          seedJob = null;
          showError(e);
          paintSeed();
        },
      });
    }
  };

  // ── 복제·내보내기·가져오기·삭제 ─────────────────────────────────────────
  const clone = async (p) => {
    if (!discardOk("복제할까요? (복제한 기체가 문서 패널에 열립니다)")) return;
    const newId = globalThis.prompt?.("새 기체 id (영문·숫자·_·-, 1~64자, `_`로 시작 불가)", `${p.id}-copy`);
    if (!newId) return;
    const name = globalThis.prompt?.("새 기체 이름", `${p.name} 복제`);
    if (name == null) return;
    try {
      clear(errBox);
      const src = await api.get(path(p.id));
      const created = await api.post("/profiles",
        { document: cloneDocument(src.document, { id: newId.trim(), name: name.trim() || newId.trim() }) });
      opened = fresh(created);
      await load();
      refreshPicker();
      paintDoc();
      paintVariants();
      paintViewer(); // 옛 기체의 곡선이 새 문서 밑에 남지 않게
      paintSeed();
      drawers.open("doc");
    } catch (e) {
      showError(e);
    }
  };

  const exportDoc = async (id) => {
    try {
      clear(errBox);
      const body = await api.get(path(id));
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(body.document, null, 1)], { type: "application/json" }));
      const a = el("a", { href: url, download: exportFileName(id, body.revision) });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      showError(e);
    }
  };

  const importDoc = async () => {
    if (!discardOk("가져올까요? (가져온 기체가 문서 패널에 열립니다)")) return;
    const { doc, error } = parseDocumentText(importText);
    const out = importBox.querySelector(".import-result");
    if (error) {
      clear(out).append(checkLine(false, error));
      return;
    }
    try {
      const created = await api.post("/profiles", { document: doc });
      importText = "";
      opened = fresh(created);
      await load();
      refreshPicker();
      paintImport();
      paintDoc();
      paintVariants();
      paintViewer();
      paintSeed();
      drawers.open("doc");
    } catch (e) {
      const text = e instanceof ApiError && e.status === 409
        ? `이미 있는 기체 id입니다 — 문서의 id를 바꿔 가져오거나 기존 기체를 지운 뒤 가져옵니다 (${failText(e)})`
        : failText(e);
      clear(out).append(checkLine(false, text));
    }
  };

  const paintImport = () => {
    const area = el("textarea", {
      class: "doc", style: "min-height:180px", spellcheck: "false", value: importText,
      placeholder: "내보내기로 받은 기체 JSON을 붙여 넣거나 파일을 고른다",
      oninput: (e) => { importText = e.target.value; },
    });
    const file = el("input", {
      type: "file", accept: ".json,application/json",
      onchange: (e) => {
        const f = e.target.files?.[0];
        if (!f) return;
        const reader = new FileReader();
        reader.onload = () => {
          importText = String(reader.result ?? "");
          area.value = importText;
        };
        reader.readAsText(f);
      },
    });
    clear(importBox).append(
      el("p", { class: "hint", style: "margin:0 0 8px" },
        "가져오기는 새 기체 만들기와 같은 길입니다 — 서버가 같은 규칙으로 검증하고 리비전 1(지웠던 id면 이어지는 번호)로 저장합니다."),
      file, area,
      el("div", { class: "row", style: "gap:8px;margin-top:8px" },
        el("button", { class: "primary", onclick: importDoc }, "가져오기")),
      el("div", { class: "import-result" }));
  };

  const remove = async (id) => {
    const dirtyNote = opened?.id === id && opened.dirty ? " 열어 둔 문서의 저장하지 않은 편집도 버려집니다." : "";
    if (!globalThis.confirm?.(`기체 「${id}」를 지웁니다 — 목록·조회에서 사라지고, 그 기체로 계산한 결과는 `
      + `계산에 쓴 기체 스냅숏과 함께 남습니다.${dirtyNote} 지울까요?`)) return;
    try {
      clear(errBox);
      await api.del(path(id));
      if (opened?.id === id) opened = null;
      if (currentSelection()?.id === id) {
        // 지금 고른 기체다 — 다음 요청이 404가 된다. 예제로 되돌리고 다시 읽는다
        setSelection(null);
        saveSelection(browserStorage(), null);
        globalThis.alert?.("지금 계산에 쓰던 기체를 지웠습니다 — 예제 기체로 되돌리고 페이지를 다시 읽습니다.");
        globalThis.location.reload();
        return;
      }
      await load();
      refreshPicker();
      paintDoc();
      paintVariants();
      paintViewer(); // 지운 문서의 곡선·[그리기]가 남으면 누를 때 빈 문서를 읽는다
      paintSeed();
    } catch (e) {
      showError(e);
    }
  };

  // ── 대표 그림 (전면) ──────────────────────────────────────────────────────
  // 기본은 지금 계산에 쓰는 기체(헤더 선택·형상 변형 반영)다. ‹ ›로 목록의 다른 기체·형상 변형(예: 예제의 EO/IR형)을
  // **그 자리에서** 미리 본다 — 계산 선택은 바뀌지 않는다. 계산까지 바꾸려면 [이 기체로 계산]을 누르고, 그것은 헤더
  // 선택과 같은 전환이다(묻고 다시 읽기, 06 §8). 화살표마다 페이지를 다시 읽으면 둘러보기가 안 된다.
  // 무엇을 그리고 무엇이라고 말할지는 lib/aircrafthero.js, 그리기는 번들의 mountAircraftViewer(한 렌더러에서 show로 바꾼다)
  let heroNav = () => {}; // 목록을 받은 뒤 화살표를 다시 세운다(load가 부른다)
  const paintHero = () => {
    const session = {};
    hero = { session, handle: null };
    const live = () => hero?.session === session;
    const selected = () => currentSelection() ?? { id: EXAMPLE_ID, variant: null };
    const stage = el("div", { class: "hero-canvas" });
    const status = el("div", { class: "hero-status" }, "기체를 불러오는 중…");
    const name = el("span", { class: "hero-name" });
    const badge = el("span", { class: "hero-badge" });
    const counter = el("span", { class: "hero-count" });
    const facts = el("p", { class: "hero-facts" });
    const notes = el("div", {});
    const useBtn = el("button", { class: "hero-use", title: "모든 탭의 계산을 이 기체로 바꾼다 — 헤더 선택과 같다(페이지를 다시 읽는다)" },
      "이 기체로 계산");
    const spinBtn = el("button", { class: "hero-spin" }, "회전 멈춤");
    const prev = el("button", { class: "hero-nav prev" }, "‹");
    const next = el("button", { class: "hero-nav next" }, "›");
    prev.setAttribute("aria-label", "이전 기체");
    next.setAttribute("aria-label", "다음 기체");
    for (const b of [useBtn, spinBtn, prev, next]) b.hidden = true;
    // 그림 위에는 조작(‹ ›)만 — 이름·상태·사실은 그림 아래 캡션이다(다른 탭의 그림과 같은 배치, 06 §2)
    clear(heroBox).append(
      el("div", { class: "aircraft-hero" }, stage, status, prev, next),
      el("div", { class: "hero-caption" },
        el("div", { class: "hero-line" }, name, badge, useBtn, counter, spinBtn), facts, notes));
    const paintNotes = (lines) => clear(notes).append(...lines.map((t) => el("p", { class: "hero-note" }, t)));

    // 문서·자산 목록·번들 — 번들과 목록은 한 번, 문서는 기체마다
    const why = (what) => (e) => {
      throw new Error(`${what} — ${e?.message ?? e}`);
    };
    const ready = Promise.all([
      api.get("/world/manifest").catch(() => null),
      import(BUNDLE).catch(why("3D 번들을 불러오지 못했습니다 — 빌드가 없으면 web/world에서 npm run build")),
    ]);
    const baseFor = (id) => {
      if (!heroDocs.has(id)) {
        const pending = api.get(path(id)).then((body) => body.document);
        heroDocs.set(id, pending);
        pending.catch(() => {
          if (heroDocs.get(id) === pending) heroDocs.delete(id);
        });
      }
      return heroDocs.get(id);
    };
    // {doc: 적용 문서, raw: 기본 문서} — 적용 문서에는 variants가 없다(치환 적용이 뗀다). 변형 이름·덮어쓴 항목은 raw에서 읽는다
    const docFor = (entry) => {
      const raw = baseFor(entry.id);
      const doc = sameSelection(entry, selected())
        ? selectedDocument() // 계산이 쓰는 그 문서
        : raw.then((d) => {
          // 없는 형상 변형을 기본 문서로 조용히 바꿔 그리지 않는다 — 그리면 이름표와 그림이 다른 기체를 말한다
          if (entry.variant && !(d.variants ?? []).some((v) => v?.id === entry.variant)) {
            throw new Error(`형상 변형이 없다: ${entry.id} / ${entry.variant}`);
          }
          return effectiveOf(d, entry.variant);
        });
      return Promise.all([doc, raw]).then(([d, r]) => ({ doc: d, raw: r }));
    };

    let seq = 0;
    // 지금 캡션·그림이 말하는 {entry, raw}. heroPick은 문서를 받는 중일 수 있어 [이 기체로 계산]·늦은 도식 알림은 이것을 쓴다
    let shown = null;
    const showEntry = (entry) => {
      heroPick = entry;
      const my = ++seq;
      const isSelected = sameSelection(entry, selected());
      paintNav();
      useBtn.hidden = true; // 문서가 오기 전 캡션은 옛 기체를 말한다 — 그사이 누르면 캡션과 다른 기체로 바뀐다
      Promise.all([docFor(entry).catch(why("기체 문서를 받지 못했습니다")), ready]).then(([{ doc, raw }, [manifest, mod]]) => {
        if (!live() || my !== seq) return; // 떠났거나 그사이 다른 기체로 넘겼다
        shown = { entry, raw };
        badge.hidden = false;
        const vname = entry.variant ? (raw.variants ?? []).find((v) => v?.id === entry.variant)?.name : null;
        name.textContent = doc.name + (vname ? ` · ${vname}` : "");
        badge.textContent = isSelected ? "계산에 쓰는 중" : "미리 보기";
        badge.className = isSelected ? "hero-badge" : "hero-badge preview";
        badge.title = isSelected ? "모든 탭이 이 기체로 계산한다" : "계산은 아직 헤더에서 고른 기체로 한다";
        useBtn.hidden = isSelected;
        facts.textContent = heroFacts(doc).join(" · ");
        const plan = heroPlan(doc, manifest);
        stage.title = `끌어서 돌려 보기 — ${plan.title}`;
        const lines = [variantNote(raw, entry.variant), ...plan.notes].filter(Boolean);
        paintNotes(lines);
        const content = { model: plan.model, schematic: plan.schematic };
        if (hero.handle) {
          hero.handle.show(content);
          return;
        }
        const handle = mod.mountAircraftViewer(stage, {
          ...content,
          onStatus: (s) => {
            if (!live()) return;
            status.hidden = s.state === "ready";
            status.textContent = s.state === "failed" ? `그리지 못했습니다 — ${s.reason}` : "모델을 불러오는 중…";
            // 모델을 못 읽어 도식으로 물러났으면 「화면용 모델」 안내는 틀린 말이다 — 사유로 갈아 끼운다
            if (s.state === "ready" && s.source === "schematic" && s.reason) {
              paintNotes([variantNote(shown?.raw, shown?.entry.variant), s.reason].filter(Boolean));
            }
          },
        });
        hero.handle = handle;
        const label = () => { spinBtn.textContent = handle.spinning ? "회전 멈춤" : "회전"; };
        spinBtn.onclick = () => { handle.setSpin(!handle.spinning); label(); };
        label();
        spinBtn.hidden = false;
      }).catch((e) => {
        if (!live() || my !== seq) return;
        // 캡션·그림을 비운다 — 두면 순번은 새 칸인데 이름·그림·[이 기체로 계산]은 옛 기체를 말한다(지워진 기체로 넘긴 경우)
        shown = null;
        name.textContent = entry.label ?? entry.id;
        badge.hidden = true;
        facts.textContent = "";
        paintNotes([]);
        hero?.handle?.show({ model: null, schematic: null }); // 무대도 비운다 — 늦게 온 옛 모델이 이 알림을 덮지 않게
        status.hidden = false;
        status.textContent = e?.message ?? String(e);
      });
    };

    const paintNav = () => {
      const entries = heroEntries(list);
      const at = entries.findIndex((e) => sameSelection(e, heroPick ?? selected()));
      const many = entries.length > 1;
      prev.hidden = !many;
      next.hidden = !many;
      counter.textContent = many && at >= 0 ? `${at + 1} / ${entries.length}` : "";
      if (!many) return;
      prev.title = `이전: ${entries[stepIndex(entries.length, at, -1)].label}`;
      next.title = `다음: ${entries[stepIndex(entries.length, at, +1)].label}`;
    };
    const move = (dir) => {
      const entries = heroEntries(list);
      if (entries.length < 2) return;
      const at = entries.findIndex((e) => sameSelection(e, heroPick ?? selected()));
      showEntry(entries[stepIndex(entries.length, at, dir)]);
    };
    prev.onclick = () => move(-1);
    next.onclick = () => move(+1);
    useBtn.onclick = () => {
      if (!shown || sameSelection(shown.entry, selected())) return;
      const r = switchTo(shown.entry);
      if (r.reason) showError(r.reason);
    };
    let loads = 0;
    heroNav = () => {
      if (!live()) return;
      loads += 1;
      // 보던 기체가 목록에서 사라졌으면(지워짐) 계산에 쓰는 기체로 돌아간다 — 없는 문서를 계속 받으려 하지 않게
      if (heroPick && list && !heroEntries(list).some((e) => sameSelection(e, heroPick))) {
        showEntry(selected());
        return;
      }
      // 첫 목록은 그림을 막 그린 직후라 화살표만 세운다. 그 뒤(저장·삭제·새로고침)는 받아 둔 문서를 비웠으니 다시 그린다
      if (loads > 1) showEntry(heroPick ?? selected());
      else paintNav();
    };
    showEntry(heroPick ?? selected());
  };

  const drawers = createDrawers({
    id: "aircraft-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "doc", label: "문서", group: "편집",
        title: "연 기체의 문서 — 검증·리비전 저장", build: () => docBox },
      { key: "variants", label: "형상 변형", group: "편집",
        title: "연 기체의 형상 변형 — 덮어쓴 경로·지문·고르기",
        count: () => opened?.body.document.variants?.length ?? null, build: () => variantBox },
      { key: "seed", label: "게인·δe_trim", group: "설계",
        title: "연 기체의 게인 출처와 할당 표 — 초기 게인 빠른 탐색(조종효율 부호·앵커 튜닝 크기)·δe_trim 표 도출",
        build: () => seedBox },
      { key: "aero", label: "공력 DB 뷰어", group: "보기",
        title: "연 문서의 계수 계산기로 한 축을 따라 CL·CD·모멘트 계수 곡선 — 실속 표 대조", build: () => viewerBox },
      { key: "import", label: "가져오기", group: "반입",
        title: "내보내 둔 기체 JSON을 새 기체로", build: () => [
          drawerSection("가져오기", null, importBox)] },
    ],
  });

  if (list) paintList();
  paintNotices();
  paintDoc();
  paintVariants();
  paintViewer();
  paintSeed();
  paintImport();
  paintHero();
  load();

  return el("div", { class: "tab-page aircraft-page" },
    tabTop({
      title: "기체",
      lead: "모든 탭이 헤더에서 고른 기체로 계산합니다 — 여기서 기체 문서를 만들고 고칩니다(예제는 복제해서).",
      actions: [el("button", { onclick: load }, "새로고침")],
      extra: [statusLine, errBox, noticeBox],
    }),
    tabStage(heroBox, listBox),
    drawers.root,
  );
}
