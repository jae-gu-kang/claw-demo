/** 전역 질문 위젯 (D2) — 어느 탭에서든 묻고, 답이 화면을 그 자리로 옮긴다.

조립 전용 — 판단(액션 정규화·해시 검증)은 lib/ask.js(테스트). 이 위젯은 body에
직접 붙는 유일한 상시 크롬이다: 라우트 뷰가 아니라 main.js가 초기화 끝에
`mount()`를 한 번 부르고, 탭 전환(#view 교체)에 영향받지 않는다. main.js의
import는 VIEWS 객체 **밖**이라 blocks.test.js의 nav 정규식 가드에 안 걸린다.

동작: 질문 → `/api/llm/ask` 202 잡 → 답 + 이동 액션. **첫 액션으로 화면을
실제로 이동**시키고(그것이 이 기능의 요지 — "답을 말하는" 게 아니라 "답을
보여 주는"), 패널은 떠 있어 답을 계속 읽는다. 키 없는 배포는 서버 사유
문장이 패널에 그대로 뜬다(조용한 비표시 금지).

ESC 전역 리스너는 이 리포 최초다 — 열려 있을 때만 닫고, preventDefault를
하지 않아 캔버스 스코프의 기존 Escape(영향성 선택 해제)와 충돌하지 않는다.
*/

import { api, errorText, watchJob } from "../api.js";
import { clear, el } from "../dom.js";
import { TAB_HASHES, normalizeAnswer } from "../lib/ask.js";
import { walkPages } from "../lib/blocks.js";
import { SUBSYSTEMS } from "./subsystems.js";

let mounted = false;
let isOpen = false;
let jobId = null;       // 진행 중 잡 — 이중 제출 방지의 한 축
let submitting = false; // await 앞 동기 플래그 — 더블클릭 이중 과금 방지 (전 기능 규약)
let llm = null;         // /llm/status — 성공만 캐시 (실패는 다음 열기에서 재시도)
let lastQA = null;      // {question, norm, model} — 닫았다 열어도 남는다

export function mount() {
  if (mounted) return; // 한 번만 — main.js 재호출 방어
  mounted = true;
  // 블록도 하위 페이지 전량 — 해시 검증 허용 목록 (lib는 목록을 인자로 받는다)
  const blockPages = new Set([...walkPages(SUBSYSTEMS)].map((p) => p.key));

  const statusLine = el("p", { class: "hint", style: "margin:0 0 8px" },
    "서버 상태 확인 중…");
  const input = el("input", {
    class: "ask-input",
    placeholder: "예: 실속 마진은 어디서 봐?",
    onkeydown: (ev) => { if (ev.key === "Enter") run(); },
  });
  const askBtn = el("button", { class: "primary" }, "묻기");
  const busyLine = el("p", { class: "hint", style: "margin:6px 0 0" });
  const errBox = el("div");
  const ansBox = el("div");

  const syncUi = () => {
    const avail = !!llm?.available;
    input.disabled = !avail || !!jobId;
    askBtn.disabled = !avail || !!jobId || submitting;
    clear(askBtn).append(jobId || submitting ? "생성 중…" : "묻기");
    clear(statusLine);
    if (llm == null) statusLine.append("서버 상태 확인 중…");
    else if (!avail) statusLine.append(llm.reason ?? "사용할 수 없습니다.");
    else statusLine.append(`${llm.model} — 답이 그 화면을 엽니다 (수치의 정본은 각 탭).`);
  };

  const showErr = (text) =>
    clear(errBox).append(el("div", { class: "error-box" }, text));

  const loadStatus = async () => {
    try {
      llm = await api.get("/llm/status");
      clear(errBox);
    } catch (e) {
      // **실패는 캐시하지 않는다** — 이 위젯은 mount 1회·앱 수명 크롬이라
      // 실패를 llm에 담으면 콜드 스타트(~1분)의 첫 실패가 새로고침 전까지
      // 위젯을 전 탭에서 죽인다 (blocks.js gainsCatalog가 같은 이유로 성공만
      // 캐시한다 — 실제 배포가 그 무료 플랜이다). 다음 열기에서 재시도.
      llm = null;
      showErr(`상태 조회 실패 — ${errorText(e)} · 패널을 다시 열면 재시도합니다.`);
    }
    syncUi();
  };

  const paintAnswer = () => {
    clear(ansBox);
    if (!lastQA) return;
    const { question, norm, model } = lastQA;
    ansBox.append(
      el("p", { class: "hint", style: "margin:10px 0 4px" }, `Q. ${question}`),
      ...norm.answer.split(/\n{2,}/).map((par) =>
        el("p", { style: "margin:0 0 6px" }, par)),
      norm.actions.length
        ? el("div", { class: "ask-actions" },
            norm.actions.map((a, i) => el("button", {
              class: i === 0 ? "primary" : "",
              title: a.why || a.hash,
              onclick: () => { location.hash = a.hash; },
            }, i === 0 ? `${a.label} ↗` : a.label)))
        : null,
      norm.issues.length
        ? el("div", { class: "error-box", style: "margin-top:8px" },
            norm.issues.map((m) => el("div", {}, `· ${m}`)))
        : null,
      model ? el("p", { class: "hint", style: "margin:6px 0 0" }, model) : null,
    );
  };

  const run = async () => {
    if (jobId || submitting) return; // 버튼이 이미 꺼져 있다 — 방어만
    const q = input.value.trim();
    if (!q) {
      showErr("질문을 입력하십시오 — 한 줄이면 됩니다.");
      return;
    }
    submitting = true;
    syncUi();
    try {
      clear(errBox);
      busyLine.textContent = "";
      const sub = await api.post("/llm/ask", { question: q });
      jobId = sub.id;
      syncUi();
      busyLine.textContent = "답을 만드는 중…";
      // 서버의 단계 보고("호출 중"·"답 정리 중")를 그대로 흘린다 — 다른 기능과
      // 같은 규약 (고정 문자열은 진행을 위장한다)
      const done = await watchJob(jobId, (j) => {
        busyLine.textContent = j.message || "답을 만드는 중…";
      });
      if (done.status !== "done" || !done.result_id) {
        throw new Error(done.error ?? `문답 ${done.status}`);
      }
      const body = await api.get(`/results/${done.result_id}`);
      const norm = normalizeAnswer(
        { answer: body.answer, actions: body.actions },
        { views: TAB_HASHES, blockPages });
      lastQA = { question: q, norm, model: body.model ?? null };
      paintAnswer();
      // 첫 액션 자동 이동 — 패널은 떠 있어 답을 계속 읽는다
      if (norm.actions.length) location.hash = norm.actions[0].hash;
    } catch (e) {
      showErr(errorText(e));
    } finally {
      jobId = null;
      submitting = false;
      busyLine.textContent = "";
      syncUi();
    }
  };
  askBtn.onclick = run;

  const panel = el("div", { class: "ask-panel", hidden: true },
    el("div", { class: "ask-head" },
      el("strong", {}, "질문 — 답이 화면을 엽니다"),
      el("button", { class: "ask-close", title: "닫기 (ESC)",
        onclick: () => setOpen(false) }, "×")),
    statusLine,
    el("div", { class: "ask-row" }, input, askBtn),
    busyLine, errBox, ansBox,
  );
  const fab = el("button", {
    class: "ask-fab",
    title: "무엇이 어디 있는지 물어보십시오 — 답이 그 화면을 엽니다 (서버 경유 LLM)",
    "aria-expanded": "false",
  }, "? 질문");

  function setOpen(v) {
    isOpen = v;
    panel.hidden = !v;
    fab.setAttribute("aria-expanded", v ? "true" : "false");
    if (v) {
      if (llm == null) loadStatus(); // 처음 열 때 1회 — 안 여는 사람에게 왕복 없음
      paintAnswer(); // 지난 문답 복원
      input.focus();
    }
  }
  fab.onclick = () => setOpen(!isOpen);
  // 열려 있을 때만 닫는다 — preventDefault 없음 (다른 Escape 소비자와 공존)
  window.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && isOpen) setOpen(false);
  });

  syncUi(); // 첫 상태 조회 전에는 비활성 — 상태를 모른 채 제출부터 되면 안 된다
  document.body.append(fab, panel);
}
