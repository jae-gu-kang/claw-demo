/** 헤더 기체 선택기 — 모든 탭의 계산이 쓰는 기체·형상 변형을 고른다 (06 §8).

**전환은 페이지를 다시 읽는다.** 기체에서 나온 상태가 탭마다 모듈에 산다 — 게인 카탈로그 캐시
(블록도·게인·Autocode·검증), 적용한 게인 표·SCAS·오토파일럿·작동기·항법 편집본, 탭 간 인계(영향성
진단·웨이포인트 초안·투어), 엔벨로프 프리필. 그것을 하나씩 구독해 비우면 비울 목록이 코드와 따로
늙고, 하나를 빠뜨리면 **A 기체의 게인 표로 B 기체를 계산**한다. 다시 읽기는 빠뜨릴 수가 없다. 대가는
저장하지 않은 편집·진행 화면이 사라지는 것이라 전환 전에 묻는다 — 서버 작업은 계속 돌고 결과는 결과
탭에 남는다.

선택 규칙(무엇을 저장하고 어느 요청에 싣나)은 lib/profile.js, 여기는 DOM뿐이다.
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import {
  EXAMPLE_ID, currentSelection, normalizeSelection, sameSelection, saveSelection, selectionProblem,
  setSelection,
} from "../lib/profile.js";
import { effectiveOf } from "../lib/profileform.js";

/** 브라우저 저장소 — 접근 자체가 예외인 환경(사생활 창·차단 설정)에서도 죽지 않는다. */
export function browserStorage() {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export const SWITCH_CONFIRM = "기체를 바꾸면 페이지를 다시 읽습니다 — 저장하지 않은 편집과 진행 화면이 "
  + "초기화됩니다(서버 작업은 계속되고 결과는 결과 탭에 남습니다). 바꿀까요?";

/** 기체 전환 — 묻고, 저장하고, 다시 읽는다. 돌려주는 것: {ok, reason}.
 *
 *  저장이 안 되면 **전환하지 않는다** — 다시 읽는 순간 선택이 사라져 예제 기체로 돌아가는데, 화면은
 *  바꿨다고 믿게 된다. */
export function switchTo(sel, {
  storage = browserStorage(), confirmFn = globalThis.confirm, reload = () => globalThis.location.reload(),
} = {}) {
  const norm = normalizeSelection(sel);
  if (!norm) return { ok: false, reason: "잘못된 기체 선택" };
  if (sameSelection(norm, currentSelection() ?? { id: EXAMPLE_ID })) return { ok: true, reason: null };
  if (confirmFn && !confirmFn(SWITCH_CONFIRM)) return { ok: false, reason: null };
  if (!storage || !saveSelection(storage, norm)) {
    return { ok: false, reason: "브라우저 저장소를 쓸 수 없어 기체 선택을 유지할 수 없습니다 — 전환하지 않았습니다" };
  }
  reload();
  return { ok: true, reason: null };
}

let box = null;
let notice = null; // 서버에서 사라진 선택을 예제로 되돌린 사유 — 이 페이지 수명 동안 헤더에 남긴다

function paint(list, error) {
  if (!box) return;
  const sel = currentSelection() ?? { id: EXAMPLE_ID, variant: null };
  if (error) {
    clear(box).append("기체 ", el("span", { class: "badge warn", title: error }, "목록 못 받음"));
    return;
  }
  const readable = list.filter((p) => !p.unreadable);
  const row = readable.find((p) => p.id === sel.id) ?? readable[0];
  const idSelect = el("select", {
    title: "모든 탭의 계산이 이 기체를 쓴다 — 바꾸면 페이지를 다시 읽는다",
    onchange: (e) => {
      const r = switchTo({ id: e.target.value, variant: null });
      if (!r.ok) {
        e.target.value = sel.id; // 취소·실패 — 화면을 실제 선택으로 되돌린다
        if (r.reason) globalThis.alert?.(r.reason);
      }
    },
  }, list.map((p) => el("option", {
    value: p.id, selected: p.id === sel.id, disabled: !!p.unreadable,
    title: p.unreadable ? p.reason : `${p.id} · 리비전 ${p.revision} · 지문 ${p.fingerprint}`,
  }, p.unreadable ? `${p.id} — 읽을 수 없음` : p.name)));
  const variants = row?.variants ?? [];
  const variantSelect = variants.length
    ? el("select", {
      title: "형상 변형 — 기체 문서의 일부 값을 덮어쓴 구성",
      onchange: (e) => {
        const r = switchTo({ id: sel.id, variant: e.target.value || null });
        if (!r.ok) {
          e.target.value = sel.variant ?? "";
          if (r.reason) globalThis.alert?.(r.reason);
        }
      },
    },
    el("option", { value: "", selected: !sel.variant }, "기본 형상"),
    variants.map((v) => el("option", { value: v.id, selected: v.id === sel.variant }, v.name)))
    : null;
  clear(box).append(
    el("a", { href: "#aircraft", title: "기체 탭 — 기체 문서 만들기·고치기" }, "기체"),
    idSelect,
    variantSelect,
    row?.is_example
      ? el("span", { class: "badge example", title: "엔진에 딸린 읽기 전용 예제 — 실기체 값이 아니다" }, "예제")
      : null,
    notice ? el("span", { class: "badge warn", title: notice }, "선택 복원") : null,
  );
}

/** 목록과 저장된 선택을 맞춘다 — 선택이 서버에서 사라졌으면(지워짐·형상 변형 삭제·휘발 저장소 재시작)
 *  예제로 되돌리고 사유를 남긴 뒤 지금 탭을 다시 그린다. 그 사이 나간 요청은 404로 실패했을 것이라 다시
 *  보내야 한다. mount만이 아니라 refresh(기체 탭의 저장·삭제 뒤)에서도 부른다 — 저장으로 고른 형상 변형이
 *  사라지고 사용자가 다시 읽기를 거절하면, 헤더는 「기본 형상」을 보이는데 요청은 없는 변형을 싣게 된다.
 *  돌려주는 것: 되돌렸으면 사유, 할 일이 없었으면 null. */
export function reconcile(list, {
  storage = browserStorage(),
  redraw = () => globalThis.dispatchEvent?.(new HashChangeEvent("hashchange")),
} = {}) {
  const problem = selectionProblem(list, currentSelection());
  if (!problem) return null;
  notice = `${problem} — 예제 기체로 되돌렸습니다. 공개 데모처럼 저장소가 재시작마다 비워지는 서버에서는 `
    + "저장한 기체가 사라질 수 있습니다.";
  setSelection(null);
  if (storage) saveSelection(storage, null);
  redraw();
  return notice;
}

/** 헤더에 붙인다 — 목록을 받아 선택과 맞춘 뒤(reconcile) 그린다. */
export async function mount() {
  box = document.getElementById("profile-pick");
  if (!box) return;
  box.textContent = "기체 …";
  let list;
  try {
    list = await api.get("/profiles");
  } catch (e) {
    paint(null, errorText(e));
    return;
  }
  reconcile(list);
  paint(list, null);
}

/** 기체 탭이 목록을 바꾼 뒤(생성·삭제·저장) 헤더를 다시 채운다. */
export async function refresh() {
  if (!box) return;
  try {
    const list = await api.get("/profiles");
    reconcile(list);
    paint(list, null);
  } catch (e) {
    paint(null, errorText(e));
  }
}

export const restoredNotice = () => notice;


let selectedDoc = null;
let selectedKey = null; // 받아 둔 문서가 **어느 선택**의 것인가 — 선택이 바뀌면 다시 받는다

/** 지금 계산에 쓰는 기체의 **적용 문서**(형상 변형 반영) — 화면 기본값(시뮬 폼의 레일·작동기 등)을 기체
 *  문서에서 읽는 자리. 고르지 않았으면 예제 기체다. 실패는 기억하지 않는다(다음에 다시 받는다).
 *
 *  받아 둔 문서는 선택(id·형상 변형)마다다. 첫 탭은 헤더가 선택을 맞추기(reconcile) **전에** 그려지므로,
 *  사라진 선택으로 받은 문서가 되돌린 선택에 그대로 쓰이면 화면 기본값은 딴 기체, 계산은 예제가 된다.
 *  같은 이유로 없는 형상 변형은 기본 문서로 조용히 바꾸지 않고 못 받은 것으로 친다. */
export function selectedDocument() {
  const sel = currentSelection() ?? { id: EXAMPLE_ID, variant: null };
  const key = `${sel.id}/${sel.variant ?? ""}`;
  if (!selectedDoc || selectedKey !== key) {
    selectedKey = key;
    const pending = api.get(`/profiles/${encodeURIComponent(sel.id)}`).then((body) => {
      const variants = Array.isArray(body.document?.variants) ? body.document.variants : [];
      if (sel.variant && !variants.some((v) => v?.id === sel.variant)) {
        throw new Error(`형상 변형이 없다: ${sel.id} / ${sel.variant}`);
      }
      return effectiveOf(body.document, sel.variant);
    });
    selectedDoc = pending;
    pending.catch(() => {
      if (selectedDoc === pending) selectedDoc = null;
    });
  }
  return selectedDoc;
}
