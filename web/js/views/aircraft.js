/** 기체 탭 (02 §8 0단계) — 기체 프로파일 목록·선택·복제·편집·내보내기/가져오기 (06 §8).

모든 탭의 계산이 **헤더에서 고른 기체**를 쓴다(lib/profile.js가 요청마다 싣는다). 이 탭은 그 기체
문서를 만들고 고치는 자리다. 문서는 서버가 검증해 리비전으로 쌓는다(02 §5.6) — 검증 규칙을 여기서
다시 적지 않는다: [검증]은 서버 `/profiles/validate`(저장과 같은 규칙)의 답을 경로째 보여 줄 뿐이다.

배치(06 §2): **목록이 전면**이고 문서·형상 변형·가져오기는 패널이다. 문서 패널은 절별 폼(views/profileform.js)과
JSON 글이 같은 문서를 고친다.

예제 기체는 엔진 패키지 데이터라 읽기 전용이다. 보여 주되 검증을 부르지 않는다(검증은 저장 규칙이라
예제 표시를 거부한다) — 고치려면 복제한다.
*/

import { ApiError, api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import {
  EXAMPLE_ID, cloneDocument, currentSelection, exportFileName, parseDocumentText, profileErrorText,
  saveSelection, setSelection,
} from "../lib/profile.js";
import { formUpdate } from "../lib/profileform.js";
import { renderProfileForm } from "./profileform.js";
import { browserStorage, refresh as refreshPicker, restoredNotice, switchTo } from "./profilepick.js";
import { createDrawers, drawerSection, tabStage, tabTop } from "./stage.js";

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

export function render() {
  const statusLine = el("p", { class: "hint", style: "margin:4px 0 0" });
  const errBox = el("div");
  const noticeBox = el("div");
  const listBox = el("div");
  const docBox = el("div");
  const variantBox = el("div");
  const importBox = el("div");

  const showError = (e) => clear(errBox).append(
    el("div", { class: "error-box" }, typeof e === "string" ? e : failText(e)));

  const paintNotices = () => {
    const restored = restoredNotice();
    clear(noticeBox).append(
      restored ? el("p", { class: "notice" }, restored) : null,
      volatile
        ? el("p", { class: "notice" },
          "이 서버는 기체 저장소가 재시작마다 비워집니다(공개 데모) — 저장한 기체는 재배포·절전 복귀 때 "
          + "사라집니다. 남겨야 할 기체는 [내보내기]로 JSON을 받아 두고 「가져오기」 패널로 되살립니다. "
          + "예제 기체는 사라지지 않습니다.")
        : null,
    );
  };

  const load = async () => {
    clear(errBox);
    statusLine.textContent = "불러오는 중…";
    try {
      const [items, health] = await Promise.all([
        api.get("/profiles"), api.get("/health").catch(() => null)]);
      list = items;
      volatile = !!health?.profile_store?.volatile;
      statusLine.textContent = `${list.length}대 · 지금 계산에 쓰는 기체: ${selectedId()}`
        + (currentSelection()?.variant ? ` / ${currentSelection().variant}` : "");
      paintNotices();
      paintList();
      drawers.refresh();
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
        next.check = { ok: true, lines: [`리비전 ${body.revision}로 저장했습니다 — 지문 ${body.fingerprint}`] };
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
    } catch (e) {
      showError(e);
    }
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
      { key: "import", label: "가져오기", group: "반입",
        title: "내보내 둔 기체 JSON을 새 기체로", build: () => [
          drawerSection("가져오기", null, importBox)] },
    ],
  });

  if (list) paintList();
  paintNotices();
  paintDoc();
  paintVariants();
  paintImport();
  load();

  return el("div", { class: "tab-page aircraft-page" },
    tabTop({
      title: "기체",
      lead: "모든 탭의 계산이 헤더에서 고른 기체를 씁니다 — 여기서는 그 기체 문서를 만들고 고칩니다. "
        + "예제는 읽기 전용이라 복제해서 고칩니다.",
      actions: [el("button", { onclick: load }, "새로고침")],
      extra: [statusLine, errBox, noticeBox],
    }),
    tabStage(listBox),
    drawers.root,
  );
}
