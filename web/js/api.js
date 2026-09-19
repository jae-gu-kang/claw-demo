/** 서버(M13) 통신 래퍼 — REST + 작업 진행 구독(WS, 폴백 폴링). 이 모듈만 통신 담당. */

import { currentSelection, withProfile } from "./lib/profile.js";

const BASE = "/api";
export const TERMINAL = new Set(["done", "error", "cancelled"]);
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function request(method, path, body) {
  // 헤더에서 고른 기체를 계산 요청에 싣는다 — 어느 요청이 받는가는 lib/profile.js 한 곳 (02 §5.6)
  ({ path, body } = withProfile(method, path, body, currentSelection()));
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["content-type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, opts);
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    // 세션 만료·거절 → 로그인 게이트 재소환 (views/login.js가 듣는다).
    // /auth/* 는 제외 — 로그인 실패 401이 게이트를 다시 세우면 재귀다.
    // window 존부 확인은 node --test용 (이 모듈은 DOM 없이도 import된다)
    if (res.status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("claw:auth-required", { detail: { path } }));
    }
    throw new ApiError(res.status, data && data.detail !== undefined ? data.detail : data);
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body),
  put: (path, body) => request("PUT", path, body),
  patch: (path, body) => request("PATCH", path, body),
  del: (path) => request("DELETE", path),
};

/** 422 detail(pydantic 오류 배열)을 사람이 읽을 줄단위 텍스트로. */
export function errorText(err) {
  if (!(err instanceof ApiError)) return String(err);
  if (Array.isArray(err.detail)) {
    return err.detail.map((e) => `${(e.loc || []).join(".")}: ${e.msg}`).join("\n");
  }
  return typeof err.detail === "string" ? err.detail : err.message;
}

/**
 * 작업 진행 구독 — WS 우선, 연결 실패·유실 시 REST 폴링 폴백.
 * onUpdate(job)를 갱신마다 호출하고 종단 상태 job으로 resolve.
 */
export function watchJob(jobId, onUpdate) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (job) => {
      if (!settled) {
        settled = true;
        resolve(job);
      }
    };
    const fail = (err) => {
      if (!settled) {
        settled = true;
        reject(err);
      }
    };
    const poll = async () => {
      try {
        for (;;) {
          const job = await api.get(`/jobs/${jobId}`);
          onUpdate(job);
          if (TERMINAL.has(job.status)) return finish(job);
          await sleep(300);
        }
      } catch (err) {
        fail(err);
      }
    };
    let ws;
    try {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/ws/jobs/${jobId}`);
    } catch {
      poll();
      return;
    }
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.error) {
        ws.close();
        fail(new ApiError(404, msg.error));
        return;
      }
      onUpdate(msg);
      if (TERMINAL.has(msg.status)) {
        ws.close();
        finish(msg);
      }
    };
    ws.onclose = () => {
      if (!settled) poll(); // 서버 이탈·연결 실패 → 폴링 폴백
    };
  });
}

export const cancelJob = (jobId) => api.post(`/jobs/${jobId}/cancel`);
