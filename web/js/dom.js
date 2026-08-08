/** DOM 조립 헬퍼 — 프레임워크 없이(no-build, eval-free) 뷰를 만드는 공통 어휘. */

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2), v);
    } else if (k === "class") {
      node.className = v;
    } else if (k === "value" || k === "checked" || k === "disabled" || k === "selected") {
      node[k] = v;
    } else {
      node.setAttribute(k, String(v));
    }
  }
  appendChildren(node, children);
  return node;
}

function appendChildren(node, children) {
  for (const c of children) {
    if (c == null || c === false) continue;
    if (Array.isArray(c)) appendChildren(node, c);
    else node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

/** 수치 표시 — null(NaN 직렬화)·"inf" 문자열 정책(M13 serialize) 인지. */
export function fmt(x, digits = 3) {
  if (x == null) return "—";
  if (x === "inf") return "∞";
  if (x === "-inf") return "−∞";
  if (typeof x !== "number") return String(x);
  if (Number.isInteger(x) && Math.abs(x) < 1e6) return String(x);
  return x.toPrecision(digits);
}

/** 판정 플래그 배지 — 3-상태 (true/false/null=미판정). */
export function flagBadge(v, textTrue = "OK", textFalse = "위반", textNa = "미판정") {
  const cls = v === true ? "ok" : v === false ? "bad" : "na";
  const text = v === true ? textTrue : v === false ? textFalse : textNa;
  return el("span", { class: `flag ${cls}` }, text);
}
