/** 기체 문서 절별 폼 — 서버 폼 서술(`GET /profiles/_form`)대로 칸을 세운다 (06 §8).

칸의 이름·단위·형식·선택지는 서버가 준다(엔진 `claw.profile.form`). 여기는 DOM 조립과 "입력 → 문서 값"
배선뿐이고, 그 규칙(포인터·형상 변형 덮어쓰기·칸 해석·쓰기 판단)은 `lib/profileform.js`에 있다. 판정(범위·
서열·대칭)은 적지 않는다 — [검증]·[저장] 때 서버 검증기가 경로와 함께 말한다.

**쓰기는 `ctx.update(fn)`이다** — fn은 **그 순간의 문서**를 받아 새 문서를 돌려준다. 그린 때의 사본으로
문서를 통째로 만들지 않는다: 폼은 수치 칸을 고칠 때마다 다시 그리지 않으므로(아래) 그린 때의 사본은 곧
낡고, 그 사본으로 [행 추가]를 만들면 방금 친 값이 사라진다.

**수치 칸의 쓰기는 다시 그리지 않는다.** 칸이 이미 친 값을 보이고 있다. 칸의 change는 blur, 곧 [저장]의
mousedown에 오므로 그때 다시 그리면 누르던 버튼이 사라지고 포커스가 엉뚱한 칸으로 간다. 대칭 행렬의 마주
보는 칸과 형상 변형의 「덮어씀」 표시는 그 자리에서 고친다. 행 추가·없음·형식 변경처럼 모양이 바뀌는 쓰기만
`{structural: true}`로 넘겨 호출측이 다시 그린다 — 클릭이 끝난 뒤라 잃을 것이 없다.

「없음」(null)은 체크로만 고른다 — 빈 칸을 null로 읽으면 지운 줄 모른다. 비어 있던 묶음을 만들 때와
추진·작동기 형식을 바꿀 때는 **누른 뒤에만** 예제·레지스트리 기본값으로 채운다.
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import {
  FormNotice, aeroTableFromParsed, tableSummary,
  allowedInputs, applyPatch, clearInPatch, effectiveOf, formatNum, getAt, inputsText, isUnder,
  machTableFromParsed, paramsFromDefaults, parseInputs, parseNum, parseNumList, patchOwner, patchedBelow,
  sectionOverrides, setAt, setMatrixCell, tableFromRows, tableRows, writeValues,
} from "../lib/profileform.js";
import { groupFields, schemaFields } from "../lib/schemaform.js";

// 열어 둔 절 — 모양이 바뀌어 다시 그려도 닫히지 않게 (모듈 스코프 규약)
const openSections = new Set();
// 그린 차례 — 응답을 기다리는 쓰기(CSV 표 반입)가 행 번호를 들고 있다. 그사이 폼을 다시 그렸으면(항 추가·삭제 등
// 모양이 바뀐 쓰기는 반드시 다시 그린다) 그 번호가 다른 항을 가리킬 수 있어 쓰지 않는다
let renderSeq = 0;

const clone = (v) => JSON.parse(JSON.stringify(v));
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const STRUCTURAL = { structural: true };

/** ctx: {spec, doc, editVariant, example, readOnly, getSchema(category, name),
 *        update(fn, {structural?, async?, editVariant?}), setEditVariant(id)} */
export function renderProfileForm(ctx) {
  const seq = ++renderSeq;
  const { spec, doc, readOnly } = ctx;
  const variants = Array.isArray(doc.variants) ? doc.variants : [];
  const variant = ctx.editVariant == null ? null : variants.find((v) => v?.id === ctx.editVariant) ?? null;
  const variantId = variant?.id ?? null;
  const patch = variant?.patch ?? null;
  const applied = patch ? applyPatch(doc, patch) : { doc, issues: [] };
  const shown = applied.doc;
  const dis = readOnly ? true : undefined;
  const rows = new Map(); // 칸 경로 → {row, label} — 다시 그리지 않고 「덮어씀」을 붙이는 자리

  // ── 쓰기 ─────────────────────────────────────────────────────────────────
  /** 형상 변형 편집 중 쓴 칸에 「덮어씀」을 붙인다 — 수치 칸은 다시 그리지 않으므로 그 자리에서 */
  const markOverridden = (path) => {
    if (!variantId) return;
    let best = null;
    for (const [fp, r] of rows) if (isUnder(path, fp) && (!best || fp.length > best[0].length)) best = [fp, r];
    if (best && !best[1].row.classList.contains("ov")) {
      // 「하위 N곳 덮어씀」은 이 쓰기가 그 하위 치환을 녹였으므로 더는 참이 아니다 — 지우고 새로 단다
      best[1].row.classList.remove("ov-part");
      for (const b of best[1].label.querySelectorAll?.(".pf-badge") ?? []) b.remove();
      best[1].row.classList.add("ov");
      best[1].label.append(el("span", { class: "pf-badge", title: "다시 그리면 [해제]가 선다" }, "덮어씀"));
    }
  };
  /** 경로의 **그 순간** 값(편집 대상 기준) → 새 값. */
  const edit = (path, fn, opts = {}) => {
    ctx.update((cur) => writeValues(cur, variantId, [[path, fn(getAt(effectiveOf(cur, variantId), path))]]), opts);
    if (!opts.structural) markOverridden(path);
  };
  const put = (path, value, opts) => edit(path, () => value, opts);
  const clearOverride = (path) => ctx.update((cur) => {
    const i = (cur.variants ?? []).findIndex((v) => v?.id === variantId);
    if (i < 0) throw new Error(`형상 변형이 문서에 없습니다: ${variantId}`);
    return setAt(cur, `/variants/${i}/patch`, clearInPatch(cur.variants[i].patch, path));
  }, STRUCTURAL);

  const bad = (node, msg) => {
    node.classList.add("bad");
    node.title = msg;
  };
  // 받아들인 값이면 오류 표시·「값을 넣어야 없음이 풀린다」 표시를 지운다(다시 그리지 않으므로 그 자리에서)
  const ok = (node, title = "") => {
    node.classList.remove("bad");
    node.title = title ?? "";
    node.closest?.(".pf-row")?.classList.remove("pf-need");
  };
  const numInput = (value, onValue, { title } = {}) => el("input", {
    class: "pf-num", value: formatNum(value), disabled: dis, spellcheck: "false", title,
    onchange: (e) => {
      const r = parseNum(e.target.value);
      if (r.error) {
        bad(e.target, r.error);
        return;
      }
      ok(e.target, title);
      onValue(r.value);
    },
  });
  const btn = (label, onclick, title) => (readOnly ? null : el("button", { class: "pf-mini", onclick, title }, label));

  // 「없음」 체크 — 켜면 null을 쓴다(모양이 바뀐다). 끄면 값을 넣어야 풀린다는 표시만 한다
  const nullToggle = (f, v) => {
    if (!f.nullable) return { node: null, box: null };
    const box = el("input", {
      type: "checkbox", checked: v === null, disabled: dis,
      onchange: (e) => {
        if (e.target.checked) put(f.path, null, STRUCTURAL);
        else e.target.closest?.(".pf-row")?.classList.add("pf-need");
      },
    });
    return { node: el("label", { class: "pf-null" }, box, " 없음"), box };
  };

  // 문서 값이 선택지 밖이면 첫 선택지를 고른 척하지 않고 그 값을 그대로 보인다
  const offList = (choices, v) => (v != null && !choices.includes(v)
    ? el("option", { value: v, selected: true }, `${v} (허용 목록 밖 — 검증에서 거부된다)`) : null);

  // ── 칸 편집기 ────────────────────────────────────────────────────────────
  const editors = {
    number: (f, v) => {
      const tog = nullToggle(f, v);
      return el("span", {}, numInput(v, (x) => {
        put(f.path, x);
        if (tog.box) tog.box.checked = false;
      }), tog.node);
    },

    range: (f, v) => {
      const tog = nullToggle(f, v);
      const commitRange = () => {
        const a = parseNum(lo.value);
        const b = parseNum(hi.value);
        if (a.error || b.error) return; // 두 끝이 다 들어와야 쓴다 — 한 끝만 쓰면 [lo, null]이 된다
        put(f.path, [a.value, b.value]);
        if (tog.box) tog.box.checked = false;
      };
      const lo = numInput(v?.[0], commitRange);
      const hi = numInput(v?.[1], commitRange);
      return el("span", {}, "[", lo, " , ", hi, "]", tog.node);
    },

    vec3: (f, v) => {
      const cells = [];
      for (let i = 0; i < 3; i += 1) {
        cells.push(numInput(v?.[i], (x) => {
          edit(f.path, (cur) => (Array.isArray(cur) ? cur : [0, 0, 0]).map((y, k) => (k === i ? x : y)));
          // 비어 있던 벡터면 나머지 칸이 0으로 들어갔다 — 칸도 그렇게 보인다
          for (const c of cells) if (c.value === "") c.value = "0";
        }));
      }
      return el("span", {}, "[", cells[0], " , ", cells[1], " , ", cells[2], "]");
    },

    mat3: (f, v) => {
      const cells = [];
      for (let i = 0; i < 3; i += 1) {
        for (let j = 0; j < 3; j += 1) {
          cells.push(numInput(v?.[i]?.[j], (x) => {
            edit(f.path, (cur) => setMatrixCell(cur, i, j, x, { symmetric: f.symmetric }));
            if (f.symmetric && i !== j) { // 다시 그리지 않으니 그 자리에서
              cells[j * 3 + i].value = formatNum(x);
              ok(cells[j * 3 + i]);
            }
          }, { title: f.symmetric && i !== j ? `대칭 행렬 — [${j},${i}]도 같이 바뀐다` : null }));
        }
      }
      return el("div", { class: "pf-grid", style: "grid-template-columns:repeat(3,auto)" }, cells);
    },

    rows3: (f, v) => el("div", {},
      el("table", { class: "pf-table" }, el("tbody", {}, (Array.isArray(v) ? v : []).map((row, i) => el("tr", {},
        el("td", { class: "hint" }, `#${i + 1}`),
        (Array.isArray(row) ? row : []).map((c, j) => el("td", {}, numInput(c, (x) => edit(f.path,
          (cur) => cur.map((r, k) => (k === i ? r.map((y, m) => (m === j ? x : y)) : r)))))),
        el("td", {}, btn("삭제", () => edit(f.path, (cur) => cur.filter((_, k) => k !== i), STRUCTURAL))))))),
      btn("행 추가", () => edit(f.path, (cur) => [...(cur ?? []), [...((cur ?? []).at(-1) ?? [0, 0, 0])]], STRUCTURAL),
        "마지막 행을 복사해 붙인다")),

    table_mach: (f, v) => tableEditor(f, v),

    choice: (f, v) => el("select", {
      disabled: dis,
      onchange: (e) => {
        if (f.path === "/aero/form") changeAeroForm(e.target.value, e.target, v);
        else put(f.path, e.target.value);
      },
    }, f.choices.map((c) => el("option", { value: c, selected: c === v }, c)), offList(f.choices, v)),

    // 고른 순서·목록 밖 이름을 보존한다 — 한 칸을 켜고 끄는 것이 목록 전체를 다시 줄 세우면 안 한 변경이 생긴다
    multichoice: (f, v) => {
      const cur0 = Array.isArray(v) ? v : [];
      const outside = cur0.filter((c) => !f.choices.includes(c));
      return el("div", { class: "pf-multi" }, [...f.choices, ...outside].map((c) => el("label", {
        title: f.choices.includes(c) ? null : "허용 목록 밖 — 검증에서 거부된다",
      },
      el("input", {
        type: "checkbox", checked: cur0.includes(c), disabled: dis,
        onchange: (e) => {
          const on = e.target.checked;
          edit(f.path, (cur) => {
            const arr = Array.isArray(cur) ? cur : [];
            return on ? [...arr.filter((x) => x !== c), c] : arr.filter((x) => x !== c);
          });
        },
      }), ` ${c}${f.choices.includes(c) ? "" : " (목록 밖)"}`)));
    },

    numlist: (f, v) => el("input", {
      class: "pf-wide", value: Array.isArray(v) ? v.join(", ") : formatNum(v), disabled: dis, spellcheck: "false",
      onchange: (e) => {
        const r = parseNumList(e.target.value);
        if (r.error) {
          bad(e.target, r.error);
          return;
        }
        ok(e.target);
        put(f.path, r.value);
      },
    }),

    text_json: (f, v) => el("textarea", {
      class: "pf-json", disabled: dis, spellcheck: "false", value: JSON.stringify(v, null, 1),
      onchange: (e) => {
        let parsed;
        try {
          parsed = JSON.parse(e.target.value);
        } catch (err) {
          bad(e.target, `JSON이 아닙니다 — ${err.message}`);
          return;
        }
        ok(e.target);
        put(f.path, parsed);
      },
    }),

    terms: (f, v) => termsEditor(f, v),
    registry: (f, v) => registryEditor(f.path, f.category, f.name, f.reserved ?? [], v),
    component: (f, v) => componentEditor(f, v),
  };

  // 표 — 행 편집 + CSV 반입(서버 판독, 파일을 올리지 않고 글을 보낸다)
  const tableEditor = (f, v) => {
    const rowsOf = (t) => tableRows(t);
    const ext = v?.extrapolate ?? f.extrapolate?.[0];
    const setRows = (fn, opts) => edit(f.path, (cur) => tableFromRows(fn(rowsOf(cur)), cur?.extrapolate ?? ext), opts);
    const csvBox = el("div");
    const col = el("input", { class: "pf-num", value: "value", title: "값 열 이름" });
    const text = el("textarea", { class: "pf-json", placeholder: "mach,value\n0.1,0.40\n0.5,0.33" });
    const file = el("input", {
      type: "file", accept: ".csv,text/csv,text/plain",
      onchange: (e) => {
        const fl = e.target.files?.[0];
        if (!fl) return;
        const r = new FileReader();
        r.onload = () => { text.value = String(r.result ?? ""); };
        r.readAsText(fl);
      },
    });
    const readCsv = async () => {
      clear(csvBox);
      try {
        const parsed = await api.post("/profiles/parse-table",
          { csv_text: text.value, axis_cols: ["mach"], value_col: col.value.trim(), extrapolate: ext });
        const t = machTableFromParsed(parsed, ext);
        if (t.error) csvBox.append(el("p", { class: "error-box" }, t.error));
        else put(f.path, t.value, { structural: true, async: true });
      } catch (e) {
        csvBox.append(el("p", { class: "error-box" }, errorText(e)));
      }
    };
    const shownRows = rowsOf(v);
    return el("div", {},
      el("table", { class: "pf-table" },
        el("thead", {}, el("tr", {}, el("th", {}, "mach"), el("th", {}, `${f.value_label ?? "값"} [${f.unit}]`), el("th", {}, ""))),
        el("tbody", {}, shownRows.map((r, i) => el("tr", {},
          el("td", {}, numInput(r.mach, (x) => setRows((rs) => rs.map((q, k) => (k === i ? { ...q, mach: x } : q))))),
          el("td", {}, numInput(r.value, (x) => setRows((rs) => rs.map((q, k) => (k === i ? { ...q, value: x } : q))))),
          el("td", {}, btn("삭제", () => setRows((rs) => rs.filter((_, k) => k !== i), STRUCTURAL))))))),
      btn("행 추가", () => setRows((rs) => [...rs, { ...(rs.at(-1) ?? { mach: 0, value: 0 }) }], STRUCTURAL),
        "마지막 행을 복사해 붙인다 — 마하는 오름차순이어야 한다"),
      el("span", { class: "hint", style: "margin-left:8px" }, `외삽 ${ext}`),
      readOnly ? null : el("details", { class: "pf-csv" }, el("summary", {}, "CSV에서 읽기"),
        el("p", { class: "hint" }, "긴 형식 CSV — 머리줄에 mach와 값 열 이름. 값 열 이름을 적고 붙여 넣거나 파일을 고른다."),
        el("label", { class: "field" }, "값 열", col), file, text,
        el("button", { onclick: readCsv }, "표로 읽기"), csvBox));
  };

  // 계수 형식을 바꾸면 계수 이름이 바뀐다 — 같은 이름(CY·Cl·Cm·Cn)의 항만 남긴다
  const changeAeroForm = (next, select, prev) => {
    const names = spec.aero_forms[next] ?? [];
    const dropped = Object.keys(getAt(shown, "/aero/coefficients") ?? {}).filter((k) => !names.includes(k));
    if (!globalThis.confirm?.(`계수 형식을 ${next}로 바꿉니다 — ${dropped.join("·") || "없음"} 항은 지우고, 새 이름 계수는 빈 항으로 둡니다. 바꿀까요?`)) {
      select.value = prev;
      return;
    }
    ctx.update((cur) => {
      const coefs = getAt(effectiveOf(cur, variantId), "/aero/coefficients") ?? {};
      return writeValues(cur, variantId, [["/aero/form", next],
        ["/aero/coefficients", Object.fromEntries(names.map((n) => [n, clone(coefs[n] ?? [])]))]]);
    }, STRUCTURAL);
  };

  // 공력 항 k를 표로 — 긴 형식 CSV(머리줄 = 축 이름들 + 값 열)를 서버가 판독한다(파일을 올리지 않고 글을 보낸다).
  // 축 이름은 폼 서술의 table_axes 중에서 — 틀리면 반입 전에 사유를 말하고, 격자 누락·중복은 서버가 말한다
  const tableImport = (coef, onK, label) => {
    const axesIn = el("input", { class: "pf-wide", value: "alpha, mach",
      title: `축 열 이름 — ${(spec.table_axes ?? []).join(", ")} 중에서, data 중첩 순서가 된다` });
    const valueIn = el("input", { class: "pf-num", value: coef, title: "값 열 이름" });
    const extSel = el("select", {}, (spec.table_policies ?? ["clip"]).map((pol) => el("option", { value: pol }, pol)));
    const text = el("textarea", { class: "pf-json", placeholder: `alpha,mach,${coef}\n0.0,0.3,0.10\n0.1,0.3,0.45` });
    const file = el("input", {
      type: "file", accept: ".csv,text/csv,text/plain",
      onchange: (e) => {
        const fl = e.target.files?.[0];
        if (!fl) return;
        const r = new FileReader();
        r.onload = () => { text.value = String(r.result ?? ""); };
        r.readAsText(fl);
      },
    });
    const out = el("div");
    const read = async () => {
      clear(out);
      try {
        const parsed = await api.post("/profiles/parse-table", {
          csv_text: text.value, axis_cols: parseInputs(axesIn.value), value_col: valueIn.value.trim(),
          extrapolate: extSel.value,
        });
        const k = aeroTableFromParsed(parsed, spec.table_axes);
        if (k.error) {
          out.append(el("p", { class: "error-box" }, k.error));
        } else if (seq !== renderSeq) {
          // 이 칸은 이미 화면에 없다 — 사유는 새로 그린 폼의 오류 줄로 낸다(다른 기체를 열었으면 그 사유가 대신 선다)
          ctx.update(() => {
            throw new FormNotice("표를 읽는 사이 폼이 다시 그려져(항 추가·삭제·검증 등) 어느 항인지 확실하지 않아"
              + " 표를 넣지 않았습니다 — 그 항에서 다시 반입하세요");
          }, { structural: true, async: true });
        } else {
          onK(k.value);
        }
      } catch (e) {
        out.append(el("p", { class: "error-box" }, errorText(e)));
      }
    };
    return el("details", { class: "pf-csv" }, el("summary", {}, label),
      el("label", { class: "field" }, "축 열", axesIn), el("label", { class: "field" }, "값 열", valueIn),
      el("label", { class: "field" }, "외삽", extSel), file, text,
      el("button", { onclick: read }, "표로 읽기"), out);
  };

  // 공력 계수 항 — 계수마다 [k(수치 또는 표), 입력들, 섭동 태그] 행
  const termsEditor = (f, v) => {
    const form = getAt(shown, "/aero/form");
    const names = spec.aero_forms[form] ?? Object.keys(v ?? {});
    const tags = Object.keys(spec.dispersion_tags ?? {});
    const setCoef = (name, fn, opts) => edit(f.path, (cur) => ({ ...clone(cur ?? {}), [name]: fn((cur ?? {})[name] ?? []) }), opts);
    return el("div", {}, names.map((name) => {
      const terms = Array.isArray(v?.[name]) ? v[name] : [];
      const allowed = allowedInputs(spec, form, name);
      return el("div", { class: "pf-coef" },
        el("div", { class: "pf-group-head" }, name, el("span", { class: "hint" }, `입력: ${allowed.join(" · ")}`)),
        el("table", { class: "pf-table" },
          el("thead", {}, el("tr", {}, el("th", {}, "k"), el("th", {}, "입력들(곱)"), el("th", {}, "섭동 태그"), el("th", {}, ""))),
          el("tbody", {}, terms.map((t, i) => {
            const setTerm = (part, opts) => setCoef(name, (ts) => ts.map((x, k) => (k === i ? { ...x, ...part } : x)), opts);
            const toTable = (k) => setTerm({ k }, { structural: true, async: true });
            return el("tr", {},
              el("td", {}, typeof t?.k === "number"
                ? el("div", {}, numInput(t.k, (x) => setTerm({ k: x })),
                  readOnly ? null : tableImport(name, toTable, "표로 반입"))
                : tableSummary(t?.k)
                  ? el("div", {}, el("span", { class: "hint" }, tableSummary(t.k)),
                    readOnly ? null : tableImport(name, toTable, "다시 반입"),
                    btn("수치로", () => {
                      const v = parseNum(globalThis.prompt?.("이 항의 표를 수치 k로 바꿉니다 — 값", "0") ?? "");
                      if (!v.error) setTerm({ k: v.value }, STRUCTURAL);
                    }, "표를 버리고 상수 k로"))
                  : el("span", { class: "error-box" }, "알 수 없는 k — JSON 글에서 고친다")),
              el("td", {}, el("input", {
                class: "pf-wide", value: inputsText(t?.inputs), disabled: dis, spellcheck: "false",
                title: `허용: ${allowed.join(", ")} — 빈 칸이면 상수항`,
                onchange: (e) => setTerm({ inputs: parseInputs(e.target.value) }),
              })),
              el("td", {}, el("select", { disabled: dis, onchange: (e) => setTerm({ dispersion: e.target.value || null }) },
                el("option", { value: "", selected: t?.dispersion == null }, "없음"),
                tags.map((g) => el("option", { value: g, selected: t?.dispersion === g },
                  `${g} (${spec.dispersion_tags[g].coef}·${spec.dispersion_tags[g].input})`)))),
              el("td", {}, btn("삭제", () => setCoef(name, (ts) => ts.filter((_, k) => k !== i), STRUCTURAL))));
          }))),
        btn("항 추가", () => setCoef(name, (ts) => [...ts, { k: 0, inputs: [], dispersion: null }], STRUCTURAL)));
    }),
    // 이 형식에 없는 계수 — 숨기면 다음 편집에 그대로 실려 저장이 거부되는데 화면은 이유를 못 보인다
    Object.keys(v ?? {}).filter((k) => !names.includes(k)).map((k) => el("div", { class: "error-box" },
      `계수 형식 ${form}에 없는 계수 ${k} — 검증에서 거부된다 `,
      btn("지우기", () => edit(f.path, (cur) => Object.fromEntries(Object.entries(clone(cur ?? {})).filter(([n]) => n !== k)), STRUCTURAL)))));
  };

  // 레지스트리 파라미터 — 이름·설명·단위는 레지스트리 스키마가 준다 (블록도 파라미터 폼과 같은 원천)
  const registryEditor = (path, category, name, reserved, v) => {
    const box = el("div", { class: "hint" }, `${category}/${name} 파라미터 서술을 불러오는 중…`);
    ctx.getSchema(category, name).then((schema) => {
      const fields = schemaFields(schema).filter((x) => !reserved.includes(x.name));
      const known = new Set(fields.map((x) => x.name));
      const stray = Object.keys(v ?? {}).filter((k) => !known.has(k));
      clear(box).className = "";
      box.append(...groupFields(`${category}/${name}`, fields).map((g) => el("div", { class: "pf-reg" },
        g.title ? el("div", { class: "pf-group-head" }, g.title) : null,
        g.fields.map((x) => el("label", { class: "pf-param", title: x.desc },
          el("span", {}, x.name, x.unit ? el("span", { class: "pf-unit" }, `[${x.unit}]`) : null),
          // 파라미터 객체째 쓴다 — 문서에 빠진 파라미터(JSON 글로 지운 것)도 칸에서 다시 채울 수 있게
          numInput(v?.[x.name], (val) => edit(path, (cur) => ({ ...clone(cur ?? {}), [x.name]: val }))),
          el("span", { class: "hint" }, x.desc))))),
      stray.length ? el("p", { class: "error-box" }, `이 형식에 없는 파라미터: ${stray.join(", ")} — 검증에서 거부된다`) : null);
    }).catch((e) => {
      clear(box).append(el("span", { class: "error-box" }, `파라미터 서술을 못 받았습니다 — ${errorText(e)} (JSON 글에서 고칠 수 있다)`));
    });
    return box;
  };

  const componentEditor = (f, v) => el("div", {},
    el("label", { class: "field" }, "형식", el("select", {
      disabled: dis,
      onchange: async (e) => {
        const type = e.target.value;
        if (!globalThis.confirm?.(`형식을 ${type}로 바꿉니다 — 파라미터를 그 형식의 레지스트리 기본값으로 채웁니다. 기체 값으로 고치세요. 바꿀까요?`)) {
          e.target.value = v?.type;
          return;
        }
        try {
          const schema = await ctx.getSchema(f.category, type);
          put(f.path, { type, params: paramsFromDefaults(schemaFields(schema), f.reserved ?? []) },
            { structural: true, async: true });
        } catch (err) {
          e.target.value = v?.type;
          globalThis.alert?.(`파라미터 서술을 못 받아 형식을 바꾸지 않았습니다 — ${errorText(err)}`);
        }
      },
    }, (spec.registry?.[f.category] ?? []).map((t) => el("option", { value: t, selected: t === v?.type }, t)),
    offList(spec.registry?.[f.category] ?? [], v?.type))),
    v?.type ? registryEditor(`${f.path}/params`, f.category, v.type, f.reserved ?? [], v.params) : null);

  // ── 덮어쓰기 표시 ─────────────────────────────────────────────────────────
  const overrideInfo = (f) => {
    if (!patch) return { cls: "", badge: null };
    const owner = patchOwner(patch, f.path);
    const below = patchedBelow(patch, f.path);
    if (owner === f.path) {
      return { cls: " ov", badge: el("span", { class: "pf-badge" }, "덮어씀",
        btn("해제", () => clearOverride(f.path), "이 경로의 덮어쓰기를 지워 기본 문서 값으로 되돌린다")) };
    }
    if (owner) return { cls: " ov", badge: el("span", { class: "pf-badge", title: `해제하려면 ${owner}의 덮어쓰기를 지운다` }, `상위 ${owner} 덮어씀`) };
    if (below.length) return { cls: " ov-part", badge: el("span", { class: "pf-badge", title: below.join("\n") }, `하위 ${below.length}곳 덮어씀`) };
    return { cls: "", badge: null };
  };

  const row = (f) => {
    if (f.kind === "group") return groupRow(f);
    const value = getAt(shown, f.path);
    const ov = overrideInfo(f);
    const editor = editors[f.kind];
    const label = el("div", { class: "pf-label" }, f.label,
      f.unit && f.unit !== "-" ? el("span", { class: "pf-unit" }, `[${f.unit}]`) : null,
      ov.badge,
      f.help ? el("div", { class: "hint" }, f.help) : null);
    const node = el("div", { class: `pf-row${ov.cls}`, "data-pf-path": f.path }, label,
      el("div", { class: "pf-edit" }, value === undefined
        ? el("span", { class: "error-box" }, `문서에 없는 경로: ${f.path}`)
        : editor ? editor(f, value) : el("span", { class: "hint" }, `모르는 칸 형식 ${f.kind} — JSON 글에서 고친다`)));
    rows.set(f.path, { row: node, label });
    return node;
  };

  const groupRow = (f) => {
    const value = getAt(shown, f.path);
    const ov = overrideInfo(f);
    const exampleValue = ctx.example ? getAt(ctx.example, f.path) : undefined;
    const head = el("div", { class: "pf-group-head" }, f.label, ov.badge,
      f.help ? el("span", { class: "hint" }, f.help) : null);
    if (value === null) {
      head.append(el("span", { class: "hint" }, "없음"),
        exampleValue != null ? btn("예제 값으로 시작", () => {
          if (globalThis.confirm?.(`「${f.label}」을 예제 기체 값으로 채워 만듭니다 — 실기체 값으로 고치세요. 만들까요?`)) {
            put(f.path, clone(exampleValue), STRUCTURAL);
          }
        }, "예제 기체의 같은 자리 값으로 채운다 — 누를 때만 채운다") : null);
      return el("div", { class: `pf-group${ov.cls}`, "data-pf-path": f.path }, head);
    }
    if (f.nullable) {
      head.append(btn("없음으로", () => {
        if (globalThis.confirm?.(`「${f.label}」을 없음으로 둡니다 — 안의 값이 지워집니다. 둘까요?`)) put(f.path, null, STRUCTURAL);
      }));
    }
    const node = el("div", { class: `pf-group${ov.cls}`, "data-pf-path": f.path }, head, ...f.fields.map(row));
    rows.set(f.path, { row: node, label: head });
    return node;
  };

  // ── 머리: 이름표·편집 대상 ────────────────────────────────────────────────
  const addVariant = () => {
    const id = globalThis.prompt?.("새 형상 변형 id (영문·숫자·_·-, 1~64자)", `variant-${variants.length + 1}`)?.trim();
    if (!id) return;
    if (!ID_RE.test(id) || variants.some((v) => v?.id === id)) {
      globalThis.alert?.(`쓸 수 없는 id입니다: ${id} (형식이 틀렸거나 이미 있다)`);
      return;
    }
    const name = globalThis.prompt?.("형상 변형 이름", id);
    if (name == null) return;
    ctx.update((cur) => setAt(cur, "/variants", [...cur.variants, { id, name: name.trim() || id, patch: {} }]),
      { structural: true, editVariant: id });
  };
  const variantIndex = (cur) => {
    const i = (cur.variants ?? []).findIndex((v) => v?.id === variantId);
    if (i < 0) throw new Error(`형상 변형이 문서에 없습니다: ${variantId}`);
    return i;
  };
  const renameVariant = () => {
    const name = globalThis.prompt?.("형상 변형 이름", variant.name);
    if (name?.trim()) ctx.update((cur) => setAt(cur, `/variants/${variantIndex(cur)}/name`, name.trim()), STRUCTURAL);
  };
  const removeVariant = () => {
    if (!globalThis.confirm?.(`형상 변형 「${variant.name}」을 지웁니다 — 덮어쓴 ${Object.keys(patch).length}곳도 사라집니다. 지울까요?`)) return;
    ctx.update((cur) => setAt(cur, "/variants", cur.variants.filter((v) => v?.id !== variantId)),
      { structural: true, editVariant: null });
  };

  const meta = el("div", { class: "pf-meta" },
    el("label", { class: "field" }, "id", el("input", { value: doc.id, disabled: true, title: "id는 바꿀 수 없다 — 복제해서 새 id로 만든다" })),
    el("label", { class: "field grow" }, "이름", el("input", {
      value: doc.name ?? "", disabled: readOnly || patch ? true : undefined,
      onchange: (e) => {
        const name = e.target.value;
        ctx.update((cur) => setAt(cur, "/name", name));
      },
    })),
    el("label", { class: "field grow" }, "설명", el("input", {
      value: doc.description ?? "", disabled: readOnly || patch ? true : undefined,
      onchange: (e) => {
        const text = e.target.value;
        ctx.update((cur) => setAt(cur, "/description", text));
      },
    })));

  const vbar = el("div", { class: "pf-vbar" },
    el("span", {}, "편집 대상"),
    el("select", { onchange: (e) => ctx.setEditVariant(e.target.value || null) },
      el("option", { value: "", selected: !variantId }, "기본 문서"),
      variants.map((v) => el("option", { value: v?.id, selected: v?.id === variantId }, `형상 변형 · ${v?.name} (${v?.id})`))),
    btn("새 형상 변형", addVariant),
    variantId ? btn("이름 바꾸기", renameVariant) : null,
    variantId ? btn("변형 지우기", removeVariant) : null,
    variantId
      ? el("span", { class: "hint" }, `보이는 값은 기본 문서에 이 변형을 적용한 값 · 덮어쓴 경로 ${Object.keys(patch ?? {}).length}곳 — 고친 값은 이 변형으로 들어간다`)
      : null);

  const sections = spec.sections.map((s) => {
    const n = patch ? sectionOverrides(patch, s).length : 0;
    return el("details", {
      class: "pf-sect", open: openSections.has(s.key) ? "" : undefined,
      ontoggle: (e) => { if (e.target.open) openSections.add(s.key); else openSections.delete(s.key); },
    },
    el("summary", {}, s.title, n ? el("span", { class: "pf-badge" }, `덮어씀 ${n}`) : null,
      el("span", { class: "hint" }, s.help)),
    ...s.fields.map(row));
  });

  return el("div", { class: "pf" }, meta, vbar,
    applied.issues.length
      ? el("div", { class: "error-box" }, "이 형상 변형의 치환 중 적용 못 한 것: ", applied.issues.join(" · "))
      : null,
    ...sections);
}
