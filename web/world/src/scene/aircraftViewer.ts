/** 기체 탭 대표 그림 — 지금 계산에 쓰는 기체를 크게, 제자리에서 돌린다 (06 §8).
 *
 * 가상환경 번들의 **두 번째 진입점**이다(`main.tsx`). three는 이 번들에만 있고(06 §6), 번들을 나누면 three가
 * 두 벌 실린다. 그래서 기체 탭(`web/js/views/aircraft.js`)이 같은 번들을 동적 import해 이 함수만 부른다.
 *
 * 판단(요·고각·화면 맞춤·축 사상)은 `core/turntable.ts`·`core/modelaxes.ts`에 있고 테스트가 붙는다. 여기는 three
 * 조립과 포인터·키 배선뿐이다.
 *
 * ## 무엇을 그리나는 호출측이 정한다
 *
 * 문서의 표시 모델이 가리키는 GLB(`model`)와, 기준량에서 만든 도식(`schematic`, FRD 성분)을 함께 받는다. 모델을
 * 못 읽으면 **사유와 함께** 도식으로 물러난다 — 빈 무대로 두면 "기체가 없다"와 "파일이 없다"가 구별되지 않는다.
 * 모델의 애니메이션 클립은 돌리지 않는다(`models.ts`와 같은 이유 — 시뮬과 무관한 타면 동작을 그리게 된다).
 *
 * ## WebGL 컨텍스트는 반납한다
 *
 * 브라우저당 컨텍스트가 8~16개뿐이다. `dispose()`가 렌더러를 놓고 컨텍스트를 잃게 해, 탭을 오갈 때 쌓이지 않는다.
 * 늦게 도착한 GLB는 `disposed`를 보고 스스로 놓는다.
 */

import {
  ACESFilmicToneMapping, Box3, BufferAttribute, BufferGeometry, CircleGeometry, DirectionalLight, Group,
  HemisphereLight, Mesh, MeshStandardMaterial, PCFShadowMap, PMREMGenerator, PerspectiveCamera, Scene,
  ShadowMaterial, SRGBColorSpace, Vector3, WebGLRenderer, type Object3D,
} from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

import { frdToModelLocal } from "../core/modelaxes.ts";
import {
  KEY_STEP, START_VIEW, advanceYaw, cameraOffset, clampElev, dragView, fitDistance, wrapYaw,
  type TurntableExtent, type TurntableView,
} from "../core/turntable.ts";
import { modelUrl } from "../data/api.ts";
import { disposeMaterial, disposeTree } from "./dispose.ts";

/** 절차 도식 메시 — `web/js/lib/uavmesh.js`의 반환 모양(FRD 성분, 면마다 정점). */
export interface SchematicMesh {
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint16Array;
  groups: readonly { start: number; count: number; name: string }[];
}

export interface AircraftViewerOptions {
  /** 서버 자산 GLB 이름 — 없으면 도식만 그린다 */
  model: string | null;
  /** 모델이 없거나 못 읽었을 때 그릴 도식 */
  schematic: SchematicMesh | null;
  /** 자동 회전으로 시작할까 — 생략하면 사용자가 움직임 줄이기를 켜 두지 않았을 때만 돈다 */
  spin?: boolean;
  onStatus?: (s: AircraftViewerStatus) => void;
}

export interface AircraftViewerStatus {
  state: "loading" | "ready" | "failed";
  source: "model" | "schematic" | null;
  /** 도식으로 물러났거나 아무것도 못 그린 사유 */
  reason: string | null;
}

export interface AircraftViewerHandle {
  dispose(): void;
  setSpin(on: boolean): void;
  readonly spinning: boolean;
}

/** 도식 색 — 엘레본만 눈에 띄게(믹서가 쓰는 그 4면). 표시 선택이다 */
const SCHEMATIC_COLOR: Record<string, number> = { wing: 0xb8c1cb, elevon: 0xe08a2e, body: 0x7b8591 };

const prefersReducedMotion = (): boolean =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function schematicObject(mesh: SchematicMesh): Mesh {
  const n = mesh.positions.length / 3;
  const pos = new Float32Array(mesh.positions.length);
  const nrm = new Float32Array(mesh.normals.length);
  for (let i = 0; i < n; i++) {
    const k = 3 * i;
    pos.set(frdToModelLocal([mesh.positions[k]!, mesh.positions[k + 1]!, mesh.positions[k + 2]!]), k);
    nrm.set(frdToModelLocal([mesh.normals[k]!, mesh.normals[k + 1]!, mesh.normals[k + 2]!]), k);
  }
  const geo = new BufferGeometry();
  geo.setAttribute("position", new BufferAttribute(pos, 3));
  geo.setAttribute("normal", new BufferAttribute(nrm, 3));
  geo.setIndex(new BufferAttribute(new Uint16Array(mesh.indices), 1));
  const mats = mesh.groups.map((g, i) => {
    geo.addGroup(g.start, g.count, i);
    return new MeshStandardMaterial({ color: SCHEMATIC_COLOR[g.name] ?? 0xaab2bc, roughness: 0.55, metalness: 0.1 });
  });
  const obj = new Mesh(geo, mats);
  obj.castShadow = true;
  obj.receiveShadow = true;
  return obj;
}

export function mountAircraftViewer(container: HTMLElement, opts: AircraftViewerOptions): AircraftViewerHandle {
  const report = (s: AircraftViewerStatus) => opts.onStatus?.(s);
  const canvas = document.createElement("canvas");
  canvas.tabIndex = 0;
  canvas.setAttribute("aria-label", "기체 3D 형상 — 끌거나 화살표 키로 돌려 봅니다");
  // 가로 끌기는 회전, 세로 끌기는 페이지 스크롤 — 대표 그림이 폰에서 스크롤을 삼키지 않게
  canvas.style.touchAction = "pan-y";
  container.append(canvas);

  let renderer: WebGLRenderer;
  try {
    renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true });
  } catch (e) {
    canvas.remove();
    report({ state: "failed", source: null, reason: `WebGL을 열지 못했습니다 — ${(e as Error).message}` });
    return { dispose() {}, setSpin() {}, spinning: false };
  }
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  // PCFSoft는 three 0.185에서 폐기 경고를 내고 PCF로 바뀐다 — 처음부터 PCF에 radius로 가장자리를 푼다
  renderer.shadowMap.type = PCFShadowMap;
  renderer.setClearColor(0x000000, 0); // 배경은 CSS가 칠한다(탭 팔레트와 한 곳)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  const scene = new Scene();
  // 반사 환경 — 무광 회색 판이 되지 않게 하는 가장 싼 빛. 만든 뒤 원본 장면은 바로 놓는다
  const pmrem = new PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const envTex = pmrem.fromScene(room, 0.04).texture;
  disposeTree(room);
  scene.environment = envTex;
  scene.environmentIntensity = 0.85;

  const key = new DirectionalLight(0xffffff, 2.4);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.bias = -0.0005;
  key.shadow.radius = 4;
  scene.add(key, key.target, new HemisphereLight(0xffffff, 0x9aa6b4, 0.6));

  const turntable = new Group(); // 요가 여기 걸린다 — 카메라·조명은 선다(core/turntable.ts 머리말)
  scene.add(turntable);
  const ground = new Mesh(new CircleGeometry(1, 64), new ShadowMaterial({ opacity: 0.16 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  ground.visible = false;
  scene.add(ground);

  const camera = new PerspectiveCamera(30, 1, 0.01, 1000);
  let view: TurntableView = { ...START_VIEW };
  let spin = opts.spin ?? !prefersReducedMotion();
  let extent: TurntableExtent = { radial: 1, halfHeight: 0.2 };
  let disposed = false;
  let raf = 0;
  let last = 0;
  let drag: { id: number; x: number; y: number } | null = null;

  const render = () => {
    turntable.rotation.y = view.yaw;
    const dist = fitDistance(extent, view.elev, (camera.fov * Math.PI) / 180, camera.aspect);
    const [x, y, z] = cameraOffset(dist, view.elev);
    camera.position.set(x, y, z);
    camera.near = dist / 100;
    camera.far = dist * 10;
    camera.updateProjectionMatrix();
    camera.lookAt(0, 0, 0);
    renderer.render(scene, camera);
  };
  const tick = (now: number) => {
    raf = 0;
    if (disposed) return;
    const dt = last ? (now - last) / 1000 : 0;
    last = now;
    if (spin && !drag) view = { ...view, yaw: advanceYaw(view.yaw, dt) };
    render();
    if (spin) raf = requestAnimationFrame(tick);
    else last = 0; // 멈춘 사이의 시간을 다시 돌 때 한꺼번에 반영하지 않는다
  };
  const requestFrame = () => {
    if (!raf && !disposed) raf = requestAnimationFrame(tick);
  };

  /** 기체 중심을 회전축 위에 두고, 크기에 맞춰 바닥 그림자·조명·그림자 카메라를 세운다. */
  const place = (obj: Object3D) => {
    const box = new Box3().setFromObject(obj);
    const center = box.getCenter(new Vector3());
    const size = box.getSize(new Vector3());
    extent = { radial: Math.max(Math.hypot(size.x, size.z) / 2, 1e-3), halfHeight: size.y / 2 };
    const radius = Math.hypot(extent.radial, extent.halfHeight); // 조명·그림자 카메라·바닥 크기 기준
    obj.position.sub(center);
    turntable.add(obj);
    ground.position.y = box.min.y - center.y - 0.35 * radius; // 살짝 띄운다 — 그림자가 기체 밑에서 퍼져 보이게
    ground.scale.setScalar(radius * 1.8);
    ground.visible = true;
    key.position.set(radius * 2.2, radius * 4.5, radius * 2.6);
    const cam = key.shadow.camera;
    cam.left = -2 * radius;
    cam.right = 2 * radius;
    cam.top = 2 * radius;
    cam.bottom = -2 * radius;
    cam.near = 0.5 * radius;
    cam.far = 12 * radius;
    cam.updateProjectionMatrix(); // 안 부르면 그림자 카메라가 옛 절두체로 남아 그림자가 잘린다
    requestFrame();
  };

  const resize = () => {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (w <= 0 || h <= 0) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    requestFrame();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(container);

  const onDown = (e: PointerEvent) => {
    if (e.button !== 0) return;
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY };
    canvas.setPointerCapture(e.pointerId);
  };
  const onMove = (e: PointerEvent) => {
    if (!drag || e.pointerId !== drag.id) return;
    view = dragView(view, e.clientX - drag.x, e.clientY - drag.y);
    drag.x = e.clientX;
    drag.y = e.clientY;
    requestFrame();
  };
  const onUp = (e: PointerEvent) => {
    if (!drag || e.pointerId !== drag.id) return;
    drag = null;
    if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
    requestFrame();
  };
  const onKey = (e: KeyboardEvent) => {
    const step = ({ ArrowLeft: [-KEY_STEP, 0], ArrowRight: [KEY_STEP, 0], ArrowUp: [0, KEY_STEP],
      ArrowDown: [0, -KEY_STEP] } as Record<string, [number, number]>)[e.key];
    if (!step) return;
    e.preventDefault();
    view = { yaw: wrapYaw(view.yaw + step[0]), elev: clampElev(view.elev + step[1]) };
    requestFrame();
  };
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerup", onUp);
  canvas.addEventListener("pointercancel", onUp);
  canvas.addEventListener("keydown", onKey);

  const showSchematic = (reason: string | null) => {
    if (!opts.schematic) {
      report({ state: "failed", source: null, reason: reason ?? "그릴 형상이 없습니다" });
      return;
    }
    place(schematicObject(opts.schematic));
    report({ state: "ready", source: "schematic", reason });
  };

  report({ state: "loading", source: null, reason: null });
  if (opts.model) {
    const name = opts.model;
    new GLTFLoader().loadAsync(modelUrl(name)).then(
      (gltf) => {
        if (disposed) {
          disposeTree(gltf.scene);
          return;
        }
        gltf.scene.traverse((o) => {
          if ((o as Mesh).isMesh) {
            o.castShadow = true;
            o.receiveShadow = true;
          }
        });
        place(gltf.scene);
        report({ state: "ready", source: "model", reason: null });
      },
      (e: unknown) => {
        if (disposed) return;
        showSchematic(`표시 모델 파일(${name})을 읽지 못해 도식으로 대신 그립니다 — ${(e as Error)?.message ?? e}`);
      },
    );
  } else {
    showSchematic(null);
  }
  resize();

  return {
    dispose() {
      if (disposed) return;
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      ro.disconnect();
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointercancel", onUp);
      canvas.removeEventListener("keydown", onKey);
      disposeTree(turntable);
      ground.geometry.dispose();
      disposeMaterial(ground.material);
      envTex.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    },
    setSpin(on: boolean) {
      spin = on;
      last = 0;
      requestFrame();
    },
    get spinning() {
      return spin;
    },
  };
}
