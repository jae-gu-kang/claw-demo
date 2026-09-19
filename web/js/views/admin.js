/** 관리자 화면 — 회원관리·접속 현황·서버 데이터 (세션 모드 전용, routes/admin.py 소비).

파이프라인 탭이 **아니다**: index.html nav·main.js VIEWS·02 §8 어디에도 없고
(blocks.test.js 가드), 헤더 세션 알약의 [관리] 링크(#admin)로만 들어온다 —
main.js route()가 admin 역할일 때만 이 뷰를 세우고 아니면 블록도로 폴백한다.

권한은 서버가 판정한다(require_admin) — 여기서 403이 오면 안내만 남긴다.
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";

let pollTimer = null;

export function dispose() {
  clearInterval(pollTimer);
  pollTimer = null;
}

const when = (t) => (t == null ? "—" : new Date(t * 1000).toLocaleString("ko-KR"));
const mb = (b) => (b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${(b / 1e3).toFixed(1)} kB`);
const ROLE = { admin: "관리자", user: "일반" };
const STATUS = { pending: "승인 대기", active: "사용 중", rejected: "거절됨" };

export function render() {
  const membersBox = el("div");
  const sessionsBox = el("div");
  const dataBox = el("div");
  const root = el("div", { class: "admin-page" },
    el("div", { class: "pagetop" }, el("h1", {}, "관리")),
    el("section", { class: "panel" }, el("h2", {}, "회원"), membersBox),
    el("section", { class: "panel" }, el("h2", {}, "접속 현황"), sessionsBox),
    el("section", { class: "panel" }, el("h2", {}, "서버 데이터"), dataBox),
  );
  loadMembers(membersBox);
  loadSessions(sessionsBox);
  loadData(dataBox);
  // 접속 현황만 5초 폴링 (refreshHealth 관례) — 회원·데이터는 동작 후 재조회로 충분
  pollTimer = setInterval(() => loadSessions(sessionsBox), 5000);
  return root;
}

const oops = (box, err) =>
  clear(box).append(el("p", { class: "notice" }, errorText(err)));

// ── 회원 ────────────────────────────────────────────────────────────────

async function loadMembers(box) {
  let users;
  try {
    users = await api.get("/admin/users");
  } catch (err) {
    return oops(box, err);
  }
  const act = (label, fn, danger = false) =>
    el("button", {
      class: danger ? "danger" : null,
      onclick: async (e) => {
        e.target.disabled = true;
        try {
          await fn();
          loadMembers(box);
        } catch (err) {
          alertRow(box, err);
          e.target.disabled = false;
        }
      },
    }, label);
  clear(box).append(
    el("table", {},
      el("thead", {}, el("tr", {},
        ...["아이디", "역할", "상태", "가입", "최근 로그인", "동작"].map((h) => el("th", {}, h)))),
      el("tbody", {}, users.map((u) => el("tr", { class: u.status === "pending" ? "pending" : null },
        el("td", {}, el("b", {}, u.username)),
        el("td", {}, ROLE[u.role] ?? u.role),
        el("td", {}, STATUS[u.status] ?? u.status),
        el("td", {}, when(u.created_at)),
        el("td", {}, when(u.last_login)),
        el("td", {}, el("div", { class: "rowbtns" },
          u.status !== "active" && act("승인", patchUser(u.username, { status: "active" }, box)),
          u.status !== "rejected" && act("거절", patchUser(u.username, { status: "rejected" }, box)),
          u.role === "user"
            ? act("관리자로", patchUser(u.username, { role: "admin" }, box))
            : act("일반으로", patchUser(u.username, { role: "user" }, box)),
          act("비번 재설정", () => resetPassword(u.username)),
          act("삭제", () => removeUser(u.username), true),
        )),
      ))),
    ),
    el("p", { class: "muted" },
      "가입 신청은 「승인 대기」로 들어옵니다 — 승인해야 로그인됩니다. ",
      "관리자 시드 계정(환경변수)은 재기동 때 항상 복원됩니다."),
  );

  function patchUser(name, body) {
    return () => api.patch(`/admin/users/${name}`, body);
  }
  async function resetPassword(name) {
    const pw = prompt(`「${name}」의 새 비밀번호 (4자 이상)`);
    if (pw == null) return;
    await api.patch(`/admin/users/${name}`, { password: pw });
  }
  async function removeUser(name) {
    if (!confirm(`「${name}」 계정을 삭제할까요? 되돌릴 수 없습니다.`)) return;
    await api.del(`/admin/users/${name}`);
  }
  function alertRow(box, err) {
    box.querySelector(".notice")?.remove();
    box.prepend(el("p", { class: "notice" }, errorText(err)));
  }
}

// ── 접속 현황 ───────────────────────────────────────────────────────────

async function loadSessions(box) {
  let s;
  try {
    s = await api.get("/admin/sessions");
  } catch (err) {
    return oops(box, err);
  }
  clear(box).append(
    el("p", { class: "muted" },
      `지금 접속 중 (최근 ${Math.round(s.window_s / 60)}분 내 요청): `,
      s.online.length
        ? s.online.map((o, i) => el("span", {}, i ? " · " : "", el("b", {}, o.username)))
        : "없음"),
    el("table", {},
      el("thead", {}, el("tr", {},
        ...["아이디", "상태", "최근 로그인"].map((h) => el("th", {}, h)))),
      el("tbody", {}, s.users.map((u) => el("tr", {},
        el("td", {}, u.username),
        el("td", {}, STATUS[u.status] ?? u.status),
        el("td", {}, when(u.last_login)),
      ))),
    ),
  );
}

// ── 서버 데이터 ─────────────────────────────────────────────────────────

async function loadData(box) {
  let d;
  try {
    d = await api.get("/admin/data");
  } catch (err) {
    return oops(box, err);
  }
  const keep = el("input", { type: "number", min: 0, step: 1, value: 20, style: "width:80px" });
  clear(box).append(
    el("p", {},
      `결과 저장소: ${d.results}건 · ${mb(d.bytes)}`,
      d.limit != null ? ` (보존 상한 ${d.limit}건 — 넘치면 오래된 것부터 자동 삭제)` : " (상한 없음)"),
    el("div", { class: "rowbtns" },
      el("label", {}, "최신 ", keep, " 건만 남기고"),
      el("button", {
        class: "danger",
        onclick: async (e) => {
          const n = Math.max(0, Math.floor(+keep.value || 0));
          if (!confirm(`오래된 결과를 지우고 최신 ${n}건만 남길까요? 되돌릴 수 없습니다.`)) return;
          e.target.disabled = true;
          try {
            const r = await api.post("/admin/data/prune", { keep: n });
            await loadData(box); // 먼저 다시 그린다 — 안 기다리면 그 clear(box)가 아래 메시지를 지운다
            box.prepend(el("p", { class: "muted" }, `${r.removed}건 삭제 — ${r.results}건 남음`));
          } catch (err) {
            oops(box, err);
          }
        },
      }, "정리"),
    ),
    el("p", { class: "muted" },
      "결과는 계산 산출물이라 지워도 다시 계산하면 됩니다. 기체 프로파일은 여기서 건드리지 않습니다."),
  );
}
