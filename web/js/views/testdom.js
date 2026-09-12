/** 뷰 테스트용 가짜 DOM·캔버스 — **테스트 전용. 앱은 이 파일을 들여오지 않는다.**
 *
 * `js/views/`는 16,800줄인데 테스트가 없었다. 그 대부분은 DOM 조립이라 npm 의존
 * 0(폐쇄망 반입: `web/` 파일이 전부)을 지키면서 시험하려면 가짜 DOM이 필요하고,
 * 이 파일이 그것이다. `*.test.js`가 아니라 러너가 스위트로 잡지 않는다.
 *
 * ## `dom.test.js`의 스텁과 **일부러 따로 둔다**
 *
 * 그쪽은 "최소 가짜 document로 `el()`의 계약만" 검증한다 — el이 그 이상을 필요로
 * 하지 않는다는 것이 그 테스트의 주장이라, 풍부한 스텁으로 바꾸면 주장이 약해진다.
 * 이쪽은 반대로 **뷰가 실제로 그리게** 해야 해서 넉넉하다. 둘은 목적이 다르므로
 * 중복이 아니다 — 합치지 말 것.
 *
 * ## 기록하는 캔버스
 *
 * 픽셀을 견주지 않는다. `stroke()`·`fill()`·`fillText()`가 불린 **그 순간의 색·굵기·
 * 점선 패턴과 쌓인 경로**를 한 건으로 적어 둔다. 그래서 시험할 수 있는 것이 "무엇이
 * 어떻게 보이나"가 아니라 **"무엇을 그리기로 했나"**다 — 뷰에 남아 있는 판단이
 * 곧 그것이고, lib으로 뺄 수 없어 여기 남은 것도 그것이다.
 */

/** 그리기 한 건 — 색·굵기·점선은 **그 시점의 값을 박아** 둔다(나중에 바뀌어도 무관). */
class Op {
  constructor(kind, ctx, extra = {}) {
    this.kind = kind; // "stroke" | "fill" | "text" | "clear" | "strokeRect"
    this.strokeStyle = ctx.strokeStyle;
    this.fillStyle = ctx.fillStyle;
    this.lineWidth = ctx.lineWidth;
    this.dash = [...ctx._dash];
    Object.assign(this, extra);
  }
}

class FakeCtx {
  constructor(recorder) {
    this.ops = recorder;
    this.strokeStyle = "#000";
    this.fillStyle = "#000";
    this.lineWidth = 1;
    this.font = "";
    this.textAlign = "left";
    this._dash = [];
    this._path = []; // [{op:"move"|"line"|"arc", ...}]
  }

  // ---- 경로 쌓기 ----
  beginPath() { this._path = []; }
  moveTo(x, y) { this._path.push({ op: "move", x, y }); }
  lineTo(x, y) { this._path.push({ op: "line", x, y }); }
  arc(x, y, r, a0, a1) { this._path.push({ op: "arc", x, y, r, a0, a1 }); }
  rect(x, y, w, h) { this._path.push({ op: "rect", x, y, w, h }); }
  roundRect(x, y, w, h) { this._path.push({ op: "rect", x, y, w, h }); }
  closePath() {}
  setLineDash(d) { this._dash = [...(d ?? [])]; }

  // ---- 확정 ----
  stroke() { this.ops.push(new Op("stroke", this, { path: [...this._path] })); }
  fill() { this.ops.push(new Op("fill", this, { path: [...this._path] })); }
  fillText(text, x, y) { this.ops.push(new Op("text", this, { text: String(text), x, y })); }
  strokeRect(x, y, w, h) { this.ops.push(new Op("strokeRect", this, { x, y, w, h })); }
  fillRect(x, y, w, h) { this.ops.push(new Op("fill", this, { x, y, w, h, path: [] })); }
  clearRect(x, y, w, h) { this.ops.push(new Op("clear", this, { x, y, w, h })); }

  // ---- 계측 ----
  // 글자 폭은 **글자당 6 px 근사**다. 정확한 폭이 필요한 판단(줄바꿈·잘림)을 시험할
  // 생각이면 그 판단부터 lib으로 빼야 한다 — 여기서 폰트 metrics를 흉내 내면
  // 테스트가 스텁의 근사를 고정하게 되고, 그건 브라우저의 참을 고정한 것이 아니다.
  measureText(t) { return { width: String(t).length * 6 }; }
  scale() {}
  save() {}
  restore() {}
  translate() {}
}

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.nodeType = 1;
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.style = {};
    this.className = "";
    this.classList = {
      add: (...cs) => {
        this.className = [...new Set([...this.className.split(" ").filter(Boolean), ...cs])]
          .join(" ");
      },
      remove: (...cs) => {
        this.className = this.className.split(" ").filter((c) => c && !cs.includes(c)).join(" ");
      },
      contains: (c) => this.className.split(" ").includes(c),
      toggle: (c, on) => (on ? this.classList.add(c) : this.classList.remove(c)),
    };
    if (this.tagName === "CANVAS") {
      this._ops = [];
      this._ctx = new FakeCtx(this._ops);
    }
  }

  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] ?? []).filter((f) => f !== fn);
  }
  /** 등록된 리스너를 직접 부른다 — 스텁에는 버블링이 없다(있는 척하지 않는다). */
  emit(type, ev = {}) { for (const fn of this.listeners[type] ?? []) fn(ev); }

  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  append(...cs) { this.children.push(...cs); }
  appendChild(c) { this.children.push(c); return c; }
  replaceChildren(...cs) { this.children = [...cs]; }
  remove() {}
  focus() {}
  getContext() { return this._ctx; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 380, height: 380 }; }
  hasPointerCapture() { return false; }
  setPointerCapture() {}
  releasePointerCapture() {}

  /** 자손 전체의 텍스트 — 캡션·안내문이 실제로 나가는지 보는 데 쓴다. */
  get text() {
    return this.children
      .map((c) => (c?.nodeType === 3 ? c.data : c?.text ?? ""))
      .join("");
  }
  /** 태그로 자손 찾기 (얕은 재귀) — 스텁에 선택자 엔진은 없다. */
  find(tag) {
    const want = String(tag).toUpperCase();
    const out = [];
    const walk = (n) => {
      for (const c of n.children ?? []) {
        if (c?.nodeType === 1) { if (c.tagName === want) out.push(c); walk(c); }
      }
    };
    walk(this);
    return out;
  }
}

class FakeText {
  constructor(s) { this.nodeType = 3; this.data = s; }
  get text() { return this.data; }
}

/** 전역에 가짜 DOM을 깐다 — **뷰 모듈을 import 하기 전에** 부를 것.
 *
 *  뷰는 최상위에서 `document`를 만지지 않지만 `makeCanvas`가 `window.devicePixelRatio`를
 *  읽으므로 window도 함께 깐다. 되돌리는 함수를 돌려준다(한 파일에서 여러 스위트를
 *  돌릴 때 전역이 새지 않게).
 */
export function installDom() {
  const prev = { document: globalThis.document, window: globalThis.window };
  globalThis.document = {
    createElement: (t) => new FakeNode(t),
    createTextNode: (s) => new FakeText(s),
  };
  globalThis.window = { devicePixelRatio: 1 };
  return () => { globalThis.document = prev.document; globalThis.window = prev.window; };
}

/** 캔버스 노드가 기록한 그리기 목록 (`makeCanvas`가 돌려준 canvas를 넘긴다). */
export function opsOf(canvas) { return canvas._ops ?? []; }

/** 루트 조각 아래에서 첫 캔버스를 찾는다 — 뷰는 보통 조각 하나를 돌려준다. */
export function canvasIn(root) { return root.find("canvas")[0] ?? null; }

/** 색으로 거른 stroke 목록 — 뷰가 "무엇을 그리기로 했나"를 색 언어로 묻는다. */
export function strokesOf(canvas, color) {
  return opsOf(canvas).filter((o) => o.kind === "stroke" && o.strokeStyle === color);
}
