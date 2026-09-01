/** 측지 좌표 계층 — NED(원점 기준 m) ↔ 위경도 ↔ 지도 타일 (엔진 claw.env.geodesy의 짝).

배경지도·지형·3D 월드가 "이 NED 평면이 지구 어디에 놓였는가"를 알아야 해서 생긴 층이다.
DOM 무접촉 순수 함수만 — 타일 페치·캔버스 그리기는 views/ 소관.

## 왜 엔진과 같은 식이 여기 또 있나

웹은 프레임마다 NED→타일 좌표를 계산하므로 서버 왕복이 불가능하다. 이 리포는 같은 중복을
이미 두 번 허용했다(lib/mission.js의 COND_KINDS는 엔진 _COND_ARITY의 사본, lib/wpmap.js의
planProfile은 엔진 path.py _leg_alt 모양의 사본). 규약도 같다 — **정본은 엔진, 웹은 그릴
만큼만, 어긋남은 테스트가 잡는다**. 여기서는 한 걸음 더 가서 `data/geodesy-fixture.json`을
엔진 테스트와 **같이 읽는다**(geo.test.js) — 한쪽만 고치면 반대쪽이 즉시 빨개진다.

## 수직축은 변환하지 않는다

이 리포의 NED D축은 곧 MSL 고도의 부호 반전이라(h = −pos_n[2]) 원점과 해면 사이에 오프셋이
없다. `hRef`는 **곡률반경을 평가할 기준 고도일 뿐** 수직 원점이 아니다.

## 1차 접평면 근사의 오차

곡률반경을 원점에서 한 번만 평가한다. φ=34.6°에서 원점 20 km 지점의 누적 오차는 약 0.3 m —
수치표고모델 5 m 격자의 1/16이라 이 용도에 충분하다. 관심구역이 100 km 급이 되면 오차가
제곱으로 커지므로(약 8 m) 그때는 엄밀 변환으로 올려야 한다.
*/

// 각도 환산 — 규약 §3이 "인라인 환산계수 금지"라 측지 경로의 환산은 여기 한 곳뿐이다.
// (웹에는 엔진의 claw.common.units에 해당하는 모듈이 없어 이 파일이 그 자리를 맡는다.)
export const DEG2RAD = Math.PI / 180;
export const RAD2DEG = 180 / Math.PI;

// WGS-84 — 엔진 claw/env/constants.py와 같은 값이어야 한다 (geo.test.js가 대조).
export const WGS84_A = 6378137.0; // 장반경 [m]
export const WGS84_F = 1.0 / 298.257223563; // 편평률 [-]
export const WGS84_E2 = WGS84_F * (2.0 - WGS84_F); // 제1이심률 제곱 [-]

// 원점 위도 한계 — 이보다 극에 가까우면 cos(lat0)가 0에 수렴해 동서 스케일이 발산한다.
// 조용히 거대한 경도를 내놓는 대신 던진다 (엔진 geodesy.py와 같은 한계).
const LAT0_MAX_RAD = 89 * DEG2RAD;

/** 묘유선 곡률반경 N(φ) [m] — 경도(동/서) 방향 스케일. */
export function radiusPrimeVertical(latRad) {
  const sin2 = Math.sin(latRad) ** 2;
  return WGS84_A / Math.sqrt(1 - WGS84_E2 * sin2);
}

/** 자오선 곡률반경 M(φ) [m] — 위도(남/북) 방향 스케일. */
export function radiusMeridian(latRad) {
  const sin2 = Math.sin(latRad) ** 2;
  return (WGS84_A * (1 - WGS84_E2)) / (1 - WGS84_E2 * sin2) ** 1.5;
}

/** 원점에서의 국지 스케일 {north, east} [m/rad].
 *
 * 둘의 비가 곧 위도에 따른 동서 압축이다 — φ=34.6°에서 동/북 ≈ 0.8269.
 * (cos φ = 0.8231과 미세하게 다르다: M(φ) ≠ N(φ)이기 때문이다.)
 */
export function localScales(lat0Rad, hRef = 0) {
  if (!Number.isFinite(lat0Rad)) throw new Error(`원점 위도는 유한값이어야 함: ${lat0Rad}`);
  if (Math.abs(lat0Rad) > LAT0_MAX_RAD) {
    throw new Error(
      `원점 위도 |${(lat0Rad * RAD2DEG).toFixed(4)}°| > 89° — 국지 접평면 근사가 성립하지 않음`,
    );
  }
  if (!Number.isFinite(hRef)) throw new Error(`기준 고도는 유한값이어야 함: ${hRef}`);
  return {
    north: radiusMeridian(lat0Rad) + hRef,
    east: (radiusPrimeVertical(lat0Rad) + hRef) * Math.cos(lat0Rad),
  };
}

/** NED 수평 (n, e) [m] → {latRad, lonRad}. origin = {latRad, lonRad, hRef?}. */
export function nedToGeodetic(n, e, origin) {
  const s = localScales(origin.latRad, origin.hRef ?? 0);
  return { latRad: origin.latRad + n / s.north, lonRad: origin.lonRad + e / s.east };
}

/** {latRad, lonRad} → NED 수평 {n, e} [m]. nedToGeodetic의 정확한 역함수. */
export function geodeticToNed(latRad, lonRad, origin) {
  const s = localScales(origin.latRad, origin.hRef ?? 0);
  return { n: (latRad - origin.latRad) * s.north, e: (lonRad - origin.lonRad) * s.east };
}

/* ---------------------------------------------------------------------------
   타일 스킴

   **스킴을 자료구조로 둔 이유**: 국토정보플랫폼 WMTS의 타일매트릭스셋이 EPSG:3857이 아니라
   EPSG:5179(UTM-K)일 가능성이 있고, GetCapabilities로 확인하기 전에는 단정할 수 없다.
   스킴을 하드코딩하면 확인 결과에 따라 이 모듈을 통째로 다시 쓴다 — 객체로 두면 스킴을
   하나 더 얹는 것으로 끝나고 **소비자는 무변경**이다. 브이월드는 3857이 확실하다.
--------------------------------------------------------------------------- */

/** 구면 메르카토르 (EPSG:3857) — 브이월드·OSM 계열이 쓰는 표준 타일 격자. */
export const WEB_MERCATOR = {
  crs: "EPSG:3857",
  tileSize: 256,
  // z=0에서 타일 하나가 덮는 **투영** 해상도 [m/px]. 2πa/256.
  resolutionAt: (z) => (2 * Math.PI * WGS84_A) / (WEB_MERCATOR.tileSize * 2 ** z),
  // 메르카토르는 극을 표현하지 못한다 — 정사각 세계지도가 되는 위도에서 자른다.
  latClipRad: 85.05112877980659 * DEG2RAD,
  /** (위도, 경도) → 세계 정규좌표 [0, 1)². 범위 밖 위도는 null (조용한 Infinity 금지). */
  forward(latRad, lonRad) {
    if (!Number.isFinite(latRad) || !Number.isFinite(lonRad)) return null;
    if (Math.abs(latRad) > this.latClipRad) return null;
    const s = Math.sin(latRad);
    return {
      u: 0.5 + lonRad / (2 * Math.PI),
      v: 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI),
    };
  },
  /** 세계 정규좌표 [0, 1)² → {latRad, lonRad}. forward의 역함수. */
  inverse(u, v) {
    return {
      latRad: 2 * Math.atan(Math.exp((0.5 - v) * 2 * Math.PI)) - Math.PI / 2,
      lonRad: (u - 0.5) * 2 * Math.PI,
    };
  },
};

/** 메르카토르 스케일 계수 1/cos φ — **투영 미터 ÷ 지상 미터**.
 *
 * φ=34.6°에서 1.215다. 이것을 잊고 투영 미터를 지상 미터로 쓰면 배경지도가 21.5% 크게
 * 깔리고, 궤적과 지도가 어긋나는데 원인이 화면에 보이지 않는다.
 */
export function mercatorScaleFactor(latRad) {
  return 1 / Math.cos(latRad);
}

/** 줌 z에서의 **지상** 해상도 [m/px] — 투영 해상도에 cos φ를 곱한 것. */
export function groundMetersPerPixel(scheme, latRad, z) {
  return scheme.resolutionAt(z) * Math.cos(latRad);
}

/** (위도, 경도, z) → {x, y, fx, fy} 타일 좌표. 범위 밖 위도는 null.
 *
 * fx·fy는 타일 안에서의 소수 위치 [0, 1) — 정렬 확인과 부분 타일 그리기에 쓴다.
 */
export function tileOf(scheme, latRad, lonRad, z) {
  const w = scheme.forward(latRad, lonRad);
  if (w === null) return null;
  const n = 2 ** z;
  const gx = w.u * n;
  const gy = w.v * n;
  // 경도가 정확히 ±180°면 x가 n 또는 −1이 된다 — 존재하지 않는 타일이므로 양쪽을 클램프.
  // 위쪽만 막으면 대척 자오선 서쪽에서 **음수 타일 x**가 나가고, 그 URL은 조용히 404다.
  const x = Math.min(Math.max(Math.floor(gx), 0), n - 1);
  const y = Math.min(Math.max(Math.floor(gy), 0), n - 1);
  return { x, y, fx: gx - x, fy: gy - y };
}

/** 타일 (z, x, y)의 측지 경계 {west, south, east, north} [rad]. */
export function tileBoundsGeodetic(scheme, z, x, y) {
  const n = 2 ** z;
  const nw = scheme.inverse(x / n, y / n);
  const se = scheme.inverse((x + 1) / n, (y + 1) / n);
  return { west: nw.lonRad, north: nw.latRad, east: se.lonRad, south: se.latRad };
}

/** 화면 축척에 맞는 줌 — 타일 1픽셀이 디바이스 1픽셀이 되게 고른다.
 *
 * groundMPerCssPx는 **논리(CSS) 픽셀당 지상 미터**다. views/plots.js makeCanvas가 이미
 * ctx.scale(dpr, dpr)을 걸어 두어 그리기 좌표가 논리 px이므로, 여기서 dpr을 나눠 장치
 * 픽셀 기준으로 환산한다. 그 결과 drawImage는 항상 **축소** 방향으로 리샘플해 선명하다.
 */
export function zoomForScale(scheme, groundMPerCssPx, latRad, { dpr = 1, zMin = 0, zMax = 21 } = {}) {
  if (!(groundMPerCssPx > 0)) throw new Error(`축척은 양수여야 함: ${groundMPerCssPx}`);
  const target = groundMPerCssPx / dpr; // 장치 픽셀당 지상 미터
  const z = Math.round(Math.log2(groundMetersPerPixel(scheme, latRad, 0) / target));
  return Math.min(Math.max(z, zMin), zMax);
}
