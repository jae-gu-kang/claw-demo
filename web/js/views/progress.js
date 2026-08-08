/** 진행률 UI 헬퍼 — 실행 중 탭 이탈·재진입 시 재부착 (리뷰 S4: 고아 작업 방지).

뷰 모듈은 진행 중 job id를 모듈 상태로 보관하고, render마다 이 헬퍼로
재부착한다. watchJob 중복 부착은 무해 (이전 감시자는 분리된 DOM에 쓰고 종료).
*/

import { cancelJob, watchJob } from "../api.js";
import { clear, el } from "../dom.js";

export function attachProgress(progressBox, jobId, { onDone, onError }) {
  const bar = el("div");
  const label = el("span", { class: "progress-label" }, "…");
  clear(progressBox).append(el("div", { class: "progress-line" },
    el("div", { class: "progress" }, bar),
    label,
    el("button", { onclick: () => cancelJob(jobId) }, "취소"),
  ));
  watchJob(jobId, (j) => {
    bar.style.width = `${Math.round(100 * j.progress)}%`;
    label.textContent = `${j.status} ${j.done}/${j.total} ${j.message ?? ""}`;
  }).then((job) => {
    clear(progressBox);
    onDone(job);
  }).catch((e) => {
    clear(progressBox);
    onError(e);
  });
}

/** 취소 fast-path 등 저장 결과 없는 종단 처리 — true면 호출측은 결과 조회 생략. */
export function cancelledWithoutResult(job) {
  return job.status === "cancelled" && !job.result_id;
}
