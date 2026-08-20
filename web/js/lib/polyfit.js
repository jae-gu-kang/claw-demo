/** 구간별 다항식 회귀 (01 §3.4 백로그 1차) — 게인 테이블 → 근사식.

수치 계층(뷰·캔버스 분리, 테스트 대상). 스케줄 변수 축을 내부 경계로 구간
분할하고 구간마다 최소제곱 다항식을 적합 — 전 구간 단일 차수식 가정 없음.
적합은 센터·스케일 정규화 u=(x-c)/h 영역에서 정규방정식으로 풀어 컨디셔닝
확보 (차수 ≤ 6, 격자점 수십 개 규모 전제 — 데모 1D mach 17점).

경계 연속성(값·기울기 점프)과 잔차는 정량만 보고 — 허용치 판정은 설계자
소관 (max_adjacent_jump와 동일 원칙). 근사식의 스케줄 실주입은 범위 밖.
*/

/** 대칭 양정치 소계(n ≤ 7) 가우스 소거 — 부분 피벗. */
function solve(A, b) {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let k = 0; k < n; k++) {
    let p = k;
    for (let i = k + 1; i < n; i++) if (Math.abs(M[i][k]) > Math.abs(M[p][k])) p = i;
    [M[k], M[p]] = [M[p], M[k]];
    for (let i = k + 1; i < n; i++) {
      const f = M[i][k] / M[k][k];
      for (let j = k; j <= n; j++) M[i][j] -= f * M[k][j];
    }
  }
  const x = new Array(n).fill(0);
  for (let i = n - 1; i >= 0; i--) {
    let s = M[i][n];
    for (let j = i + 1; j < n; j++) s -= M[i][j] * x[j];
    x[i] = s / M[i][i];
  }
  return x;
}

/** 최소제곱 다항식 적합 — 반환 {coeffs(u-영역 오름차수), c, h, degree}.
 * 요청 차수는 점 개수-1로 클램프 (점 2개에 3차 요청 → 직선). */
export function polyfit(xs, ys, degree) {
  const n = xs.length;
  const d = Math.min(degree, n - 1);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const c = (x0 + x1) / 2;
  const h = (x1 - x0) / 2 || 1; // 단일점·동일점 구간 방어
  const m = d + 1;
  const ATA = Array.from({ length: m }, () => new Array(m).fill(0));
  const ATy = new Array(m).fill(0);
  for (let p = 0; p < n; p++) {
    const u = (xs[p] - c) / h;
    const pw = new Array(m);
    pw[0] = 1;
    for (let k = 1; k < m; k++) pw[k] = pw[k - 1] * u;
    for (let i = 0; i < m; i++) {
      ATy[i] += pw[i] * ys[p];
      for (let j = 0; j < m; j++) ATA[i][j] += pw[i] * pw[j];
    }
  }
  return { coeffs: solve(ATA, ATy), c, h, degree: d };
}

/** 적합식 평가 — u-영역 호너. */
export function evalFit(fit, x) {
  const u = (x - fit.c) / fit.h;
  let v = 0;
  for (let k = fit.coeffs.length - 1; k >= 0; k--) v = v * u + fit.coeffs[k];
  return v;
}

/** 적합식 기울기 dp/dx — u-영역 도함수 호너 / h (연쇄법칙). */
export function evalFitSlope(fit, x) {
  const u = (x - fit.c) / fit.h;
  let v = 0;
  for (let k = fit.coeffs.length - 1; k >= 1; k--) v = v * u + k * fit.coeffs[k];
  return v / fit.h;
}

/** u-영역 계수 → 원 x-영역 계수 [a0, a1, ...] (p(x) = Σ ak·x^k).
 * (x-c)^k 이항 전개 — 표시·근사식 반출용 (평가는 evalFit이 수치적으로 우수). */
export function rawCoeffs(fit) {
  const m = fit.coeffs.length;
  const a = new Array(m).fill(0);
  for (let k = 0; k < m; k++) {
    const ck = fit.coeffs[k] / fit.h ** k;
    let binom = 1; // C(k, j)
    for (let j = 0; j <= k; j++) {
      a[j] += ck * binom * (-fit.c) ** (k - j);
      binom = (binom * (k - j)) / (j + 1);
    }
  }
  return a;
}

/** 구간별 적합 — xs 오름차순 전제(스케줄 축 규격). boundaries는 내부 경계.
 *
 * 구간 i = [경계i, 경계i+1) — 내부 경계 위의 격자점은 우측 구간 소속, 마지막
 * 구간만 폐구간. 반환 {segments: [{x0, x1, fit, n}], maxResidual, rms,
 * joints: [{x, valueJump, slopeJump}]} — 실패 시 {error: 사유}.
 */
export function piecewisePolyfit(xs, ys, boundaries, degree) {
  if (!Number.isInteger(degree) || degree < 1 || degree > 6) {
    return { error: `차수는 1~6 정수: ${degree}` };
  }
  if (xs.length < 2) return { error: "격자점 2개 이상 필요" };
  const xmin = xs[0];
  const xmax = xs[xs.length - 1];
  const bs = [...boundaries].sort((a, b) => a - b);
  for (let i = 0; i < bs.length; i++) {
    if (!Number.isFinite(bs[i])) return { error: `경계가 수치 아님: ${bs[i]}` };
    if (bs[i] <= xmin || bs[i] >= xmax) {
      return { error: `경계 ${bs[i]}는 축 범위 (${xmin}, ${xmax}) 내부여야 함` };
    }
    if (i > 0 && bs[i] === bs[i - 1]) return { error: `경계 중복: ${bs[i]}` };
  }
  const edges = [xmin, ...bs, xmax];
  const segments = [];
  for (let i = 0; i + 1 < edges.length; i++) {
    const last = i + 2 === edges.length;
    const idx = [];
    for (let p = 0; p < xs.length; p++) {
      if (xs[p] >= edges[i] && (last ? xs[p] <= edges[i + 1] : xs[p] < edges[i + 1])) idx.push(p);
    }
    if (idx.length === 0) {
      return { error: `구간 [${edges[i]}, ${edges[i + 1]}]에 격자점 없음 — 경계 조정 필요` };
    }
    const fit = polyfit(idx.map((p) => xs[p]), idx.map((p) => ys[p]), degree);
    segments.push({ x0: edges[i], x1: edges[i + 1], fit, n: idx.length, idx });
  }
  let maxResidual = 0;
  let sq = 0;
  for (const s of segments) {
    for (const p of s.idx) {
      const r = ys[p] - evalFit(s.fit, xs[p]);
      if (Math.abs(r) > maxResidual) maxResidual = Math.abs(r);
      sq += r * r;
    }
  }
  const joints = bs.map((b, i) => ({
    x: b,
    valueJump: evalFit(segments[i + 1].fit, b) - evalFit(segments[i].fit, b),
    slopeJump: evalFitSlope(segments[i + 1].fit, b) - evalFitSlope(segments[i].fit, b),
  }));
  return { segments, maxResidual, rms: Math.sqrt(sq / xs.length), joints };
}

/** 오버레이 샘플 — 구간마다 등간격 perSegment+1점, 구간 사이 null 구분자
 * (경계 불연속을 선으로 잇지 않음 — lineChartCanvas의 null 끊김 규약). */
export function sampleFit(pw, perSegment = 40) {
  const x = [];
  const y = [];
  pw.segments.forEach((s, i) => {
    if (i > 0) {
      x.push(s.x0);
      y.push(null);
    }
    for (let k = 0; k <= perSegment; k++) {
      const xi = s.x0 + ((s.x1 - s.x0) * k) / perSegment;
      x.push(xi);
      y.push(evalFit(s.fit, xi));
    }
  });
  return { x, y };
}
