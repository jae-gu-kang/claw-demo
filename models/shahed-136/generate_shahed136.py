# SHAHED-136형 무인기 — 조종면(엘레본·러더)이 분리되어 움직이는 .blend 생성 스크립트
#
# 실행:  blender -b --factory-startup -P generate_shahed136.py
#        SHAHED_VARIANT=eoir blender -b --factory-startup -P generate_shahed136.py   (EOIR형)
# 산출:  shahed136.blend  (+ preview.png, shahed136.glb) — EOIR형은 각 이름에 _eoir
#
# 좌표계(블렌더, Z-up): +Y 기수 방향, +X 우현, +Z 상방.
# FRD 동체축(docs/conventions.md §1)과의 대응: FRD x(전방)=+Y, y(우측)=+X, z(하방)=-Z.
# 타면 부호(conventions.md §5): 엘레본 + = 뒷전 내림(TE down), 러더 + = 뒷전 좌(TE left).
#
# 치수는 공개 보도 기반 근사(전장 ~3.5 m, 익폭 ~2.5 m)의 시각화용 형상이며
# 실기체 설계 데이터가 아니다.

import bpy
import bmesh
import math
import os
import sys

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 변형 — 기체는 같고 기수만 갈린다. 산출 파일 이름이 갈리므로 서로의 산출물을 덮지 않는다.
#   ""     기본형: 원추 기수                → shahed136.blend / .glb / preview.png
#   "eoir" EOIR형: 기수 대신 2축 짐벌 볼    → shahed136_eoir.blend / .glb / preview_eoir.png
VARIANT = os.environ.get("SHAHED_VARIANT", "").strip().lower()
if VARIANT not in ("", "eoir"):
    sys.exit("[gen] 알 수 없는 SHAHED_VARIANT=%r (허용: '', 'eoir')" % VARIANT)
EOIR = VARIANT == "eoir"
SUFFIX = "_" + VARIANT if VARIANT else ""

# 내장 numpy가 못 뜨는 블렌더 빌드가 있다 — glTF 내보내기가 그때 조용히 빠진다.
# 사유·증상·복구는 models/blender_numpy.py 참조. **bpy.ops 호출 전에** 부른다.
sys.path.insert(0, os.path.dirname(OUT_DIR))  # models/
from blender_numpy import ensure_numpy  # noqa: E402

ensure_numpy(repo_root=os.path.dirname(os.path.dirname(OUT_DIR)))

# ---------------------------------------------------------------- 기본 장면
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "SHAHED-136"
scene.unit_settings.system = 'METRIC'
scene.unit_settings.length_unit = 'METERS'
scene.render.fps = 24
scene.frame_start, scene.frame_end = 1, 168

col_model = bpy.data.collections.new("SHAHED-136")
col_studio = bpy.data.collections.new("Studio")
scene.collection.children.link(col_model)
scene.collection.children.link(col_studio)


# ---------------------------------------------------------------- 헬퍼
def loft(bm, rings, cap_start=True, cap_end=True):
    """같은 점수의 닫힌 링 목록을 사각형 면으로 잇는다."""
    prev = first = None
    for ring in rings:
        verts = [bm.verts.new(co) for co in ring]
        if prev is not None:
            n = len(verts)
            for i in range(n):
                bm.faces.new((prev[i], prev[(i + 1) % n],
                              verts[(i + 1) % n], verts[i]))
        else:
            first = verts
        prev = verts
    if cap_start:
        bm.faces.new(list(reversed(first)))
    if cap_end:
        bm.faces.new(prev)


def finish_bm(name, bm, mats, collection):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    return ob


SUPERELLIPSE_E = 2.7                            # 동체 단면 기본 지수


def superellipse_ring(y, w, h, zc, n=28, e=SUPERELLIPSE_E):
    pts = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        pts.append((w * math.copysign(abs(c) ** (2.0 / e), c),
                    y,
                    zc + h * math.copysign(abs(s) ** (2.0 / e), s)))
    return pts


def circle_ring(n, r, axis, at):
    """axis: 링이 놓이는 평면의 법선('x'|'y'|'z'), at: 중심 (3,)"""
    pts = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        u, v = r * math.cos(a), r * math.sin(a)
        if axis == 'x':
            pts.append((at[0], at[1] + u, at[2] + v))
        elif axis == 'y':
            pts.append((at[0] + u, at[1], at[2] + v))
        else:
            pts.append((at[0] + u, at[1] + v, at[2]))
    return pts


def airfoil_ring(x, y_le, y_te, t, zc, n=12):
    """앞전 뾰족·뒷전 뾰족 렌즈형 익형 단면(스팬 방향 x 고정)."""
    pts = []
    for i in range(n + 1):                      # 윗면 LE→TE
        s = i / n
        y = y_le + (y_te - y_le) * s
        pts.append((x, y, zc + 0.5 * t * math.sin(math.pi * s ** 0.72)))
    for i in range(n - 1, 0, -1):               # 아랫면 TE→LE
        s = i / n
        y = y_le + (y_te - y_le) * s
        pts.append((x, y, zc - 0.5 * t * math.sin(math.pi * s ** 0.72)))
    return pts


def make_mat(name, color, rough=0.55, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    m.diffuse_color = (*color, 1.0)
    return m


def shade_smooth(ob, angle_deg=40.0):
    me = ob.data
    for p in me.polygons:
        p.use_smooth = True
    try:                                        # 4.0.x
        me.use_auto_smooth = True
        me.auto_smooth_angle = math.radians(angle_deg)
    except AttributeError:                      # 4.1+
        pass


def apply_modifiers(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    old = ob.data
    ob.data = me
    ob.modifiers.clear()
    bpy.data.meshes.remove(old)


# ---------------------------------------------------------------- 재질
MAT_AIRFRAME = make_mat("Airframe", (0.615, 0.625, 0.600), rough=0.55)
MAT_DARK = make_mat("DarkDetail", (0.055, 0.058, 0.062), rough=0.45)
MAT_CTRL = make_mat("ControlSurface", (0.430, 0.450, 0.435), rough=0.55)

# ---------------------------------------------------------------- 동체
bm = bmesh.new()
# 기수부 — 기본형은 원추. EOIR형은 1.25 m 선을 이어 받아 원형 짐벌 칼라(r 0.090, y 1.44)로
# 모으고, 그 앞에 볼이 앉는다. 다섯 번째 값은 초타원 지수 e(생략 시 2.7) — 칼라 끝을 2.0(원)으로.
if EOIR:
    nose = [(1.44, 0.090, 0.090, -0.005, 2.0),
            (1.40, 0.094, 0.099, -0.005, 2.35)]
else:
    nose = [(1.75, 0.010, 0.010, 0.000),
            (1.55, 0.055, 0.065, -0.005)]
stations = nose + [                             # (y, 반폭, 반높이, z 중심[, e])
    (1.25, 0.115, 0.125, -0.005),
    (0.85, 0.185, 0.180, 0.000),
    (0.35, 0.245, 0.215, 0.000),
    (-0.15, 0.280, 0.230, 0.000),
    (-0.65, 0.285, 0.225, 0.000),
    (-1.10, 0.255, 0.205, 0.000),
    (-1.45, 0.195, 0.175, 0.000),
    (-1.70, 0.115, 0.130, 0.010),
]
loft(bm, [superellipse_ring(y, w, h, zc, e=e[0] if e else SUPERELLIPSE_E)
          for y, w, h, zc, *e in stations])

# 꼬리 페어링(엔진부 수렴)
loft(bm, [superellipse_ring(-1.699, 0.112, 0.127, 0.010),
          superellipse_ring(-1.77, 0.062, 0.072, 0.010)])

# 엔진 실린더 헤드(좌·우 돌출)
for sx in (1.0, -1.0):
    loft(bm, [circle_ring(16, 0.050, 'x', (sx * 0.20, -1.38, 0.02)),
              circle_ring(16, 0.050, 'x', (sx * 0.33, -1.38, 0.02))])

# 상부 안테나 돔
loft(bm, [circle_ring(16, 0.055, 'z', (0.0, -0.50, 0.205)),
          circle_ring(16, 0.048, 'z', (0.0, -0.50, 0.242)),
          circle_ring(16, 0.030, 'z', (0.0, -0.50, 0.266)),
          circle_ring(16, 0.001, 'z', (0.0, -0.50, 0.276))])

fuselage = finish_bm("Fuselage", bm, [MAT_AIRFRAME, MAT_DARK], col_model)
NOSE_DARK_Y = 1.39 if EOIR else 1.28            # EOIR형은 칼라 띠(1.40~1.44)만 — 짐벌 하우징
for p in fuselage.data.polygons:                # 기수 캡(EOIR형은 칼라)·실린더 헤드는 어두운 재질
    c = p.center
    if c.y > NOSE_DARK_Y or (abs(c.x) > 0.205 and c.y < -1.25 and abs(c.z - 0.02) < 0.12):
        p.material_index = 1
shade_smooth(fuselage)

# ---------------------------------------------------------------- 주익(델타)
WING_ZC = -0.02
Y_TE = -1.45


def y_le(x):
    return 0.95 - 1.8067 * (x - 0.06)


def thick(x):
    return 0.10 - 0.07 * (x - 0.06) / 1.19


bm = bmesh.new()
for side in (1.0, -1.0):
    xs = [0.10, 0.40, 0.70, 0.95, 1.15, 1.25]
    rings = [airfoil_ring(side * x, y_le(x), Y_TE, thick(x), WING_ZC)
             for x in xs]
    loft(bm, rings)
wing = finish_bm("Wing", bm, [MAT_AIRFRAME], col_model)

# 엘레본 자리 절개(불리언) — 스팬 0.38~1.12 m, 힌지선 y = -1.262
for sx, tag in ((1.0, "R"), (-1.0, "L")):
    bm = bmesh.new()
    x0, x1 = sorted((sx * 0.38, sx * 1.12))
    loft(bm, [
        [(x0, -1.55, -0.15), (x0, -1.262, -0.15), (x0, -1.262, 0.12), (x0, -1.55, 0.12)],
        [(x1, -1.55, -0.15), (x1, -1.262, -0.15), (x1, -1.262, 0.12), (x1, -1.55, 0.12)],
    ])
    cutter = finish_bm("cut_elevon_" + tag, bm, [], col_model)
    mod = wing.modifiers.new("cut", 'BOOLEAN')
    mod.object, mod.operation, mod.solver = cutter, 'DIFFERENCE', 'EXACT'
    apply_modifiers(wing)
    bpy.data.objects.remove(cutter)

# ---------------------------------------------------------------- 엘레본 (분리 오브젝트, 인/아웃보드 × 좌/우 = 4면)
# 규약 §5의 4면 배치: collective δe = 4면 평균(피치), differential δa = (좌−우)/2 (롤)
elevons = {}
for sx, side in ((1.0, "R"), (-1.0, "L")):
    for seg, xc in (("In", 0.565), ("Out", 0.935)):   # 스팬 중심(절개부 0.38~1.12 안)
        bm = bmesh.new()
        rings = []
        for lx in (-0.175, 0.175):              # 로컬 x = 힌지축(스팬 방향)
            rings.append([(lx, -0.006, 0.012), (lx, -0.190, 0.002),
                          (lx, -0.190, -0.002), (lx, -0.006, -0.012)])
        loft(bm, rings)
        # 밑줄 이름 — glTF/three.js는 노드 이름의 점(.)을 지운다. 밑줄은 보존되므로
        # Blender와 three.js에서 같은 이름(Elevon_In_L …)으로 조회된다.
        ob = finish_bm("Elevon_%s_%s" % (seg, side), bm, [MAT_CTRL], col_model)
        ob.location = (sx * xc, -1.262, WING_ZC)      # 원점 = 힌지선 위
        elevons[seg + side] = ob

# ---------------------------------------------------------------- 수직핀(윙팁) + 러더
FIN_PENT = [(-1.52, 0.36), (-1.24, 0.36), (-0.88, 0.02),
            (-1.10, -0.22), (-1.52, -0.22)]     # (y, z) 윤곽
fins, rudders = {}, {}
for sx, tag in ((1.0, "R"), (-1.0, "L")):
    bm = bmesh.new()
    x0, x1 = sorted((sx * 1.228, sx * 1.252))
    loft(bm, [[(x0, y, WING_ZC + z) for y, z in FIN_PENT],
              [(x1, y, WING_ZC + z) for y, z in FIN_PENT]])
    fin = finish_bm("Fin_" + tag, bm, [MAT_AIRFRAME], col_model)

    # 러더 자리 절개 — 힌지선 y = -1.383
    bm = bmesh.new()
    cx0, cx1 = sorted((sx * 1.15, sx * 1.35))
    loft(bm, [
        [(cx0, -1.60, -0.30), (cx0, -1.383, -0.30), (cx0, -1.383, 0.42), (cx0, -1.60, 0.42)],
        [(cx1, -1.60, -0.30), (cx1, -1.383, -0.30), (cx1, -1.383, 0.42), (cx1, -1.60, 0.42)],
    ])
    cutter = finish_bm("cut_rudder_" + tag, bm, [], col_model)
    mod = fin.modifiers.new("cut", 'BOOLEAN')
    mod.object, mod.operation, mod.solver = cutter, 'DIFFERENCE', 'EXACT'
    apply_modifiers(fin)
    bpy.data.objects.remove(cutter)
    fins[tag] = fin

    # 러더(분리 오브젝트) — 로컬 z = 힌지축(수직)
    bm = bmesh.new()
    rings = []
    for lz in (-0.264, 0.264):
        rings.append([(0.010, -0.006, lz), (0.002, -0.131, lz),
                      (-0.002, -0.131, lz), (-0.010, -0.006, lz)])
    loft(bm, rings)
    ob = finish_bm("Rudder_" + tag, bm, [MAT_CTRL], col_model)
    ob.location = (sx * 1.24, -1.383, WING_ZC + 0.07)
    rudders[tag] = ob

# ---------------------------------------------------------------- 프로펠러 (분리 오브젝트, 후방 푸셔)
bm = bmesh.new()
loft(bm, [circle_ring(20, 0.004, 'y', (0, -0.105, 0)),   # 스피너(로컬 좌표)
          circle_ring(20, 0.026, 'y', (0, -0.075, 0)),
          circle_ring(20, 0.042, 'y', (0, -0.040, 0)),
          circle_ring(20, 0.050, 'y', (0, 0.000, 0)),
          circle_ring(20, 0.050, 'y', (0, 0.020, 0))])

BLADE = [                                       # (z, 반코드, 반두께, 피치각 deg)
    (0.03, 0.040, 0.009, 28.0),
    (0.16, 0.046, 0.008, 24.0),
    (0.32, 0.040, 0.0065, 18.0),
    (0.45, 0.026, 0.005, 14.0),
]
for mirror in (1.0, -1.0):                      # 2엽 — R_y(180°) 대칭
    rings = []
    for z, cx, cy, ang in BLADE:
        a = math.radians(ang)
        ring = []
        for px, py in ((cx, cy), (cx, -cy), (-cx, -cy), (-cx, cy)):
            rx = px * math.cos(a) - py * math.sin(a)
            ry = px * math.sin(a) + py * math.cos(a)
            ring.append((mirror * rx, ry - 0.005, mirror * z))
        rings.append(ring)
    loft(bm, rings)
prop = finish_bm("Propeller", bm, [MAT_DARK], col_model)
prop.location = (0.0, -1.80, 0.0)               # 원점 = 회전축(로컬 y)
shade_smooth(prop)

# ---------------------------------------------------------------- EOIR 짐벌 (EOIR형만 — 분리 오브젝트 2축)
# 칼라 앞에 볼이 앉는다. 외측 EOIR_Pan(방위, 로컬 Z) › 내측 EOIR_Tilt(고각, 로컬 X).
# 두 원점 = 볼 중심 = 두 축의 교점 — 볼은 어느 자세에서도 외형이 같고 창만 돈다.
# 보어사이트 = 로컬 +Y(기수 방향). 부호는 FRD 오일러와 같은 뜻: pan + = 우측, tilt + = 위.
eoir = {}
if EOIR:
    EOIR_R = 0.100                              # 볼 반경 — 칼라(0.090)보다 커서 칼라 끝 캡을 가린다
    EOIR_C = (0.0, 1.470, -0.005)               # 볼 중심 — 칼라 축 위
    WIN_Y = 0.085                               # 창 절단면(로컬 y) → 창 반경 √(R²−y²) ≈ 0.053

    MAT_EOIR = make_mat("EOIR_Housing", (0.150, 0.155, 0.160), rough=0.40, metal=0.30)
    MAT_WINDOW = make_mat("EOIR_Window", (0.010, 0.012, 0.015), rough=0.08)
    MAT_LENS_EO = make_mat("EOIR_Lens_EO", (0.020, 0.040, 0.075), rough=0.03, metal=0.60)
    MAT_LENS_IR = make_mat("EOIR_Lens_IR", (0.300, 0.250, 0.170), rough=0.15, metal=0.90)

    # 볼 — 구 앞면을 잘라 평판 창을 붙인다. 재질 인덱스: 0 하우징, 1 창, 2 EO 렌즈, 3 IR 렌즈
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=40, v_segments=20, radius=EOIR_R)
    for f in bm.faces:
        f.smooth = True
    cut = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                                 dist=1e-6, plane_co=(0.0, WIN_Y, 0.0),
                                 plane_no=(0.0, 1.0, 0.0), clear_outer=True)
    rim = [g for g in cut["geom_cut"] if isinstance(g, bmesh.types.BMEdge)]
    bmesh.ops.contextual_create(bm, geom=rim)

    # 개구 — 창 앞으로 4 mm 솟은 경통, 그 안에 렌즈가 1.5 mm 들어가 앉는다
    APERTURES = [(-0.018, 0.008, 0.022, 2),     # (로컬 x, 로컬 z, 반경, 렌즈 재질) EO 주광
                 (0.022, 0.010, 0.015, 3),      # IR 열상
                 (0.020, -0.026, 0.007, 2)]     # 레이저 거리측정
    y_back, y_front, y_lens = WIN_Y - 0.002, WIN_Y + 0.004, WIN_Y + 0.0025
    for ax, az, r, _lens in APERTURES:
        loft(bm, [circle_ring(24, r, 'y', (ax, y_back, az)),
                  circle_ring(24, r, 'y', (ax, y_front, az)),
                  circle_ring(24, 0.78 * r, 'y', (ax, y_front, az)),
                  circle_ring(24, 0.78 * r, 'y', (ax, y_lens, az))])

    # 재질은 형상이 다 선 뒤 **좌표로** 칠한다. bm.faces 순서는 생성 순서가 아니다 —
    # `bm.faces[n0:]`를 새 면으로 믿고 칠했더니 창 면이 섞여 하우징 재질로 덮였다(실측).
    def on_plane(f, y):
        return all(abs(v.co.y - y) < 1e-6 for v in f.verts)

    for f in bm.faces:
        if on_plane(f, WIN_Y):
            f.material_index, f.smooth = 1, False
        elif on_plane(f, y_lens):
            c = f.calc_center_median()
            f.material_index = next(lens for ax, az, r, lens in APERTURES
                                    if (c.x - ax) ** 2 + (c.z - az) ** 2 < r * r)
    tilt = finish_bm("EOIR_Tilt", bm, [MAT_EOIR, MAT_WINDOW, MAT_LENS_EO, MAT_LENS_IR],
                     col_model)
    tilt.location = EOIR_C

    # 방위 요크 — 볼 좌·우의 고각축 캡(트러니언). 방위만 타고 고각은 안 탄다 → 고각축이 보인다.
    # 볼 면에 거의 붙인다(3 mm): 캡은 방위를 타고 뒤로 돌면 볼 옆면과 함께 칼라 안으로 들어가는데,
    # 크게 솟아 있으면 칼라 끝에서 잘린 캡이 보였다(확대 렌더 실측, 반경 30 mm·9 mm 돌출 때).
    bm = bmesh.new()
    for sx in (1.0, -1.0):
        loft(bm, [circle_ring(20, 0.024, 'x', (sx * 0.090, 0.0, 0.0)),
                  circle_ring(20, 0.024, 'x', (sx * (EOIR_R + 0.0015), 0.0, 0.0)),
                  circle_ring(20, 0.016, 'x', (sx * (EOIR_R + 0.003), 0.0, 0.0))])
    pan = finish_bm("EOIR_Pan", bm, [MAT_EOIR], col_model)
    pan.location = EOIR_C
    eoir = {"pan": pan, "tilt": tilt}

# ---------------------------------------------------------------- 루트 엠프티 + 계층
root = bpy.data.objects.new("SHAHED136_Root", None)
root.empty_display_type = 'PLAIN_AXES'
root.empty_display_size = 0.6
col_model.objects.link(root)

bpy.context.view_layer.update()


def parent_to(child, parent):
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()


parent_to(fuselage, root)
parent_to(wing, fuselage)
parent_to(prop, fuselage)
for ob in elevons.values():
    parent_to(ob, wing)
for tag in ("L", "R"):
    parent_to(fins[tag], wing)
    parent_to(rudders[tag], fins[tag])
if EOIR:
    parent_to(eoir["pan"], fuselage)
    parent_to(eoir["tilt"], eoir["pan"])

# ---------------------------------------------------------------- 조종 프로퍼티 + 드라이버
PROPS = [
    ("elevon_in_left", 0.0, -30, 30, "좌 인보드 엘레본 [deg], + = 뒷전 내림(TE down)"),
    ("elevon_out_left", 0.0, -30, 30, "좌 아웃보드 엘레본 [deg], + = 뒷전 내림(TE down)"),
    ("elevon_in_right", 0.0, -30, 30, "우 인보드 엘레본 [deg], + = 뒷전 내림(TE down)"),
    ("elevon_out_right", 0.0, -30, 30, "우 아웃보드 엘레본 [deg], + = 뒷전 내림(TE down)"),
    ("rudder_left", 0.0, -30, 30, "좌 러더 변위 [deg], + = 뒷전 좌(TE left)"),
    ("rudder_right", 0.0, -30, 30, "우 러더 변위 [deg], + = 뒷전 좌(TE left)"),
    ("prop_speed", 45.0, 0, 120, "프로펠러 회전 [deg/frame]"),
]
if EOIR:
    PROPS += [
        ("eoir_pan", 0.0, -50, 50, "EOIR 방위(pan) [deg], + = 우측"),
        ("eoir_tilt", 0.0, -75, 30, "EOIR 고각(tilt) [deg], + = 위"),
    ]
for name, default, lo, hi, desc in PROPS:
    root[name] = float(default)
    ui = root.id_properties_ui(name)
    ui.update(min=lo, max=hi, soft_min=lo, soft_max=hi, description=desc)


def add_driver(ob, index, expr, prop_name):
    fc = ob.driver_add('rotation_euler', index)
    d = fc.driver
    d.type = 'SCRIPTED'
    v = d.variables.new()
    v.name = 'v' if index != 1 else 's'
    t = v.targets[0]
    t.id = root
    t.data_path = '["%s"]' % prop_name
    d.expression = expr


def limit_rot(ob, axis, lo=-35.0, hi=35.0):
    c = ob.constraints.new('LIMIT_ROTATION')
    setattr(c, 'use_limit_' + axis, True)
    setattr(c, 'min_' + axis, math.radians(lo))
    setattr(c, 'max_' + axis, math.radians(hi))
    c.owner_space = 'LOCAL'


# 엘레본: 로컬 X축 힌지. +X 회전 = 뒷전 내림 → 부호 그대로
add_driver(elevons["InL"], 0, 'radians(v)', "elevon_in_left")
add_driver(elevons["OutL"], 0, 'radians(v)', "elevon_out_left")
add_driver(elevons["InR"], 0, 'radians(v)', "elevon_in_right")
add_driver(elevons["OutR"], 0, 'radians(v)', "elevon_out_right")
# 러더: 로컬 Z축 힌지. +Z 회전 = 뒷전 우 → 규약(+ = TE left)에 맞춰 부호 반전
add_driver(rudders["L"], 2, '-radians(v)', "rudder_left")
add_driver(rudders["R"], 2, '-radians(v)', "rudder_right")
# 프로펠러: 프레임 비례 회전
add_driver(prop, 1, 'radians(s)*frame', "prop_speed")

for ob in elevons.values():
    limit_rot(ob, 'x')
for tag in ("L", "R"):
    limit_rot(rudders[tag], 'z')

if EOIR:
    # 방위: 로컬 Z. +Z 회전 = 보어사이트(+Y)가 좌(−X)로 → 규약(+ = 우측)에 맞춰 부호 반전
    add_driver(eoir["pan"], 2, '-radians(v)', "eoir_pan")
    # 고각: 로컬 X. +X 회전 = 보어사이트가 위(+Z)로 → 부호 그대로
    add_driver(eoir["tilt"], 0, 'radians(v)', "eoir_tilt")
    # 범위 = 창·렌즈가 동체에 닿지 않는 **직사각형**(동체 메시 대비 실측). 한 축만이면 pan ±80·
    # tilt −80까지 비지만 두 축을 함께 돌리면 줄어든다(tilt −60에서 pan ±70, −75에서 ±55부터
    # 닿기 시작, −80에서 ±35). 축별 리밋은 그 결합 영역을 못 그리므로 그 안에 드는 직사각형으로
    # 자른다 — ±50 × −75…+30은 1° 간격 전 영역에서 간섭 0.
    limit_rot(eoir["pan"], 'z', -50, 50)
    limit_rot(eoir["tilt"], 'x', -75, 30)

# ---------------------------------------------------------------- 데모 애니메이션 (루트 프로퍼티 키프레임)
# 롤(4면 차동) → 피치(4면 동상) → 인보드만 + 러더 → 아웃보드만 + 러더
DEMO = {
    "elevon_in_left":   [(1, 0), (18, 22), (42, -22), (66, 20), (90, -20),
                         (114, 18), (138, 0), (162, 0)],
    "elevon_in_right":  [(1, 0), (18, -22), (42, 22), (66, 20), (90, -20),
                         (114, 18), (138, 0), (162, 0)],
    "elevon_out_left":  [(1, 0), (18, 22), (42, -22), (66, 20), (90, -20),
                         (114, 0), (138, 18), (162, 0)],
    "elevon_out_right": [(1, 0), (18, -22), (42, 22), (66, 20), (90, -20),
                         (114, 0), (138, 18), (162, 0)],
    "rudder_left":  [(1, 0), (90, 0), (114, 22), (138, -22), (162, 0)],
    "rudder_right": [(1, 0), (90, 0), (114, 22), (138, -22), (162, 0)],
}
if EOIR:                                        # 짐벌 탐색: 좌우 훑기 → 내려다보며 추적 → 복귀
    DEMO["eoir_pan"] = [(1, 0), (30, -45), (72, 45), (100, 30), (138, -20), (162, 0)]
    DEMO["eoir_tilt"] = [(1, 0), (30, -10), (72, -10), (100, -35), (138, -60), (162, 0)]
for prop_name, keys in DEMO.items():
    for frame, value in keys:
        root[prop_name] = float(value)
        root.keyframe_insert(data_path='["%s"]' % prop_name, frame=frame)

# ---------------------------------------------------------------- 스튜디오(카메라·조명·월드)
world = bpy.data.worlds.new("Studio")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.82, 0.83, 0.85, 1.0)
scene.world = world

cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 43
cam = bpy.data.objects.new("Camera", cam_data)
# 기본형은 후방 쿼터뷰(타면 변위가 보인다), EOIR형은 전방 쿼터뷰(볼 창이 보인다)
cam.location = (2.7, 3.7, 1.35) if EOIR else (3.1, -4.0, 2.0)
col_studio.objects.link(cam)
tc = cam.constraints.new('TRACK_TO')
tc.target, tc.track_axis, tc.up_axis = root, 'TRACK_NEGATIVE_Z', 'UP_Y'
scene.camera = cam

sun_data = bpy.data.lights.new("Sun", 'SUN')
sun_data.energy = 3.0
sun = bpy.data.objects.new("Sun", sun_data)
sun.rotation_euler = (math.radians(55), 0.0, math.radians(35))
col_studio.objects.link(sun)

fill_data = bpy.data.lights.new("Fill", 'AREA')
fill_data.energy = 400.0
fill_data.size = 4.0
fill = bpy.data.objects.new("Fill", fill_data)
fill.location = (-2.8, -3.2, 2.0)
col_studio.objects.link(fill)
fc = fill.constraints.new('TRACK_TO')
fc.target, fc.track_axis, fc.up_axis = root, 'TRACK_NEGATIVE_Z', 'UP_Y'

# ---------------------------------------------------------------- 렌더 설정
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 64
scene.cycles.use_adaptive_sampling = True
try:
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = 'OPENIMAGEDENOISE'
except Exception:
    scene.cycles.use_denoising = False
scene.render.resolution_x = 1280
scene.render.resolution_y = 860
scene.render.image_settings.file_format = 'PNG'

# ---------------------------------------------------------------- 저장 → 내보내기 → 미리보기 렌더
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, "shahed136%s.blend" % SUFFIX))
print("[gen] saved shahed136%s.blend" % SUFFIX)

# 미리보기 렌더는 드라이버 리그가 온전한 상태에서 먼저 (GLB 베이크가 in-메모리 리그를 바꾸므로)
if os.environ.get("SHAHED_SKIP_RENDER") != "1":
    # 기본형: 엘레본 차동 + 러더 변위가 보이는 프레임 / EOIR형: 볼이 우측 45°로 돌아 창이 카메라를 보는 프레임
    scene.frame_set(72 if EOIR else 114)
    scene.render.filepath = os.path.join(OUT_DIR, "preview%s.png" % SUFFIX)
    try:
        bpy.ops.render.render(write_still=True)
        print("[gen] rendered preview%s.png" % SUFFIX)
    except Exception as exc:
        print("[gen] render failed:", exc)


# ---------------------------------------------------------------- three.js용 GLB 내보내기
# three.js(GLTFLoader)는 블렌더의 드라이버·커스텀 프로퍼티를 실행하지 않는다. 그래서
#   (1) 각 타면의 드라이버 모션을 프레임별로 샘플해 rotation_euler 키프레임으로 굽고
#       (노드 피벗은 힌지선 그대로 → three.js에서 코드로 직접 회전 가능),
#   (2) 데모 동작을 glTF 애니메이션 트랙으로 내보낸다(AnimationMixer로 바로 재생).
# 이 베이크는 이미 저장된 .blend가 아니라 in-메모리 상태만 바꾼다(스크립트 종료 시 폐기).
def export_threejs_glb(path):
    ctrl = [elevons["InL"], elevons["OutL"], elevons["InR"], elevons["OutR"],
            rudders["L"], rudders["R"], prop, *eoir.values()]

    frames = range(scene.frame_start, scene.frame_end + 1)
    samples = {ob: [] for ob in ctrl}           # 드라이버 결과를 먼저 샘플
    for f in frames:
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        for ob in ctrl:
            samples[ob].append((f, tuple(ob.evaluated_get(dg).rotation_euler)))

    for ob in ctrl:                             # 드라이버·컨스트레인트 제거 → 베이크 키프레임이 정본
        if ob.animation_data:
            for d in list(ob.animation_data.drivers):
                ob.animation_data.drivers.remove(d)
        for c in list(ob.constraints):
            ob.constraints.remove(c)
    if root.animation_data:                     # 루트 커스텀 프로퍼티 데모 액션은 glTF로 안 나가므로 정리
        root.animation_data_clear()

    for ob, seq in samples.items():             # 샘플값을 명시 키프레임으로
        for f, rot in seq:
            ob.rotation_euler = rot
            ob.keyframe_insert("rotation_euler", frame=f)

    for ob in bpy.data.objects:
        ob.select_set(ob.name in {o.name for o in col_model.objects})

    common = dict(filepath=path, export_format='GLB', use_selection=True,
                  export_animations=True, export_frame_range=True,
                  export_apply=False, export_yup=True)
    try:                                        # 씬 전체를 단일 클립으로 (three.js에 이상적)
        bpy.ops.export_scene.gltf(export_animation_mode='SCENE',
                                  export_anim_scene_split_object=False, **common)
    except TypeError:                           # 구버전 폴백
        bpy.ops.export_scene.gltf(**common)
    print("[gen] exported %s (three.js: rigged nodes + baked clip)" % os.path.basename(path))


try:
    export_threejs_glb(os.path.join(OUT_DIR, "shahed136%s.glb" % SUFFIX))
except Exception as exc:
    print("[gen] glb export skipped:", exc)

print("[gen] done. objects:", sorted(o.name for o in col_model.objects))
