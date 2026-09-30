/** Saved design alternatives inside the flow workbench. */

import { api, errorText } from "../api.js";
import { el } from "../dom.js";
import { latestResultFor } from "../lib/flowsteps.js";
import { store } from "../store.js";

const names = new Map();
const open = new Map();
const evalChoice = new Map();
const trimChoice = new Map();
const basisChoice = new Map();
const notes = new Map();
const pending = new Set();
const messages = new Map();

const scope = (r) => `${r.id}::${r.variant ?? ""}`;
const same = (a, r) => a?.id === r.id && (a.variant ?? null) === (r.variant ?? null);
const label = (v) => v.source?.kind === "auto" ? "자동" : "수동";
const pipelineLabel = (item) => {
  const latest = item.versions.at(-1);
  if (!latest) return "버전 없음";
  if (latest.based_on_evaluation_id) return "평가 후 설계";
  if (new Set(item.versions.map((v) => v.source?.kind)).size > 1) return "혼합";
  return label(latest);
};

const currentConfig = (r) => {
  const source = store.get("gainTablesSource");
  if (!same(source?.profile, r)) {
    throw new Error("이 기체의 작업본이 없습니다. 게인 또는 자동 설계 탭에서 적용한 뒤 저장하세요.");
  }
  const config = {
    gain_tables: store.get("gainTables") ?? {},
    scas: store.get("scasParams") ?? null,
    autopilot: store.get("autopilotParams") ?? null,
  };
  if (store.get("gainScheduleOff") === true) config.with_schedule = false;
  return config;
};

const versionValues = (v) => {
  const rows = Object.entries(v.config?.gain_tables ?? {});
  const constants = Object.entries(v.config?.constants ?? {});
  return el("div", { class: "de-values-wrap" }, el("div", { class: "de-values" },
    ...rows.map(([slot, table]) => el("div", {},
      el("strong", {}, slot),
      el("span", {}, `표 ${table?.axes?.mach?.length ?? "?"}절점`))),
    ...constants.map(([slot, value]) => el("div", {},
      el("strong", {}, slot), el("span", {}, `상수 ${value}`))),
    !rows.length && !constants.length ? el("span", { class: "hint" }, "상수·제어 설정 저장됨") : null),
    el("details", { class: "de-raw" }, el("summary", {}, "저장된 수치 보기"),
      el("pre", {}, JSON.stringify(v.config, null, 2))));
};

const progress = (version) => {
  const lastEval = version?.evaluations?.at(-1);
  const states = [
    ["doc", version ? "done" : "empty", version ? "기준 기체 기록됨" : "설계 버전 없음"],
    ["envelope", "unknown", "저장된 엔벨로프 실행 기록 없음"],
    ["seed", "unknown", "시드 실행 기록은 설계 버전과 연결되지 않음"],
    ["design", version ? "done" : "empty", version ? `${label(version)} 설계값 저장됨` : "설계값 없음"],
    ["eval", !lastEval ? "empty" : lastEval.hard_fail === true ? "fail"
      : lastEval.hard_fail === false ? "done" : "unknown",
    !lastEval ? "연결된 평가 없음" : `평가 ${lastEval.result_id} · ${lastEval.hard_fail === true ? "미달" : lastEval.hard_fail === false ? "통과" : "판정 모름"}`],
    ["apply", version?.adopted_revision ? "done" : "empty",
      version?.adopted_revision ? `문서 리비전 ${version.adopted_revision}에 반영` : "문서에 미반영"],
  ];
  return el("span", { class: "de-progress", "aria-hidden": "true" },
    ...states.map(([stage, state, tip]) => el("span", { "data-stage": stage,
      "data-state": state, title: tip })));
};

export function renderDesignEntities(r, items, metas, refresh, paint) {
  const key = scope(r);
  const mine = (items ?? []).filter((d) => d.profile_id === r.id && (d.variant ?? null) === (r.variant ?? null));
  const chosen = open.get(key);
  const auto = latestResultFor(metas, "auto_design", { id: r.id, variant: r.variant ?? null });
  const evaluations = (metas ?? []).filter((m) => m.kind === "influence_evaluate"
    && same(m.profile, r));
  const trims = (metas ?? []).filter((m) => m.kind === "trim_batch" && same(m.profile, r));
  const run = async (action, success) => {
    if (pending.has(key)) return;
    pending.add(key);
    messages.set(key, "저장 중…");
    paint();
    try {
      const updated = await action();
      if (updated?.id) open.set(key, updated.id);
      messages.set(key, success);
      await refresh();
    } catch (err) {
      messages.set(key, errorText(err));
    } finally {
      pending.delete(key);
      paint();
    }
  };
  const box = el("section", { class: "de-manager" },
    el("div", { class: "de-head" },
      el("div", {}, el("strong", {}, "저장된 설계안"),
        el("span", { class: "hint" }, `${mine.length}개 · 버전마다 설계값과 평가를 보존`)),
      el("div", { class: "de-create" },
        el("input", { value: names.get(key) ?? "", placeholder: "새 설계안 이름", maxlength: 100,
          "aria-label": "새 설계안 이름", oninput: (ev) => names.set(key, ev.target.value) }),
        el("button", { disabled: pending.has(key), onclick: () => run(async () => {
          const name = names.get(key)?.trim();
          if (!name) throw new Error("설계안 이름을 입력하세요");
          const made = await api.post("/design-entities", { profile_id: r.id,
            variant: r.variant ?? null, name });
          names.set(key, "");
          return made;
        }, "설계안을 만들었습니다") }, "새 설계안"))));
  if (messages.has(key)) box.append(el("p", { class: "de-message" }, messages.get(key)));
  for (const item of mine) {
    const latest = item.versions.at(-1);
    const expanded = chosen === item.id;
    const card = el("div", { class: "de-item" },
      el("button", { class: "de-item-head", "aria-expanded": String(expanded),
        onclick: () => { open.set(key, expanded ? null : item.id); paint(); } },
        el("span", { class: "de-item-name" }, el("strong", {}, item.name),
          el("small", {}, latest ? `v${latest.number} · ${pipelineLabel(item)} · 평가 ${latest.evaluations.length}건` : "버전 없음")),
        progress(latest),
        el("span", { "aria-hidden": "true" }, expanded ? "−" : "+")));
    if (expanded) {
      const savedEvals = item.versions.flatMap((v) => v.evaluations ?? []);
      const basis = el("select", { "aria-label": "후속 설계의 근거 평가",
        onchange: (ev) => basisChoice.set(item.id, ev.target.value) },
        el("option", { value: "" }, "근거 평가 없음"),
        ...savedEvals.map((e) => el("option", { value: e.result_id,
          selected: basisChoice.get(item.id) === e.result_id },
        `${e.result_id} · ${e.hard_fail === true ? "미달" : "통과"}`)));
      const note = el("input", { value: notes.get(item.id) ?? "", maxlength: 500,
        placeholder: "버전 메모", "aria-label": "새 버전 메모",
        oninput: (ev) => notes.set(item.id, ev.target.value) });
      const versionMeta = () => {
        const evalId = basisChoice.get(item.id) || null;
        return { note: notes.get(item.id) ?? "", based_on_evaluation_id: evalId,
          parent_version: evalId
            ? item.versions.find((v) => v.evaluations.some((e) => e.result_id === evalId))?.number
            : item.versions.length || null };
      };
      const save = el("div", { class: "de-actions" },
        note, basis,
        el("button", { disabled: pending.has(key), title: "현재 작업본의 게인·제어 설정을 새 버전으로 고정",
          onclick: () => run(() => api.post(`/design-entities/${item.id}/versions`, {
            expected_count: item.versions.length, mode: "manual", config: currentConfig(r),
            ...versionMeta(),
          }), "수동 설계 버전을 저장했습니다") }, "현재 작업본 저장"),
        el("button", { disabled: pending.has(key) || !auto,
          title: auto ? `자동 설계 결과 ${auto.id}의 반출값을 새 버전으로 보존` : "자동 설계 결과 없음",
          onclick: () => run(() => api.post(`/design-entities/${item.id}/versions`, {
            expected_count: item.versions.length, mode: "auto", auto_result_id: auto.id,
            ...versionMeta(),
          }), "자동 설계 버전을 저장했습니다") }, "최근 자동 설계 저장"));
      const history = el("div", { class: "de-history" });
      for (const v of [...item.versions].reverse()) {
        const choiceKey = `${item.id}:${v.number}`;
        const choices = el("select", { "aria-label": `v${v.number}에 연결할 평가 결과`,
          onchange: (ev) => evalChoice.set(choiceKey, ev.target.value) },
          el("option", { value: "" }, "평가 결과 선택"),
          ...evaluations.map((m) => el("option", { value: m.id,
            selected: evalChoice.get(choiceKey) === m.id },
          `${m.id} · ${m.hard_fail === true ? "미달" : m.hard_fail === false ? "통과" : "판정 모름"}`)));
        const trimChoices = el("select", { "aria-label": `v${v.number}에 연결할 트림 결과`,
          onchange: (ev) => trimChoice.set(choiceKey, ev.target.value) },
          el("option", { value: "" }, "트림 결과 선택"),
          ...trims.map((m) => el("option", { value: m.id,
            selected: trimChoice.get(choiceKey) === m.id }, m.id)));
        const actions = el("div", { class: "de-version-actions" },
          el("button", { disabled: pending.has(key) || !!Object.keys(v.config?.constants ?? {}).length,
            title: Object.keys(v.config?.constants ?? {}).length
              ? "상수 자리까지 포함한 자동 설계는 결과 화면에서 게인 확정으로 적용"
              : "저장된 게인을 게인·영향성 탭의 작업본으로 연다",
            onclick: () => {
              store.set("gainTables", v.config.gain_tables ?? null);
              store.set("gainScheduleOff", v.config.with_schedule === false);
              store.set("scasParams", v.config.scas ?? null);
              store.set("autopilotParams", v.config.autopilot ?? null);
              store.set("gainTablesSource", { kind: "design_entity", entityId: item.id,
                version: v.number, profile: { id: r.id, variant: r.variant ?? null } });
              messages.set(key, `v${v.number}을 작업본으로 열었습니다`);
              paint();
            } }, "작업본으로 열기"),
          el("button", { disabled: pending.has(key) || !evaluations.length,
            onclick: () => run(() => {
              const resultId = evalChoice.get(choiceKey);
              if (!resultId) throw new Error("연결할 평가 결과를 고르세요");
              return api.post(`/design-entities/${item.id}/versions/${v.number}/evaluations`,
                { result_id: resultId });
            }, "평가를 연결했습니다") }, "평가 연결"),
          el("button", { disabled: pending.has(key) || !trims.length,
            onclick: () => run(() => {
              const resultId = trimChoice.get(choiceKey);
              if (!resultId) throw new Error("연결할 트림 결과를 고르세요");
              return api.post(`/design-entities/${item.id}/versions/${v.number}/artifacts`,
                { result_id: resultId });
            }, "트림을 연결했습니다") }, "트림 연결"),
          el("button", { disabled: pending.has(key), onclick: () => run(() =>
            api.post(`/design-entities/${item.id}/branch`,
              { name: `${item.name} 분기`, number: v.number }), "설계안을 분기했습니다") }, "이 버전에서 분기"),
          el("button", { disabled: pending.has(key) || !!r.variant || !!r.is_example || !Object.keys(v.config?.gain_tables ?? {}).length
            || ["scas", "autopilot", "constants"].some((k) => !!v.config?.[k])
            || v.config?.with_schedule === false || v.config?.with_limiter === false,
            title: "마하 게인 표만 가진 기본 기체 버전을 문서에 반영",
            onclick: () => run(async () => {
              const doc = await api.get(`/profiles/${encodeURIComponent(r.id)}`);
              return api.post(`/design-entities/${item.id}/versions/${v.number}/apply`,
                { base_revision: doc.revision });
            }, "설계 버전을 기체 문서에 반영했습니다") }, "문서에 반영"));
        history.append(el("div", { class: "de-version" },
          el("div", { class: "de-version-head" },
            el("strong", {}, `v${v.number} · ${label(v)}`),
            el("span", { class: "hint" }, v.created_at),
            v.parent_version ? el("span", { class: "hint" }, `v${v.parent_version} 기반`) : null,
            v.adopted_revision ? el("span", { class: "flag ok" }, `문서 리비전 ${v.adopted_revision}`) : null),
          v.note ? el("p", { class: "de-note" }, v.note) : null,
          v.based_on_evaluation_id ? el("p", { class: "de-note" }, `근거 평가: ${v.based_on_evaluation_id}`) : null,
          versionValues(v),
          el("p", { class: "de-evals" }, v.evaluations.length
            ? v.evaluations.map((e) => `${e.result_id} ${e.hard_fail === true ? "미달" : e.hard_fail === false ? "통과" : "판정 모름"}`).join(" · ")
            : "연결된 평가 없음"),
          el("p", { class: "de-evals" }, (v.artifacts ?? []).length
            ? `트림: ${v.artifacts.map((a) => a.result_id).join(" · ")}` : "연결된 트림 없음"),
          el("div", { class: "de-eval-picker" }, choices, trimChoices, actions)));
      }
      card.append(save, history);
    }
    box.append(card);
  }
  if (!mine.length) box.append(el("p", { class: "hint" }, "저장된 설계안이 없습니다."));
  return box;
}

export async function recordFlowResult(r, items, stage, resultId) {
  const item = (items ?? []).find((d) => d.id === open.get(scope(r)));
  if (!item || !resultId) return false;
  if (stage === "design") {
    await api.post(`/design-entities/${item.id}/versions`, {
      expected_count: item.versions.length, mode: "auto", auto_result_id: resultId,
    });
  } else if (stage === "eval" && item.versions.length) {
    await api.post(`/design-entities/${item.id}/versions/${item.versions.length}/evaluations`,
      { result_id: resultId });
  } else return false;
  return true;
}
