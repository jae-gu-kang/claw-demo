/** 3D 월드 렌더러 — three.js 구현 (views/worldrenderer.js가 정의한 계약).

## 이 파일이 three에서 쓰는 것 = 자체 WebGL2 구현이 채워야 할 표면

    WebGLRenderer · Scene · PerspectiveCamera · FogExp2
    BufferGeometry · BufferAttribute · Mesh · LineSegments · Group
    MeshStandardMaterial · MeshBasicMaterial · LineBasicMaterial · ShaderMaterial
    DirectionalLight · HemisphereLight
    Vector3 · Color · SphereGeometry · PlaneGeometry
    ACESFilmicToneMapping · SRGBColorSpace · BackSide · DoubleSide

**목록이 늘면 여기에 적는다.** 애드온(examples/jsm)은 반입하지 않는다 — 궤도 조작은
lib/camera.js가, 하늘은 아래 셰이더가 맡는다. (vendor/three/VERSION 참조)

## 축 변환은 이 파일 한 곳에만 있다

NED(n 북, e 동, d 하) → three(x 동, y 위, z 남) 사상은 `toWorld` 하나뿐이다:

    x = e,  y = −d,  z = −n

행렬식이 +1이라 오른손 좌표계가 보존된다 — 기체가 거울상이 되지 않는다.
lib/ 계층은 전부 NED로만 이야기하므로 이 줄만 바꾸면 다른 렌더러로 옮겨 간다.
*/

import {
  ACESFilmicToneMapping, BackSide, BufferAttribute, BufferGeometry, Color, DirectionalLight,
  DoubleSide, FogExp2, Group, HemisphereLight, LineBasicMaterial, LineSegments,
  Mesh, MeshBasicMaterial, MeshStandardMaterial, PerspectiveCamera, PlaneGeometry, Scene,
  ShaderMaterial, SphereGeometry, SRGBColorSpace, Vector3, WebGLRenderer,
} from "../vendor/three/three.module.js";
import { nedToRender } from "../lib/world3d.js";

/** NED [n, e, d] → three 월드 [x, y, z]. **이 파일의 유일한 축 변환.**
 *
 * 정본은 lib/world3d.js의 `nedToRender`다 — 지형 삼각형의 감김이 옳은지는 이 사상 아래에서만
 * 판정되므로, 그 테스트와 여기가 같은 함수를 읽어야 한다(따로 적으면 어댑터가 바뀌어도
 * 테스트가 옛 사상 기준으로 계속 초록이다). */
const toWorld = nedToRender;
const vecWorld = (p) => new Vector3(...toWorld(p[0], p[1], p[2]));

// 원거리 지형까지 담으려면 near/far 비가 16,000:1이 된다 — 로그 깊이버퍼 없이는
// 먼 곳에서 z-fighting이 난다(면들이 서로 뚫고 나오며 깜빡인다).
const NEAR = 3;
const FAR = 50000;
const SKY_RADIUS = FAR * 0.9;

/** 가시거리 V [m]에서 투과율이 2%가 되는 FogExp2 밀도. exp(−(dρ)²) = 0.02 → ρ = 1.978/V. */
export const fogDensityForVisibility = (v) => 1.978 / Math.max(v, 1);

const SKY_VERT = `
varying vec3 vDir;
void main() {
  vDir = normalize(position);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

// Preetham 같은 물리 모델이 아니라 **표시용 그라디언트**다 — 캡션이 그 사실을 밝힌다.
// 천정→지평 보간에 태양 원반과 그 둘레 번짐을 얹는다. 지평선 색이 곧 안개색이라
// 먼 지형이 회색 띠가 아니라 하늘로 녹아든다.
const SKY_FRAG = `
varying vec3 vDir;
uniform vec3 uZenith;
uniform vec3 uHorizon;
uniform vec3 uGround;
uniform vec3 uSunDir;
uniform float uSunIntensity;
void main() {
  vec3 dir = normalize(vDir);
  float h = dir.y;
  vec3 sky = mix(uHorizon, uZenith, pow(clamp(h, 0.0, 1.0), 0.45));
  vec3 col = mix(uGround, sky, smoothstep(-0.06, 0.02, h));
  float cosA = dot(dir, normalize(uSunDir));
  col += uSunIntensity * vec3(1.0, 0.93, 0.80) * pow(max(cosA, 0.0), 900.0) * 12.0; // 원반
  col += uSunIntensity * vec3(1.0, 0.85, 0.65) * pow(max(cosA, 0.0), 8.0) * 0.30;   // 둘레 번짐
  gl_FragColor = vec4(col, 1.0);
}`;

/** 렌더러 생성 — 실패하면 던지지 않고 호출측(worldrenderer.js)이 사유를 문장으로 낸다. */
export function createThreeRenderer(canvas, context) {
  // context는 worldrenderer.js가 antialias를 켜서 만들어 준 것 — 여기서 다시 만들면
  // 그 속성이 무시된다 (같은 캔버스의 두 번째 getContext는 기존 컨텍스트를 돌려준다).
  const renderer = new WebGLRenderer({ canvas, context, logarithmicDepthBuffer: true });
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;

  const scene = new Scene();
  const camera = new PerspectiveCamera(55, 1, NEAR, FAR);
  const fog = new FogExp2(0x9fb4c7, fogDensityForVisibility(25000));
  scene.fog = fog;

  const sunLight = new DirectionalLight(0xfff3e0, 2.4);
  const skyLight = new HemisphereLight(0xbcd6f0, 0x6b6f5a, 0.9);
  scene.add(sunLight, skyLight);

  // **depthTest를 끄고 가장 먼저 그린다.**
  //
  // logarithmicDepthBuffer를 켜면 three의 기본 재질은 프래그먼트에서 gl_FragDepth에
  // 로그 깊이를 써 넣는다(<logdepthbuf_fragment> 청크). 커스텀 ShaderMaterial은 그 청크를
  // 포함하지 않으므로 표준 z를 남기고, 그러면 지면이 채워 둔 로그 깊이와 비교가 어긋나
  // **하늘이 통째로 깊이 테스트에서 탈락한다**(화면이 검게 나온다 — 셰이더는 멀쩡한데
  // 원인이 전혀 안 보이는 부류다).
  //
  // 청크를 넣어 맞추는 대신 깊이 테스트를 끈다: 하늘은 배경이라 언제나 가장 뒤이고,
  // renderOrder로 먼저 그린 뒤 depthWrite:false로 깊이버퍼를 건드리지 않으면 나머지가
  // 그 위에 그려진다. three의 내부 청크 구성에 기대지 않아 버전 올림에도 안전하다.
  const skyMat = new ShaderMaterial({
    side: BackSide, depthWrite: false, depthTest: false, fog: false,
    vertexShader: SKY_VERT, fragmentShader: SKY_FRAG,
    uniforms: {
      uZenith: { value: new Color(0x2f6fb0) },
      uHorizon: { value: new Color(0x9fb4c7) },
      uGround: { value: new Color(0x5d6352) },
      uSunDir: { value: new Vector3(0.4, 0.6, 0.2) },
      uSunIntensity: { value: 1.0 },
    },
  });
  const sky = new Mesh(new SphereGeometry(SKY_RADIUS, 32, 20), skyMat);
  sky.renderOrder = -1; // 배경이므로 가장 먼저 (위 주석 참조)
  sky.frustumCulled = false; // 카메라를 따라다니므로 컬링 판정이 뜻이 없다
  scene.add(sky);

  // 장면 그룹 — 교체 시 통째로 비운다(누적 방지)
  const groups = {
    terrain: new Group(), ground: new Group(), paths: new Group(),
    marks: new Group(), model: new Group(),
  };
  for (const g of Object.values(groups)) scene.add(g);

  let stats = { drawCalls: 0, triangles: 0, ms: 0 };

  return {
    canvas,

    resize(w, h, dpr) {
      renderer.setPixelRatio(Math.min(dpr, 2)); // dpr 3 기기에서 픽셀 수가 9배가 되는 것 방지
      renderer.setSize(w, h, false);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    },

    setEnvironment({ sunAzEl, visibility, exposure, groundColor }) {
      const [az, el] = sunAzEl;
      // 태양 방향을 NED로 만든 뒤 같은 toWorld를 태운다 — 하늘·직사광·안개가 한 값에서 나온다
      const dirNed = [Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), -Math.sin(el)];
      const w = toWorld(...dirNed);
      skyMat.uniforms.uSunDir.value.set(...w);
      sunLight.position.set(w[0] * 1000, w[1] * 1000, w[2] * 1000);
      // 해가 낮을수록 지평선이 붉어지고 빛이 약해진다 — 표시 효과다(기상 모델 아님)
      const low = 1 - Math.min(Math.max(Math.sin(el), 0), 1);
      const horizon = new Color(0x9fb4c7).lerp(new Color(0xd9a066), low * 0.8);
      skyMat.uniforms.uHorizon.value.copy(horizon);
      skyMat.uniforms.uSunIntensity.value = Math.max(Math.sin(el), 0.05);
      sunLight.intensity = 0.6 + 2.0 * Math.max(Math.sin(el), 0);
      // **안개색 = 지평선 하늘색** — 먼 지형이 회색 띠가 아니라 하늘로 녹아든다
      fog.color.copy(horizon);
      fog.density = fogDensityForVisibility(visibility);
      if (groundColor != null) skyMat.uniforms.uGround.value.set(groundColor);
      renderer.toneMappingExposure = exposure;
    },

    /** 지형 메시 — lib/terrainpack.js가 만든 NED 기하를 그대로 받는다.
     *
     * 색은 고도 램프(hypsometric)이고 음영은 **진짜 법선에 조명이 닿아** 생긴다 —
     * 힐셰이드를 따로 계산하지 않는다. 영상 텍스처가 붙기 전까지의 표현이며 캡션이
     * "표고 음영 — 영상지도 아님"을 말한다.
     */
    setTerrain(patches) {
      clearGroup(groups.terrain);
      for (const p of patches) {
        const n = p.positions.length;
        const pos = new Float32Array(n);
        const nrm = new Float32Array(n);
        const col = new Float32Array(n);
        for (let i = 0; i < n; i += 3) {
          // 결측 정점은 lib이 NaN으로 두었고 인덱스가 참조하지 않는다. 그런데 NaN이
          // 속성 배열에 남으면 three의 바운딩 스피어가 NaN이 되어 **메시 전체가
          // 프러스텀 컬링으로 사라진다.** 그리지 않을 정점이므로 유한값으로 눌러 둔다.
          const d = Number.isFinite(p.positions[i + 2]) ? p.positions[i + 2] : 0;
          const w = toWorld(p.positions[i], p.positions[i + 1], d);
          pos[i] = w[0]; pos[i + 1] = w[1]; pos[i + 2] = w[2];
          const nw = toWorld(p.normals[i], p.normals[i + 1], p.normals[i + 2]);
          nrm[i] = nw[0]; nrm[i + 1] = nw[1]; nrm[i + 2] = nw[2];
          hypsometric(-d, col, i);
        }
        const geo = new BufferGeometry();
        geo.setAttribute("position", new BufferAttribute(pos, 3));
        geo.setAttribute("normal", new BufferAttribute(nrm, 3));
        geo.setAttribute("color", new BufferAttribute(col, 3));
        geo.setIndex(new BufferAttribute(p.indices, 1));
        groups.terrain.add(new Mesh(geo, new MeshStandardMaterial({
          vertexColors: true, roughness: 0.95, metalness: 0, flatShading: false,
        })));
      }
    },

    /** 지면·활주로·발사 레일 — 지형이 없을 때의 기준면. 교체 시 통째로 다시 만든다. */
    setGround({ elevation, grid, runway, rail, showPlane = true, showGrid = true }) {
      clearGroup(groups.ground);
      // 기준면 판은 **지형이 없을 때만** 그린다. 지형이 있는데도 깔면 두 지면이 겹쳐
      // 어느 쪽이 진짜인지 화면이 말할 수 없다.
      if (showPlane) {
        const plane = new Mesh(
          new PlaneGeometry(grid.extent, grid.extent),
          new MeshStandardMaterial({
            color: 0x6e7a5e, roughness: 1, metalness: 0, side: DoubleSide,
          }),
        );
        plane.rotation.x = -Math.PI / 2;
        plane.position.set(...toWorld(0, 0, -elevation));
        groups.ground.add(plane);
      }
      if (showGrid) groups.ground.add(gridLines(grid, elevation));
      if (runway) groups.ground.add(runwayMarks(runway));
      if (rail) groups.ground.add(railMark(rail));
    },

    setPaths(lines) {
      clearGroup(groups.paths);
      for (const ln of lines) {
        if (ln.points.length < 6) continue; // 점 2개 미만은 선이 아니다
        groups.paths.add(polyline(ln));
      }
    },

    setMarkers(marks) {
      clearGroup(groups.marks);
      for (const m of marks) groups.marks.add(markerFor(m));
    },

    setModelMesh(mesh) {
      clearGroup(groups.model);
      if (mesh == null) return;
      const geo = new BufferGeometry();
      // 메시는 FRD 성분으로 저장돼 있고, 축 변환은 setModelPose의 행렬이 한다 —
      // 정점을 미리 돌려 두면 자세 행렬과 두 번 도는 실수가 나기 쉽다
      geo.setAttribute("position", new BufferAttribute(mesh.positions, 3));
      geo.setAttribute("normal", new BufferAttribute(mesh.normals, 3));
      geo.setIndex(new BufferAttribute(mesh.indices, 1));
      for (const g of mesh.groups) geo.addGroup(g.start, g.count, materialIndexOf(g.name));
      const obj = new Mesh(geo, [
        new MeshStandardMaterial({ color: 0xd8dbe0, roughness: 0.55, metalness: 0.1 }),
        new MeshStandardMaterial({ color: 0xff9500, roughness: 0.5, metalness: 0.1 }),
        new MeshStandardMaterial({ color: 0x4a5058, roughness: 0.6, metalness: 0.2 }),
      ]);
      obj.matrixAutoUpdate = false;
      obj.visible = false; // setModelPose가 켠다 — 자세 없이 원점에 눕지 않게
      groups.model.add(obj);
    },

    /** 자세 적용 — 동체축의 NED 성분을 그대로 열로 세운 회전행렬.
     *
     * 쿼터니언을 three의 Quaternion으로 옮기지 않는 이유: 그러면 NED↔three 축 변환과
     * 쿼터니언 규약(scalar-first vs xyzw)을 동시에 맞춰야 해서 부호 실수가 나기 쉽다.
     * 축 벡터 셋을 각각 toWorld에 태우면 변환이 한 번뿐이고 눈으로 검증된다.
     */
    setModelPose(pose) {
      const obj = groups.model.children[0];
      if (!obj) return;
      if (pose == null) { obj.visible = false; return; }
      const { pos, axes, scale = 1 } = pose;
      const fx = toWorld(...axes.forward);
      const ry = toWorld(...axes.right);
      const dz = toWorld(...axes.down);
      const p = toWorld(...pos);
      obj.matrix.set(
        fx[0] * scale, ry[0] * scale, dz[0] * scale, p[0],
        fx[1] * scale, ry[1] * scale, dz[1] * scale, p[1],
        fx[2] * scale, ry[2] * scale, dz[2] * scale, p[2],
        0, 0, 0, 1,
      );
      obj.visible = true;
    },

    render(cam) {
      const t0 = performance.now();
      camera.position.copy(vecWorld(cam.eye));
      camera.up.copy(vecWorld(cam.up).normalize());
      camera.lookAt(vecWorld(cam.target));
      camera.fov = (cam.fovY * 180) / Math.PI;
      camera.updateProjectionMatrix();
      sky.position.copy(camera.position); // 하늘돔은 카메라를 따라다닌다 (무한 멀리)
      renderer.render(scene, camera);
      stats = {
        drawCalls: renderer.info.render.calls,
        triangles: renderer.info.render.triangles,
        ms: performance.now() - t0,
      };
    },

    stats: () => stats,

    describe: () => ({
      name: "three.js",
      api: renderer.capabilities.isWebGL2 ? "WebGL2" : "WebGL1",
      maxTextureSize: renderer.capabilities.maxTextureSize,
      maxAnisotropy: renderer.capabilities.getMaxAnisotropy(),
    }),

    dispose() {
      for (const g of Object.values(groups)) clearGroup(g);
      sky.geometry.dispose();
      skyMat.dispose();
      renderer.dispose();
      // dispose()는 리스너·프로그램·렌더리스트만 정리하고 **컨텍스트는 놓지 않는다**
      // (three.module.js의 WebGLRenderer.dispose 참조). 캔버스가 GC될 때까지 컨텍스트가
      // 남으면 브라우저당 8~16개 한계를 탭 전환 몇 번으로 태운다 — 그 한계가 애초에
      // main.js에 dispose 훅을 넣은 이유이므로 여기서 결정적으로 반납한다.
      renderer.forceContextLoss();
    },
  };
}

/* ---------------- 장면 조각 ---------------- */

/** 고도 램프 — 해면(모래빛) → 초지 → 숲 → 능선(바위빛). 표시용 색이지 토지피복이 아니다. */
const RAMP = [
  [0, [0.72, 0.70, 0.58]], [8, [0.42, 0.52, 0.32]], [80, [0.30, 0.44, 0.26]],
  [250, [0.38, 0.40, 0.30]], [600, [0.55, 0.52, 0.48]], [1200, [0.78, 0.78, 0.76]],
];

function hypsometric(h, out, i) {
  // 램프 밖은 양 끝 색으로 고정한다. 이 분기가 없어도 아래 폴백이 우연히 같은 결과를 내지만,
  // 그것은 RAMP의 첫·끝 항목이 지금 자리에 있다는 사실에 기대는 것이다.
  const first = RAMP[0], last = RAMP[RAMP.length - 1];
  const edge = h <= first[0] ? first : h >= last[0] ? last : null;
  if (edge) {
    out[i] = edge[1][0]; out[i + 1] = edge[1][1]; out[i + 2] = edge[1][2];
    return;
  }
  let a = first, b = last;
  for (let k = 0; k + 1 < RAMP.length; k++) {
    if (h >= RAMP[k][0] && h <= RAMP[k + 1][0]) { a = RAMP[k]; b = RAMP[k + 1]; break; }
  }
  const t = b[0] === a[0] ? 0 : Math.min(Math.max((h - a[0]) / (b[0] - a[0]), 0), 1);
  out[i] = a[1][0] + (b[1][0] - a[1][0]) * t;
  out[i + 1] = a[1][1] + (b[1][1] - a[1][1]) * t;
  out[i + 2] = a[1][2] + (b[1][2] - a[1][2]) * t;
}

function materialIndexOf(name) {
  return name === "elevon" ? 1 : name === "body" ? 2 : 0;
}

function gridLines({ extent, step }, elevation) {
  const pts = [];
  const half = extent / 2;
  for (let v = -half; v <= half + 1e-9; v += step) {
    pts.push(...toWorld(v, -half, -elevation), ...toWorld(v, half, -elevation));
    pts.push(...toWorld(-half, v, -elevation), ...toWorld(half, v, -elevation));
  }
  const geo = new BufferGeometry();
  geo.setAttribute("position", new BufferAttribute(new Float32Array(pts), 3));
  return new LineSegments(geo, new LineBasicMaterial({
    color: 0x8b9481, transparent: true, opacity: 0.5, fog: true,
  }));
}

/** 활주로 — **중심선만** 그린다. 폭은 결과 meta에 없고, 지어내면 화면이 없는 사실을 말한다.
 *  기하(원점에서 heading 방향 length 구간)는 lib/replay.js의 착륙 판정과 같은 규약이다. */
function runwayMarks({ elevation, heading, length }) {
  const g = new Group();
  const n1 = Math.cos(heading) * length;
  const e1 = Math.sin(heading) * length;
  g.add(segment([0, 0, -elevation], [n1, e1, -elevation], 0xffffff, 2));
  // 시단·종단 표시 — 접지 지점을 눈으로 짚을 수 있게
  for (const [n, e] of [[0, 0], [n1, e1]]) {
    const perp = [-Math.sin(heading) * 22, Math.cos(heading) * 22];
    g.add(segment([n - perp[0], e - perp[1], -elevation],
                  [n + perp[0], e + perp[1], -elevation], 0xffffff, 2));
  }
  return g;
}

/** 발사 레일 — 기부에서 앙각·방위 방향으로 length만큼. origin_height가 기부 높이다. */
function railMark({ elevation, length, elev_angle, azimuth, origin_height }) {
  const base = [0, 0, -(elevation + origin_height)];
  const tip = [
    base[0] + Math.cos(elev_angle) * Math.cos(azimuth) * length,
    base[1] + Math.cos(elev_angle) * Math.sin(azimuth) * length,
    base[2] - Math.sin(elev_angle) * length,
  ];
  const g = new Group();
  g.add(segment(base, tip, 0xff375f, 3));
  g.add(segment([0, 0, -elevation], base, 0xff375f, 2)); // 발사대 기둥
  return g;
}

function segment(a, b, color, width) {
  const geo = new BufferGeometry();
  geo.setAttribute("position", new BufferAttribute(
    new Float32Array([...toWorld(...a), ...toWorld(...b)]), 3));
  return new LineSegments(geo, new LineBasicMaterial({ color, linewidth: width }));
}

/** 폴리라인 — points는 NED 평탄 배열, breaks 인덱스에서 선을 끊는다(결측 구간).
 *
 * **양 끝을 다 본다.** 다음 점만 보면 결측에서 *나가는* 구간(k → k+1)이 살아남고, 그
 * 시작점이 결측 자리라 궤적이 엉뚱한 곳에서 뻗어 나온다. lib/world3d.js가 그 자리를
 * NaN으로 채워 두어 설사 새어 나가도 선이 그려지지는 않지만, 끊기는 여기서 맞춘다.
 */
function polyline({ points, color, breaks }) {
  const out = [];
  const cut = new Set(breaks ?? []);
  for (let i = 0; i + 5 < points.length; i += 3) {
    const a = i / 3;
    if (cut.has(a) || cut.has(a + 1)) continue;
    out.push(...toWorld(points[i], points[i + 1], points[i + 2]));
    out.push(...toWorld(points[i + 3], points[i + 4], points[i + 5]));
  }
  const geo = new BufferGeometry();
  geo.setAttribute("position", new BufferAttribute(new Float32Array(out), 3));
  return new LineSegments(geo, new LineBasicMaterial({ color }));
}

function markerFor({ ne, kind, radius }) {
  if (kind === "waypoint") {
    const g = new Group();
    g.add(segment([ne[0], ne[1], ne[2]], [ne[0], ne[1], ne[2] - 120], 0xff9500, 2));
    if (radius > 0) g.add(circle(ne, radius, 0xff9500));
    return g;
  }
  const m = new Mesh(new SphereGeometry(kind === "start" ? 14 : 10, 12, 10),
    new MeshBasicMaterial({ color: kind === "start" ? 0x34c759 : 0x007aff }));
  m.position.copy(vecWorld(ne));
  return m;
}

function circle(center, radius, color, n = 64) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    for (const k of [i, (i + 1) % n]) {
      const a = (2 * Math.PI * k) / n;
      pts.push(...toWorld(center[0] + radius * Math.cos(a),
                          center[1] + radius * Math.sin(a), center[2]));
    }
  }
  const geo = new BufferGeometry();
  geo.setAttribute("position", new BufferAttribute(new Float32Array(pts), 3));
  return new LineSegments(geo, new LineBasicMaterial({ color, transparent: true, opacity: 0.7 }));
}

function clearGroup(g) {
  for (const child of [...g.children]) {
    g.remove(child);
    child.traverse?.((o) => {
      o.geometry?.dispose?.();
      const m = o.material;
      if (Array.isArray(m)) m.forEach((x) => x.dispose?.());
      else m?.dispose?.();
    });
  }
}
