/** 결과 뷰 (02 §8 6단계 열람) — 저장 산출물 목록(메타)·원본 조회.

검증 리포트 생성(M12)은 엔진 구축 대기 — 여기서는 산출물 계보(지문) 열람까지.
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";

export function render() {
  const box = el("div");
  const errBox = el("div");

  const load = async () => {
    try {
      clear(errBox);
      const items = await api.get("/results");
      clear(box);
      if (!items.length) {
        box.append(el("p", { class: "hint" }, "저장된 산출물이 없습니다 — 트림/마진 맵/시뮬을 실행하세요."));
        return;
      }
      box.append(el("table", {},
        el("thead", {}, el("tr", {},
          el("th", {}, "생성 시각"), el("th", {}, "종류"), el("th", {}, "id"),
          el("th", {}, "건수"), el("th", {}, "지문(계보)"), el("th", {}, ""))),
        el("tbody", {}, items.map((m) => el("tr", {},
          el("td", {}, m.created ? new Date(m.created * 1000).toLocaleString() : "—"),
          el("td", {}, m.kind ?? "—"),
          el("td", { class: "num" }, m.id),
          el("td", { class: "num" }, m.n ?? "—"),
          el("td", { class: "num" }, m.fingerprint || "—"),
          el("td", {}, el("a", { href: `/api/results/${m.id}`, target: "_blank" }, "원본 JSON")),
        ))),
      ));
    } catch (e) {
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  load();
  return el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "저장 산출물 (본문/메타 분리 저장소)"),
      el("div", { class: "row" }, el("button", { onclick: load }, "새로고침")),
      errBox, box,
      el("p", { class: "hint" },
        "지문(fingerprint)은 산출물 계보 키 (02 §2.4) — 현재 클라이언트 자기신고, ",
        "파라미터 관리 계층(02 §5.5) 결선 시 엔진 발급으로 전환 예정."),
    ),
  );
}
