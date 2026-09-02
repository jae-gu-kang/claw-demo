/** 서버와의 대화 — `web/js/api.js`를 그대로 쓰고 타입만 씌운다.
 *
 * 사본을 만들지 않는 이유는 다른 lib과 같다: 그 모듈이 WebSocket 폴백과 422 오류 평탄화를
 * 들고 있고 `api.test.js`가 그것을 시험한다. 여기서 fetch를 다시 짜면 두 벌이 갈린다.
 *
 * 지형 팩과 GLB는 `api.get`을 안 쓴다 — 그건 JSON 전용이라 바이너리를 못 받는다.
 */

import { api } from "../../../js/api.js";
import type { Replay, ResultRow } from "../core/types.ts";

const rawApi = api as { get(path: string): Promise<unknown> };

export interface WorldManifest {
  terrain: { name: string; bytes: number }[];
  reason: string | null;
  models: { name: string; bytes: number }[];
  models_reason: string | null;
  /** 이름이 겹쳐 뺀 것. **서버 필드명과 정확히 같아야 한다** — 응답을 캐스트로 받으므로
   *  이름이 틀리면 타입은 통과하고 화면에서 `undefined`가 된다. 그러면 두 목록이 캡션에
   *  영영 안 닿고, 이 필드가 없애려던 "GLB가 없습니다" 혼란이 그대로 되살아난다. */
  models_dropped_duplicate: string[];
  /** 매직이 아니거나 못 읽어 뺀 것. */
  models_dropped_unreadable: string[];
  tiles: { available: boolean; reason: string };
  root: string;
}

/** 목록의 한 줄 — `n`은 **다운샘플 전** 표본 수다. */
export interface SimResultRow extends ResultRow {
  n?: number;
  t_end?: number;
  aborted?: string | null;
}

/** 시뮬 결과 목록 — `kind === "sim"`만. */
export async function listSimResults(): Promise<SimResultRow[]> {
  const rows = (await rawApi.get("/results")) as SimResultRow[];
  return rows.filter((r) => r.kind === "sim");
}

/** 재생용 다운샘플 본문.
 *
 * **표본 수는 목록에서 온다.** 예전 화면은 `/results/{id}`를 먼저 받아 `n_total` 하나를
 * 읽었는데 그 응답이 결과 전체(중앙값 ~10 MB)라, 결과를 고를 때마다 서버가 그만큼을
 * 파싱해서 버렸다 — 무료 티어 512 MB에서 가장 유력한 OOM 경로다.
 */
export async function fetchReplay(id: string, stride: number): Promise<Replay> {
  return (await rawApi.get(`/sim/${id}/replay?stride=${stride}`)) as Replay;
}

export async function fetchWorldManifest(): Promise<WorldManifest> {
  return (await rawApi.get("/world/manifest")) as WorldManifest;
}

/** 지형 팩 — 바이너리라 `api.get`(JSON 전용)을 못 쓴다. */
export async function fetchTerrainPack(name: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const r = await fetch(`/api/world/terrain/${encodeURIComponent(name)}`, {
    cache: "no-cache", signal,
  });
  if (!r.ok) throw new Error(`지형 팩을 받지 못했습니다 (${r.status})`);
  return r.arrayBuffer();
}

/** GLB의 URL — GLTFLoader가 직접 받는다(같은 출처라 CSP 무변경). */
export function modelUrl(name: string): string {
  return `/api/world/model/${encodeURIComponent(name)}`;
}
