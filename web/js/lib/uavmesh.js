/** 기체 형상 — 엔진 기준량에서 만드는 절차적 메시 (FRD 축, 렌더러 무관).

반환은 타입배열뿐이라 three.js도 장래의 자체 WebGL2도 그대로 쓴다. glTF 같은 파일 포맷
규약이 끼어들지 않는 것이 요점이다.

## 왜 여객기 모양을 그리지 않나

데모 기체는 `AeroModel(S=3.0, cbar=1.5, b=2.5)`이다 — 종횡비 b²/S ≈ 2.1의 **저종횡비**이고,
믹서가 4면 엘레본을 쓴다(fcl/mixer, 규약 §5). 이것은 델타/전익 형상이지 동체·주익·미익이
분리된 여객기가 아니다. 임의로 여객기를 그리면 화면이 기체를 잘못 말한다.

그래서 치수를 이 파일이 들고 있지 않고 **호출측이 결과 meta에서 받아 넘긴다**
(`meta.geometry` — §5.5 "엔진 기본값 재기술 금지"). 치수가 없는 결과에는 기체를 그리지 않는다.

## 무엇이 실측이고 무엇이 표시 선택인가

- **실측(엔진에서 옴)**: 스팬 b, 기준면적 S, 평균공력시위 c̄, 스키드 접촉점.
  뿌리시위는 삼각 평면형 가정에서 `c_root = 2S/b`로 유도한다 — 그 삼각형의 MAC이
  `(2/3)c_root`이고 데모 값에서 1.6 m로 c̄ 1.5 m와 맞아떨어져 가정이 자체 정합적이다.
- **표시 선택(임의)**: CG를 뿌리시위의 어디에 두는가, 동체 포드·수직미익의 크기.
  화면 캡션이 "형상은 기준량에서 만든 도식"이라고 밝혀야 한다.
*/

/** CG가 뿌리시위의 앞에서 몇 %인가 — **표시 선택**이다(공력중심이 아니다). */
const CG_AT_ROOT_CHORD = 0.4;
const THICK = 0.06; // 델타 판 반두께 [m] — 도식
const POD_HALF_W = 0.18; // 동체 포드 반폭 [m] — 도식
const FIN_HEIGHT = 0.55; // 수직미익 높이 [m] — 도식
const ELEVON_CHORD = 0.18; // 엘레본 시위 [m] — 도식 (4면 배치는 믹서 규약이 정본)
const N_ELEVON = 4;

/** 기체 메시 — geometry = {b, s_ref, cbar, gear_contacts?}.
 *
 * 반환 {positions, normals, indices, groups, landmarks, extent}.
 * `groups`는 three.js BufferGeometry.groups와 같은 모양이라 엘레본만 다른 색을 줄 수 있다.
 * `landmarks`는 테스트가 "요 90°면 기수가 동쪽"을 렌더러 없이 확인하는 데 쓴다.
 */
export function uavMesh(geometry) {
  const b = num(geometry?.b, "b");
  const sRef = num(geometry?.s_ref, "s_ref");
  const half = b / 2;
  const cRoot = (2 * sRef) / b; // 삼각 평면형 S = ½·b·c_root
  const xNose = CG_AT_ROOT_CHORD * cRoot;
  const xTe = xNose - cRoot;

  const P = [], N = [], I = [];
  const mesh = { P, N, I };

  // --- 델타 판 (뿌리 정점 → 좌우 익단) ---
  const noseT = [xNose, 0, -THICK], noseB = [xNose, 0, THICK];
  const tipLT = [xTe, -half, -THICK], tipRT = [xTe, half, -THICK];
  const tipLB = [xTe, -half, THICK], tipRB = [xTe, half, THICK];
  tri(mesh, noseT, tipRT, tipLT); // 윗면
  tri(mesh, noseB, tipLB, tipRB); // 아랫면
  quad(mesh, noseT, tipLT, tipLB, noseB); // 좌 앞전
  quad(mesh, noseT, noseB, tipRB, tipRT); // 우 앞전
  quad(mesh, tipLT, tipRT, tipRB, tipLB); // 뒷전

  // --- 엘레본 4면 (뒷전을 스팬 방향 4등분) — 믹서가 쓰는 그 4면 ---
  const elevonStart = I.length;
  for (let k = 0; k < N_ELEVON; k++) {
    const y0 = -half + (b * k) / N_ELEVON;
    const y1 = -half + (b * (k + 1)) / N_ELEVON;
    box(mesh, xTe - ELEVON_CHORD, xTe, y0 + 0.02, y1 - 0.02, -THICK * 0.7, THICK * 0.7);
  }
  const elevonCount = I.length - elevonStart;

  // --- 동체 포드 + 수직미익 + 스키드 ---
  const bodyStart = I.length;
  box(mesh, xTe + 0.1, xNose - 0.15, -POD_HALF_W, POD_HALF_W, -0.22, 0.14);
  const finX0 = xTe + 0.05, finX1 = xTe + 0.55;
  quad(mesh, [finX0, 0, -THICK], [finX1, 0, -THICK],
       [finX1, 0, -FIN_HEIGHT * 0.55], [finX0, 0, -FIN_HEIGHT]);
  quad(mesh, [finX1, 0, -THICK], [finX0, 0, -THICK],
       [finX0, 0, -FIN_HEIGHT], [finX1, 0, -FIN_HEIGHT * 0.55]);
  // 스키드는 있을 때만 — 없는 것을 그리지 않는다
  for (const c of geometry?.gear_contacts ?? []) {
    box(mesh, c[0] - 0.06, c[0] + 0.06, c[1] - 0.04, c[1] + 0.04, 0, c[2]);
  }
  const bodyCount = I.length - bodyStart;

  return {
    positions: new Float32Array(P),
    normals: new Float32Array(N),
    indices: new Uint16Array(I),
    groups: [
      { start: 0, count: elevonStart, name: "wing" },
      { start: elevonStart, count: elevonCount, name: "elevon" },
      { start: bodyStart, count: bodyCount, name: "body" },
    ],
    landmarks: {
      nose: [xNose, 0, 0],
      rightWingTip: [xTe, half, 0],
      leftWingTip: [xTe, -half, 0],
      finTop: [finX0, 0, -FIN_HEIGHT],
    },
    extent: { length: cRoot + 0.55, span: b, rootChord: cRoot, xNose, xTe },
  };
}

/* ---- 평평한 음영을 위해 면마다 정점을 따로 둔다 (정점 공유 없음) ---- */

function tri(m, a, b, c) {
  const nrm = normalOf(a, b, c);
  const base = m.P.length / 3;
  for (const v of [a, b, c]) {
    m.P.push(v[0], v[1], v[2]);
    m.N.push(nrm[0], nrm[1], nrm[2]);
  }
  m.I.push(base, base + 1, base + 2);
}

function quad(m, a, b, c, d) {
  const nrm = normalOf(a, b, c);
  const base = m.P.length / 3;
  for (const v of [a, b, c, d]) {
    m.P.push(v[0], v[1], v[2]);
    m.N.push(nrm[0], nrm[1], nrm[2]);
  }
  m.I.push(base, base + 1, base + 2, base, base + 2, base + 3);
}

/** 축 정렬 육면체 — FRD 기준 (x 전방, y 우현, z 하방). 여섯 면 다 바깥을 본다. */
function box(m, x0, x1, y0, y1, z0, z1) {
  const [X0, X1] = x0 <= x1 ? [x0, x1] : [x1, x0];
  const [Y0, Y1] = y0 <= y1 ? [y0, y1] : [y1, y0];
  const [Z0, Z1] = z0 <= z1 ? [z0, z1] : [z1, z0];
  quad(m, [X1, Y0, Z0], [X1, Y1, Z0], [X1, Y1, Z1], [X1, Y0, Z1]); // 앞 (+x)
  quad(m, [X0, Y1, Z0], [X0, Y0, Z0], [X0, Y0, Z1], [X0, Y1, Z1]); // 뒤 (−x)
  quad(m, [X0, Y1, Z0], [X1, Y1, Z0], [X1, Y1, Z1], [X0, Y1, Z1]); // 우 (+y)
  quad(m, [X1, Y0, Z0], [X0, Y0, Z0], [X0, Y0, Z1], [X1, Y0, Z1]); // 좌 (−y)
  quad(m, [X0, Y0, Z0], [X0, Y1, Z0], [X1, Y1, Z0], [X1, Y0, Z0]); // 위 (−z)
  quad(m, [X1, Y0, Z1], [X1, Y1, Z1], [X0, Y1, Z1], [X0, Y0, Z1]); // 아래 (+z)
}

function normalOf(a, b, c) {
  const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const len = Math.hypot(n[0], n[1], n[2]);
  // 퇴화 삼각형은 조용히 0 법선을 남기지 않는다 — 조명이 검게 죽는 원인이 안 보인다
  if (!(len > 0)) throw new Error("퇴화한 면 — 법선을 만들 수 없음");
  return [n[0] / len, n[1] / len, n[2] / len];
}

function num(v, what) {
  if (typeof v !== "number" || !Number.isFinite(v) || v <= 0) {
    throw new Error(`기체 형상 ${what}은(는) 양의 유한값이어야 함: ${v}`);
  }
  return v;
}
