/** 비행조건 고르개 — 요구영역 기본 격자(서버 `POST /grid/base`)에서 점을 고르거나 거른다 (05 §11.13 5단계).

영향성 탭(이관 5단계)에서 떼어 낸 공용 부품이다. 마진 맵도 같은 부품으로 고른다 — 탭마다 고르는 법이 다르면
「같은 조건」이 탭마다 다른 뜻이 된다. 규칙(보낼 점·대표점·가운데 점)은 lib/opspace.js에 있고 여기는 배선·그리기만.

- 보낼 수 있는 점 = 미계산 점만(모델 부족은 트림 근거가 없다). 이름은 서버(엔진 case_name)가 값 그대로 지은 것.
- 선택은 **이름 집합**이라 격자를 다시 받아도 같은 점이 남는다. null = 보낼 점 전부(손대지 않음 — 요구영역이 바뀌면
  새 점도 따라온다).
- 받는 중·못 받음이면 옛 점을 보내지 않는다. 요구 미정의(region null)면 보내지 않고, 고른 이름은 보류로 둔다.
- 상태는 key마다 모듈에 산다 — 탭을 떠났다 와도 선택·필터·펼침이 남는다. 요청 차례(seq)도 key마다다: 늦게 온 옛
  응답이 새 응답을 덮지 않는다.

createCondPicker({key, onChange, warnInk, where}) →
  {summary, details, el, selectedCases(), refresh(), latest(), reset(), select(names), pool(), grid(), state}
  summary·details는 따로 배치할 때(영향성 무대), el은 둘을 한 덩이로(마진 맵). 한 화면에서 둘 중 한 쪽만 쓴다.
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import {
  casesFromBaseGrid, filterPoints, pointAxes, representativePoints, storedCount, trimResultsByName, untrimmedSummary,
} from "../lib/opspace.js";
import { trimStateLabel } from "../lib/plot.js";
import { store } from "../store.js";

// 밀린 요청의 결과 — 「받았다」도 「못 받았다」도 아니다(격자는 더 나중 요청이 채운다)
const SUPERSEDED = Object.freeze({ status: "superseded" });
const emptyFilter = () => ({ alts: null, fuels: null, machLo: "", machHi: "" });
const MONO = "font-family:var(--mono);font-size:12px";

// key → 공유 상태. current = 가장 나중에 만든 화면의 다시 그리기(버려진 화면의 늦은 응답도 지금 화면을 고친다)
const slots = new Map();
function slotOf(key) {
  if (!slots.has(key)) {
    slots.set(key, {
      grid: null, error: null, loading: false, selected: null, open: false, pruned: [], filter: emptyFilter(),
      seq: 0, latest: null, current: null,
    });
  }
  return slots.get(key);
}

export function createCondPicker({ key, onChange = null, warnInk = "var(--warn)", where = "무대의 「비행조건」" }) {
  const st = slotOf(key);
  const summary = el("span", { class: "hint" });
  const box = el("div");
  const details = el("details", { style: "margin-top:6px" },
    el("summary", { class: "hint", style: "cursor:pointer" }, "점 고르기 — 고도·연료·마하로 거르고 고른다"),
    box);
  if (st.open) details.open = true;
  details.addEventListener("toggle", () => { st.open = details.open; });
  let wrap = null;

  const pool = () => casesFromBaseGrid(st.grid);

  function selectedCases() {
    const g = st.grid;
    // 받는 중·못 받음이면 남아 있는 격자는 옛 리비전일 수 있다 — 그 점으로 돌면 결과가 지금 요구영역의 것이라 읽힌다
    if (st.loading) throw new Error("기본 격자를 다시 받는 중 — 옛 점을 보내지 않는다. 받은 뒤 다시 누른다");
    if (st.error) throw new Error(`${st.error} — 옛 점을 보내지 않는다`);
    if (!g) throw new Error("기본 격자를 아직 받지 못했다 — 잠시 뒤 다시 누른다");
    if (!g.region) throw new Error(`요구영역 미정의 — ${g.reason}`);
    const sel = st.selected;
    const out = sel ? pool().filter((p) => sel.has(p.name)) : pool();
    if (!out.length) throw new Error(`고른 비행조건이 없다 — ${where}에서 점을 고른다`);
    return out;
  }

  const selectedNames = () => new Set(st.selected ?? pool().map((p) => p.name));
  // 선택을 이름 목록으로 — 보낼 점 전부면 null(손대지 않은 상태로 되돌린다)
  function setSelected(names) {
    const want = new Set(names);
    st.selected = pool().every((p) => want.has(p.name)) ? null : want;
    st.pruned = []; // 다시 골랐다 — 뺀 점 알림은 할 일을 다했다
    paintAll();
  }

  // 받은 격자를 싣는다. 요구 미정의(region null)면 고른 이름을 건드리지 않는다 — 점이 없는 응답으로 선택을 지우면
  // 요구영역을 되살려도 사용자가 고른 것이 영영 사라진다(보류로 두고 요약이 그렇다고 말한다)
  function applyGrid(body) {
    st.grid = body;
    st.error = null;
    if (!body.region || !st.selected) return;
    // 손으로 고른 이름 중 새 격자에서 보낼 수 없는 것(요구영역이 바뀌었다·모델 부족이 됐다)은 빼고 남긴다 — 없는
    // 점을 고른 채로 두면 개수가 거짓이고, 조용히 빼면 사용자가 모른 채 다른 점 집합으로 돈다
    const have = new Set(casesFromBaseGrid(body).map((p) => p.name));
    const gone = [...st.selected].filter((n) => !have.has(n));
    if (!gone.length) return;
    st.selected = new Set([...st.selected].filter((n) => have.has(n)));
    st.pruned = [...new Set([...st.pruned, ...gone])];
  }

  // 기본 격자 받기 — 요구영역의 기본 명세 그대로(명세 칸은 트림 탭 몫이다).
  // 결과 {status: "ok"|"undefined"|"error"|"superseded", reason?} — 밀린 요청은 superseded(성공으로 읽지 않는다)
  function refresh() {
    const seq = ++st.seq;
    st.loading = true;
    paintAll();
    const p = (async () => {
      try {
        const body = await api.post("/grid/base", {});
        if (seq !== st.seq) return SUPERSEDED; // 더 나중 요청이 있다 — 그쪽이 채운다
        applyGrid(body);
        return body.region ? { status: "ok" } : { status: "undefined", reason: `요구영역 미정의 — ${body.reason}` };
      } catch (e) {
        if (seq !== st.seq) return SUPERSEDED;
        // 옛 격자는 표에 남기되(고른 이름을 잃지 않게) 못 받았다고 표시한다 — selectedCases가 옛 점을 보내지 않는다
        st.error = `기본 격자를 받지 못했다 — ${errorText(e)}`;
        return { status: "error", reason: st.error };
      } finally {
        if (seq === st.seq) {
          st.loading = false;
          paintAll();
        }
      }
    })();
    st.latest = p;
    return p;
  }

  // 가장 나중 요청의 결과까지 기다린다 — 자기 요청이 밀렸으면 이긴 요청을 기다린다(밀린 응답을 받았다고 치면
  // 받는 중인 옛 격자로 고른다)
  async function latest() {
    let r = await refresh();
    while (r.status === "superseded") r = await st.latest;
    return r;
  }

  /** 손대지 않은 상태로 — 필터를 풀고 보낼 점 전부. 뺀 점 알림도 걷는다. */
  function reset() {
    st.filter = emptyFilter();
    st.selected = null;
    st.pruned = [];
    paintAll();
  }

  /** 이름 목록으로 고른다(필터도 푼다 — 고른 점이 표에서 숨지 않게). */
  function select(names) {
    st.filter = emptyFilter();
    setSelected(names);
  }

  // 트림 탭이 이 기체 리비전으로 돌린 배치가 있으면 점마다 그 상태를 붙인다(트림 결과 참조 — 없으면 열이 없다)
  const trimByName = () => trimResultsByName(store.get("trimBatch"), st.grid);

  function paint() {
    clear(summary);
    clear(box);
    try {
      paintBody(st.grid);
    } finally {
      onChange?.();
    }
  }

  function paintBody(g) {
    // 못 받았으면 옛 격자가 있어도 맨 앞에 크게 — 표의 점이 지금 요구영역의 것이라 읽히지 않게
    if (st.error) {
      summary.append(el("strong", { style: `color:${warnInk}` },
        `${st.error} — 옛 점을 보내지 않는다${g ? " (아래 표는 옛 격자)" : ""}`), g ? " · " : "");
    }
    if (!g) {
      if (!st.error) summary.append("요구영역 기본 격자를 받는 중…");
      return;
    }
    if (!g.region) {
      const held = st.selected?.size;
      summary.append(el("span", { style: `color:${warnInk}` }, `요구영역 미정의 — ${g.reason}`),
        held ? ` · 고른 점 ${held}개는 보류 — 요구영역이 정해지면 다시 적용한다` : "",
        st.loading ? " · 다시 받는 중…" : "");
      return;
    }
    const all = pool();
    const sel = selectedNames();
    const nSel = all.filter((p) => sel.has(p.name)).length;
    const untrimmed = untrimmedSummary(g);
    const nStored = storedCount(g);
    summary.append(
      el("strong", {}, `${nSel}점`), ` / 기본 격자 ${all.length}점`,
      st.selected ? " (고름)" : " (전부)",
      // 보내지 않는 점 — 모델 부족·요구영역 밖·요구 미정의 행. 트림 탭과 같은 글로 사라지지 않게 남긴다
      untrimmed.text ? ` · ${untrimmed.text.replace("트림하지 않음", "보내지 않음")}` : "",
      g.region.confirmed ? "" : " · 요구영역 미확정 초안(트림 탭 「운용영역·기본 격자」)",
      nStored ? el("span", { title: "서버 트림 저장소에 이 기체·풀이 설정으로 수렴한 수평 트림이 있는 점 — "
        + "실행 때 다시 풀지 않고 쓴다(서버 메모리, 재시작하면 비워진다)" }, ` · 트림 저장 ${nStored}`) : "",
      st.loading ? " · 다시 받는 중…" : "",
      st.pruned.length
        ? el("span", { style: `color:${warnInk}`, title: st.pruned.join(", ") },
          ` · 고른 점 ${st.pruned.length}개가 새 기본 격자에 없어 뺐다 (${st.pruned.join(", ")})`)
        : "");

    const axes = pointAxes(all);
    const f = st.filter;
    const visible = filterPoints(all, {
      alts: f.alts, fuels: f.fuels,
      machLo: f.machLo === "" ? null : Number(f.machLo), machHi: f.machHi === "" ? null : Number(f.machHi),
    });
    // 값 칩 — 체크 = 표에 보인다. 전부 켜지면 null(새 값도 보인다)
    const chips = (k, values, unit) => values.map((v) => {
      const cb = el("input", { type: "checkbox" });
      cb.checked = !f[k] || f[k].includes(v);
      cb.addEventListener("change", () => {
        const cur = new Set(f[k] ?? values);
        if (cb.checked) cur.add(v); else cur.delete(v);
        f[k] = values.every((x) => cur.has(x)) ? null : values.filter((x) => cur.has(x));
        paintAll();
      });
      return el("label", { class: "hint", style: "margin-right:8px" }, cb, ` ${v} ${unit}`);
    });
    const machIn = (k) => {
      const inp = el("input", { type: "number", step: "any", value: f[k], placeholder: "—", style: "width:62px" });
      inp.addEventListener("change", () => { f[k] = inp.value.trim(); paintAll(); }); // input마다 다시 그리면 칸이 초점을 잃는다
      return inp;
    };
    const trim = trimByName();
    const stored = new Map((g.points ?? []).map((p) => [p.name, p.stored]));
    const visNames = visible.map((p) => p.name);
    const btn = (label, title, fn) => el("button", { title, onclick: fn }, label);
    box.append(
      el("div", { class: "row", style: "gap:10px;align-items:center;flex-wrap:wrap" },
        el("span", { class: "hint" }, "고도 "), ...chips("alts", axes.alts, "m"),
        el("span", { class: "hint" }, "연료 "), ...chips("fuels", axes.fuels, "kg"),
        el("label", { class: "hint" }, "마하 ", machIn("machLo"), " ~ ", machIn("machHi"))),
      el("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-top:6px" },
        btn(`보이는 ${visible.length}점 고르기`, "표에 보이는 점을 선택에 더한다",
          () => setSelected([...selectedNames(), ...visNames])),
        btn("보이는 점 빼기", "표에 보이는 점을 선택에서 뺀다",
          () => { const s2 = selectedNames(); visNames.forEach((n) => s2.delete(n)); setSelected([...s2]); }),
        btn("대표점만", "보이는 점 중 가운데 연료 × 최저·최고 고도 행 × 각 행의 마하 양끝(최대 4점)만 고른다 "
          + "— lib/opspace.js representativePoints", () => setSelected(representativePoints(visible).map((p) => p.name))),
        trim ? btn("트림 채택점만", "보이는 점 중 트림 탭 배치에서 조건 판정이 채택한 점만 고른다",
          () => setSelected(visible.filter((p) => trim.get(p.name)?.verdict?.adopted === true).map((p) => p.name)))
          : null,
        btn("전부", "필터를 풀고 보낼 수 있는 점 전부를 고른다", () => {
          st.filter = emptyFilter();
          setSelected(all.map((p) => p.name));
        }),
        btn("기본 격자 다시 받기", "기체 탭에서 요구영역을 고쳤으면 — 고른 점은 이름으로 유지된다", () => refresh())),
      el("div", { class: "scroll-x", style: "max-height:260px;overflow-y:auto;margin-top:6px" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, ""), el("th", {}, "점"), el("th", {}, "마하"), el("th", {}, "고도 [m]"),
          el("th", {}, "연료 [kg]"), trim ? el("th", { title: "트림 탭 배치(같은 기체 리비전)의 조건 상태" }, "트림") : null)),
        el("tbody", {}, visible.map((p) => {
          const cb = el("input", { type: "checkbox" });
          cb.checked = sel.has(p.name);
          cb.addEventListener("change", () => {
            const s2 = selectedNames();
            if (cb.checked) s2.add(p.name); else s2.delete(p.name);
            setSelected([...s2]);
          });
          const tr = trim?.get(p.name);
          const kept = stored.get(p.name)?.converged === true;
          return el("tr", {}, el("td", {}, cb),
            el("td", { style: MONO }, p.name,
              kept ? el("span", { class: "hint", title: "서버 트림 저장소에 수렴한 트림이 있다 — 다시 풀지 않는다" }, " ◦")
                : null),
            el("td", { class: "num" }, String(p.mach)), el("td", { class: "num" }, String(p.alt)),
            el("td", { class: "num" }, String(p.fuel)),
            trim ? el("td", { class: "hint" }, tr ? trimStateLabel(tr) : "트림 안 함") : null);
        })))),
      el("p", { class: "hint", style: "margin:6px 0 0" },
        "점은 고른 기체의 요구 운용영역에서 만든 기본 격자다(트림 탭과 같은 점·같은 이름, 05 §11.11). ",
        "이 탭은 조건을 더하지 않는다 — 없는 조건이 필요하면 요구영역·기본 격자 명세를 고친다. ",
        trim ? "트림 열은 트림 탭이 이 기체 리비전으로 돌린 배치의 판정이다." : "트림 탭에서 배치를 돌리면 점마다 그 판정이 붙는다."),
    );
  }

  // 이 화면과 지금 화면(더 나중에 그린 화면) — 버려진 화면의 늦은 응답·조작이 지금 화면을 옛 상태로 두지 않게
  function paintAll() {
    paint();
    if (st.current && st.current !== paint) st.current();
  }
  st.current = paint;
  paint();

  return {
    summary, details,
    get el() {
      wrap ??= el("div", {}, el("div", { class: "row", style: "gap:10px;align-items:center;flex-wrap:wrap" },
        el("strong", {}, "비행조건"), summary), details);
      return wrap;
    },
    selectedCases, refresh, latest, reset, select, pool,
    grid: () => st.grid,
    state: st,
  };
}
