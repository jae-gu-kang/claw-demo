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

from mathutils import Vector

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 변형 — 기체는 같고 기수만 갈린다. 산출 파일 이름이 갈리므로 서로의 산출물을 덮지 않는다.
#   ""     기본형: 원추 기수                → shahed136.blend / .glb / preview.png
#   "eoir" EOIR형: 총알형 EO/IR 헤드 기수   → shahed136_eoir.blend / .glb / preview_eoir.png
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
    for layer in list(bm.faces.layers.int.values()):   # 칠 표시(paint_new)는 산출물에 남기지 않는다
        bm.faces.layers.int.remove(layer)
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
    except AttributeError:                      # 4.1+ — 자동 스무스가 없어져 날카로운 모서리를 직접 표시
        me.set_sharp_from_angle(angle=math.radians(angle_deg))


def apply_modifiers(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    old = ob.data
    ob.data = me
    ob.modifiers.clear()
    bpy.data.meshes.remove(old)


def paint_new(bm, layer, mat, smooth=False, pick=None):
    """아직 안 칠한 면(layer 0)만 칠한다 — 형상을 하나 만든 직후 부른다.

    bm.faces 순서는 생성 순서가 아니므로(인덱스 슬라이스로 새 면을 고르다 창이 하우징색으로 덮인
    적이 있다) 면 레이어로 새 면을 가린다. pick(f)가 재질을 돌려주면 그것이 우선이다."""
    for f in bm.faces:
        if f[layer]:
            continue
        m = pick(f) if pick else None
        f[layer], f.material_index, f.smooth = 1, mat if m is None else m, smooth


def ring_x(x, cy, cz, ry, rz, e=2.0, n=16):
    """x 고정 평면(YZ)의 초타원 링 — 좌우로 뻗은 실린더·핀용."""
    pts = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        pts.append((x, cy + ry * math.copysign(abs(c) ** (2.0 / e), c),
                    cz + rz * math.copysign(abs(s) ** (2.0 / e), s)))
    return pts


def tube(bm, points, r, n=8):
    """점열을 따라가는 원형 튜브(양끝 막음) — 점화선·배기관·런너.
    링 기준축을 앞 링에서 이어 받아(평행 이동) 굽은 곳에서도 꼬이지 않는다."""
    pts = [Vector(p) for p in points]
    rings, e1 = [], None
    for i, p in enumerate(pts):
        d = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        e1 = d.orthogonal().normalized() if e1 is None else (e1 - d * e1.dot(d)).normalized()
        e2 = d.cross(e1)
        rings.append([tuple(p + (e1 * math.cos(2 * math.pi * k / n)
                                 + e2 * math.sin(2 * math.pi * k / n)) * r) for k in range(n)])
    loft(bm, rings)


# ---------------------------------------------------------------- 재질
MAT_AIRFRAME = make_mat("Airframe", (0.615, 0.625, 0.600), rough=0.55)
MAT_DARK = make_mat("DarkDetail", (0.055, 0.058, 0.062), rough=0.45)
MAT_CTRL = make_mat("ControlSurface", (0.430, 0.450, 0.435), rough=0.55)

# ---------------------------------------------------------------- 동체
bm = bmesh.new()
# 기수부 — 기본형은 원추. EOIR형은 실기체 사진처럼 **총알형**이다: 몸통을 원통에 가깝게 끌고 와
# 한 단 솟은 검은 띠(r 0.122, y 1.26~1.29)를 두르고, 같은 굵기(r 0.119)의 원통 기수를 1.46까지
# 뻗는다. 그 끝에 한 치 작은 헤드 돔(r 0.1175)이 반구로 맞물려 원통 + 반구 = 총알 기수가 된다.
# (처음엔 가는 칼라 앞에 볼을 불룩 얹었다 — 사진과 실루엣이 달랐다.)
# 다섯 번째 값은 초타원 지수 e(생략 시 2.7) — 원통·띠는 2.0(원). 같은 y의 두 링은 단(평면 고리)이다.
if EOIR:
    nose = [(1.46, 0.119, 0.119, -0.005, 2.0),
            (1.29, 0.119, 0.119, -0.005, 2.0),
            (1.29, 0.122, 0.122, -0.005, 2.0),
            (1.26, 0.122, 0.122, -0.005, 2.0),
            (1.26, 0.119, 0.119, -0.005, 2.0),
            (1.18, 0.135, 0.140, -0.004, 2.4)]
else:
    nose = [(1.75, 0.010, 0.010, 0.000),
            (1.55, 0.055, 0.065, -0.005),
            (1.25, 0.115, 0.125, -0.005)]
stations = nose + [                             # (y, 반폭, 반높이, z 중심[, e])
    (0.85, 0.185, 0.180, 0.000),
    (0.35, 0.245, 0.215, 0.000),
    (-0.15, 0.280, 0.230, 0.000),
    (-0.65, 0.285, 0.225, 0.000),
    (-1.10, 0.255, 0.205, 0.000),
    (-1.45, 0.195, 0.175, 0.000),               # 뒤 끝 = 엔진 방화벽(엔진은 별도 오브젝트)
]
loft(bm, [superellipse_ring(y, w, h, zc, e=e[0] if e else SUPERELLIPSE_E)
          for y, w, h, zc, *e in stations])

# 엔진 후드 — 동체 윗면이 방화벽 뒤로 짧게 이어져 엔진 앞 윗부분을 덮는다(참고 사진). 윗쪽 호
# (25°~155°)만 두께 6 mm로 둘러 옆·아래는 열린다 — 실린더와 흡기 스택이 드러난다.
def hood_ring(y, w, h, t=0.006, n=14, e=SUPERELLIPSE_E):
    arc = [math.radians(25 + 130 * i / (n - 1)) for i in range(n)]

    def pt(a, sw, sh):
        c, s = math.cos(a), math.sin(a)
        return (sw * math.copysign(abs(c) ** (2.0 / e), c), y,
                sh * math.copysign(abs(s) ** (2.0 / e), s))
    return [pt(a, w, h) for a in arc] + [pt(a, w - t, h - t) for a in reversed(arc)]


loft(bm, [hood_ring(-1.440, 0.200, 0.180), hood_ring(-1.470, 0.196, 0.177),
          hood_ring(-1.495, 0.190, 0.172)])

# 상부 안테나 돔
loft(bm, [circle_ring(16, 0.055, 'z', (0.0, -0.50, 0.205)),
          circle_ring(16, 0.048, 'z', (0.0, -0.50, 0.242)),
          circle_ring(16, 0.030, 'z', (0.0, -0.50, 0.266)),
          circle_ring(16, 0.001, 'z', (0.0, -0.50, 0.276))])

fuselage = finish_bm("Fuselage", bm, [MAT_AIRFRAME, MAT_DARK], col_model)
# 기수의 어두운 부분 [(y 하한, 상한)] — 기본형은 원추 끝 캡, EOIR형은 검은 띠(1.26~1.29)와 그 단,
# 그리고 원통 끝 원판(돔 둘레로 1.5 mm만 보이는 이음 테)
EOIR_BAND_Y = 1.255                             # EOIR형 검은 띠 뒤 끝
NOSE_DARK = [(EOIR_BAND_Y, 1.295), (1.455, 1.465)] if EOIR else [(1.28, math.inf)]
FIREWALL_Y = -1.45                              # 동체 뒤 끝 = 엔진 방화벽(날개 뒷전과 같은 y)
for p in fuselage.data.polygons:                # 기수 띠·방화벽은 어두운 재질
    c = p.center
    if (any(lo < c.y < hi for lo, hi in NOSE_DARK)
            or (c.y < FIREWALL_Y + 0.005 and p.normal.y < -0.9)):
        p.material_index = 1
shade_smooth(fuselage)                          # 40° 넘는 모서리(띠의 단·방화벽·후드 입술)는 날카롭게

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

# ---------------------------------------------------------------- 엔진 (분리 오브젝트, 고정)
# 참고 사진의 수평대향 4기통이 날개 뒷전(−1.45) 뒤로 드러난다: 크랭크케이스 좌우에 핀 달린
# 실린더가 둘씩(좌 뱅크가 2 cm 앞 — 박서의 크랭크 핀 간격), 위로 카뷰레터·흡기 스택 넷과 구리
# 매니폴드, 뒤로 구리 링기어, 노란 점화선과 배기관. 원점 = 동체 원점.
MAT_ENGINE = [
    make_mat("Engine_Block", (0.060, 0.062, 0.066), rough=0.45, metal=0.60),
    make_mat("Engine_Fins", (0.180, 0.185, 0.190), rough=0.40, metal=0.80),
    make_mat("Engine_Copper", (0.520, 0.220, 0.090), rough=0.30, metal=1.00),
    make_mat("Engine_Alloy", (0.620, 0.630, 0.640), rough=0.20, metal=1.00),
    make_mat("Engine_Wire", (0.600, 0.450, 0.050), rough=0.50),
    make_mat("Engine_Exhaust", (0.030, 0.028, 0.026), rough=0.70, metal=0.40),
]
BLOCK, FINS, COPPER, ALLOY, WIRE, EXHAUST = range(len(MAT_ENGINE))

bm = bmesh.new()
done = bm.faces.layers.int.new("done")

loft(bm, [superellipse_ring(y, w, h, 0.0, e=4.0) for y, w, h in   # 크랭크케이스
          ((-1.46, 0.055, 0.045), (-1.47, 0.070, 0.058), (-1.69, 0.070, 0.058),
           (-1.70, 0.055, 0.045))])
loft(bm, [circle_ring(16, 0.015, 'z', (0.0, -1.48, z)) for z in (0.050, 0.095)])  # 배전기
paint_new(bm, done, BLOCK)

CYLINDERS = [(-1.0, -1.525), (-1.0, -1.635), (1.0, -1.545), (1.0, -1.655)]   # (좌우 부호, y 중심)
for sx, yc in CYLINDERS:
    rings, x = [], 0.065
    for _ in range(6):                          # 배럴 — 원형 핀(피치 12 mm, 두께 4 mm)
        rings += [ring_x(sx * x, yc, 0.0, r, r) for r in (0.040, 0.052)]
        rings += [ring_x(sx * (x + 0.004), yc, 0.0, r, r) for r in (0.052, 0.040)]
        x += 0.012
    for _ in range(5):                          # 헤드 — 네모난 핀(피치 12 mm)
        rings += [ring_x(sx * x, yc, 0.004, ry, ry - 0.002, e=3.5) for ry in (0.042, 0.054)]
        rings += [ring_x(sx * (x + 0.004), yc, 0.004, ry, ry - 0.002, e=3.5) for ry in (0.054, 0.042)]
        x += 0.012
    loft(bm, rings)
paint_new(bm, done, FINS)
for sx, yc in CYLINDERS:                        # 헤드 커버
    loft(bm, [ring_x(sx * xx, yc, 0.004, 0.046, 0.044, e=3.5) for xx in (0.193, 0.205)])
    loft(bm, [circle_ring(16, 0.022, 'z', (sx * 0.105, yc, z)) for z in (0.045, 0.075)])  # 카뷰레터
paint_new(bm, done, BLOCK)

for sx, yc in CYLINDERS:                        # 흡기 스택 — 나팔 입술, 안쪽은 막음
    x0 = sx * 0.105
    loft(bm, [circle_ring(16, r, 'z', (x0, yc, z)) for r, z in
              ((0.015, 0.075), (0.015, 0.150), (0.020, 0.158), (0.020, 0.163),
               (0.012, 0.163), (0.012, 0.130))])
paint_new(bm, done, ALLOY)

loft(bm, [superellipse_ring(y, 0.028, 0.014, 0.068, e=4.0) for y in (-1.50, -1.68)])  # 매니폴드
for sx, yc in CYLINDERS:
    tube(bm, [(sx * 0.020, yc, 0.068), (sx * 0.060, yc, 0.068), (sx * 0.090, yc, 0.062)], 0.008)
for y0, y1 in ((-1.715, -1.735),):             # 링기어 — 톱니 60개
    teeth = 60
    loft(bm, [[(r * math.cos(math.pi * i / teeth), y, r * math.sin(math.pi * i / teeth))
               for i, r in enumerate([0.100, 0.093] * teeth)] for y in (y0, y1)])
paint_new(bm, done, COPPER)
loft(bm, [circle_ring(20, 0.050, 'y', (0.0, y, 0.0)) for y in (-1.705, -1.745)])  # 링기어 허브
paint_new(bm, done, BLOCK)

for sx, yc in CYLINDERS:                        # 점화선 — 배전기에서 스택 뒤로 돌아 헤드 위로
    tube(bm, [(sx * 0.010, -1.48, 0.090), (sx * 0.140, yc + 0.030, 0.100),
              (sx * 0.185, yc, 0.060)], 0.0028, n=6)
paint_new(bm, done, WIRE, smooth=True)
for sx, yc in CYLINDERS:                        # 배기관 — 헤드 아래에서 바깥 아래로 굽는다
    tube(bm, [(sx * 0.170, yc, -0.040), (sx * 0.180, yc, -0.080),
              (sx * 0.215, yc - 0.012, -0.105)], 0.010, n=10)
paint_new(bm, done, EXHAUST, smooth=True)
engine = finish_bm("Engine", bm, MAT_ENGINE, col_model)

# ---------------------------------------------------------------- 프로펠러 (분리 오브젝트, 후방 푸셔 — 나무 2엽)
# 원점 = 회전축(로컬 y). 최후방(센터 너트)은 로컬 y −0.105 = 기체 원점 뒤 1.905 m 그대로다 —
# 가상환경이 발사관 안에 기체를 맞추는 상수(web/world/src/core/launcher.ts의 VEHICLE_AFT_EXTENT)가
# 이 값에서 왔다. 블레이드 끝 반경도 종전과 같은 0.45 m다.
bm = bmesh.new()
done = bm.faces.layers.int.new("done")
BLADE = [                                       # (z, 반코드, 반두께, 피치각 deg, 코드 방향 치우침)
    (0.030, 0.030, 0.016, 32.0, 0.000),
    (0.080, 0.042, 0.012, 30.0, 0.000),
    (0.160, 0.052, 0.009, 25.0, 0.004),
    (0.260, 0.050, 0.007, 20.0, 0.006),
    (0.350, 0.042, 0.0055, 16.0, 0.006),
    (0.410, 0.032, 0.0045, 14.0, 0.004),
    (0.440, 0.020, 0.0035, 13.0, 0.002),
    (0.450, 0.006, 0.0020, 13.0, 0.000),        # 둥근 끝
]
for mirror in (1.0, -1.0):                      # 2엽 — R_y(180°) 대칭
    rings = []
    for z, cx, cy, ang, off in BLADE:
        a = math.radians(ang)
        ring = []
        for i in range(12):                     # 타원 단면 — 나무 블레이드의 둥근 앞·뒷전
            t = 2.0 * math.pi * i / 12
            px, py = off + cx * math.cos(t), cy * math.sin(t)
            ring.append((mirror * (px * math.cos(a) - py * math.sin(a)),
                         px * math.sin(a) + py * math.cos(a), mirror * z))
        rings.append(ring)
    loft(bm, rings)
paint_new(bm, done, 0, smooth=True)
# 나무 허브 — 두 허브판 사이를 채운다. 없으면 블레이드 뿌리(|z| < 0.03) 안쪽이 옆에서 비쳐 보였다.
loft(bm, [circle_ring(24, 0.034, 'y', (0.0, y, 0.0)) for y in (0.020, -0.020)])
paint_new(bm, done, 0)
HUB = [                                         # ((로컬 y 앞, 뒤), 반경) — 엔진 쪽(+)에서 뒤(−)로
    ((0.085, 0.020), 0.018),                    # 축(링기어 허브에 물린다)
    ((0.036, 0.020), 0.048),                    # 앞 허브판
    ((-0.020, -0.042), 0.055),                  # 뒤 허브판 — 볼트 6개
    ((-0.042, -0.070), 0.022),                  # 센터 보스
    ((-0.070, -0.095), 0.015),
    ((-0.095, -0.105), 0.010),                  # 너트 — 최후방
]
for (y0, y1), r in HUB:
    loft(bm, [circle_ring(24, r, 'y', (0.0, y0, 0.0)), circle_ring(24, r, 'y', (0.0, y1, 0.0))])
for i in range(6):
    a = 2.0 * math.pi * i / 6
    loft(bm, [circle_ring(8, 0.0065, 'y', (0.036 * math.cos(a), y, 0.036 * math.sin(a)))
              for y in (-0.040, -0.050)])
paint_new(bm, done, 1)
prop = finish_bm("Propeller", bm, [make_mat("Prop_Wood", (0.200, 0.090, 0.035), rough=0.45),
                                   MAT_ENGINE[ALLOY]], col_model)
prop.location = (0.0, -1.80, 0.0)               # 원점 = 회전축(로컬 y)

# ---------------------------------------------------------------- EOIR 헤드 (EOIR형만 — 분리 오브젝트 2축)
# 포드형 EO/IR 기수: 검은 띠 앞에 헤드 돔이 앉고, 돔 앞면을 평평한 센서면으로 잘라 창 넷을 붙인다
# (참고 사진의 배치 — 큰 EO 렌즈, 작은 IR 창, 둥근 오각형 레이저 창, 작은 보조 렌즈, 붉은 가스켓).
# 돔 옆에는 비스듬한 패널 이음매와 리벳이 돈다.
# 외측 EOIR_Pan(방위, 로컬 Z — 형상 없는 엠프티) › 내측 EOIR_Tilt(고각, 로컬 X — 돔 전체).
# 두 원점 = 돔 중심 = 두 축의 교점 — 돔은 어느 자세에서도 외형이 같고 센서면만 돈다.
# 보어사이트 = 로컬 +Y(기수 방향). 부호는 FRD 오일러와 같은 뜻: pan + = 우측, tilt + = 위.
eoir = {}
if EOIR:
    # 돔 반경은 원통 기수(r 0.119, 28각형 내접 0.1183)보다 **작다** — 돔이 원통 안에 온전히 들어가야
    # 어느 자세에서도 두 다각형 면이 서로를 뚫지 않는다. 같은 반경(0.120)으로 두었더니 돌린 자세에서
    # 이음선이 톱니처럼 울었다(확대 렌더). 남는 1.5 mm 단은 어두운 이음 테로 칠한다.
    EOIR_R = 0.1175
    EOIR_C = (0.0, 1.460, -0.005)               # 돔 중심 = 원통 기수 끝 원판 중심(축 위)
    FACE_Y = 0.096                              # 센서면 절단(로컬 y) → 면 반경 √(R²−y²) ≈ 0.068
    # 면을 크게 자를수록 사진에 가깝지만 가장자리가 일찍 원통에 먹힌다 — 가장자리는 보어사이트에서 35°
    GLASS, OPTIC, GASKET_TOP = 0.0015, 0.0020, 0.0025   # 센서면 위 높이 — 유리·광학부·가스켓
    GASKET_W = 0.0012                           # 가스켓 폭 — 사진처럼 가는 테

    SLOTS = [
        make_mat("EOIR_Housing", (0.560, 0.568, 0.552), rough=0.45, metal=0.15),  # 기체와 같은 밝은 회색
        make_mat("EOIR_Gasket", (0.520, 0.100, 0.070), rough=0.50),
        make_mat("EOIR_Lens_EO", (0.015, 0.045, 0.150), rough=0.05, metal=0.30),
        make_mat("EOIR_Lens_IR", (0.045, 0.018, 0.055), rough=0.10, metal=0.40),
        make_mat("EOIR_Laser", (0.075, 0.100, 0.045), rough=0.30),
        make_mat("EOIR_Optics", (0.008, 0.012, 0.018), rough=0.05, metal=0.60),
        make_mat("EOIR_Seam", (0.035, 0.037, 0.040), rough=0.60),
    ]
    HOUSING, GASKET, LENS_EO, LENS_IR, LASER, OPTICS, SEAM = range(len(SLOTS))

    # 창 — (코어 꼭짓점[로컬 x, z], 원·모서리 반경, 유리 재질, 광학부 반경 비). 코어가 한 점이면 원.
    # 센서면을 **마주 보고** 사진과 같은 배치다 — 마주 보면 좌우가 뒤집히므로 로컬 x(+ = 우현)는
    # 사진의 반대 부호다(처음에 사진 좌표 그대로 넣었다가 거울상으로 그려졌다). 가스켓 바깥까지
    # 서로 5 mm 넘게 떨어지고 센서면(반경 0.067) 안 5 mm 여유로 든다.
    WINDOWS = [
        ([(0.027, 0.010)], 0.0245, LENS_EO, 0.45),                 # EO 주광 — 큰 원(보기에 왼쪽)
        ([(-0.030, 0.036)], 0.0115, LENS_IR, None),                # IR — 작은 검보라 원(오른쪽 위)
        ([(0.023, -0.036)], 0.0115, LENS_EO, 0.55),                # 보조 렌즈 — 작은 원(왼쪽 아래)
        ([(-0.010, 0.013), (-0.045, 0.013), (-0.052, -0.009),
          (-0.036, -0.045), (-0.002, -0.042)], 0.0032, LASER, None),  # 레이저 — 둥근 오각형
    ]

    def rounded_outline(core, radius, n_arc=6):
        """볼록 다각형 core와 반경 radius 원의 민코프스키 합 윤곽 (로컬 x, z).
        같은 core면 radius가 달라도 점 수·순서가 같다 — 그대로 loft로 잇는다."""
        if len(core) == 1:
            (cx, cz), n = core[0], 32
            return [(cx + radius * math.cos(2 * math.pi * i / n),
                     cz + radius * math.sin(2 * math.pi * i / n)) for i in range(n)]
        area = sum(core[i - 1][0] * core[i][1] - core[i][0] * core[i - 1][1]
                   for i in range(len(core)))
        if area < 0:                            # 반시계로 맞춘다 — 바깥 법선이 (dz, −dx)가 된다
            core = core[::-1]
        pts = []
        for i in range(len(core)):
            (ax, az), (px, pz), (bx, bz) = core[i - 1], core[i], core[(i + 1) % len(core)]
            a0 = math.atan2(-(px - ax), pz - az)            # 들어오는 변의 바깥 법선 각
            da = (math.atan2(-(bx - px), bz - pz) - a0) % (2 * math.pi)
            for j in range(n_arc + 1):
                a = a0 + da * j / n_arc
                pts.append((px + radius * math.cos(a), pz + radius * math.sin(a)))
        return pts

    def dome_dir(axis, beta, t):
        """돔 위 단위 방향 — axis 둘레 각반경 beta 원의 매개변수 t 지점."""
        a = Vector(axis).normalized()
        e1 = a.orthogonal().normalized()
        return (a * math.cos(beta)
                + (e1 * math.cos(t) + a.cross(e1) * math.sin(t)) * math.sin(beta)).normalized()

    bm = bmesh.new()
    part = bm.faces.layers.int.new("part")      # 1 = 칠함 (paint_new)

    def paint(mat, smooth=False, glass_y=None, glass_mat=None):
        """paint_new로 새 면만 칠한다. glass_y가 주어지면 그 높이 평면의 면만 glass_mat이다."""
        def pick(f):
            if glass_y is not None and all(abs(v.co.y - glass_y) < 1e-7 for v in f.verts):
                return glass_mat
            return None
        paint_new(bm, part, mat, smooth, pick)

    # 돔 — 앞면을 잘라 센서면을 붙인다
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=EOIR_R)
    paint(HOUSING, smooth=True)
    cut = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                                 dist=1e-6, plane_co=(0.0, FACE_Y, 0.0),
                                 plane_no=(0.0, 1.0, 0.0), clear_outer=True)
    rim = [g for g in cut["geom_cut"] if isinstance(g, bmesh.types.BMEdge)]
    bmesh.ops.contextual_create(bm, geom=rim)
    paint(HOUSING)                              # 센서면(평면)

    # 창 — 가스켓이 센서면에서 2.5 mm 솟고, 유리는 그 안 1.5 mm 높이, 광학부는 유리 위 원판
    for core, radius, glass, optic in WINDOWS:
        outer = rounded_outline(core, radius + GASKET_W)
        inner = rounded_outline(core, radius)
        loft(bm, [[(x, FACE_Y - 0.001, z) for x, z in outer],
                  [(x, FACE_Y + GASKET_TOP, z) for x, z in outer],
                  [(x, FACE_Y + GASKET_TOP, z) for x, z in inner],
                  [(x, FACE_Y + GLASS, z) for x, z in inner]])
        paint(GASKET, glass_y=FACE_Y + GLASS, glass_mat=glass)
        if optic:
            disk = rounded_outline(core, radius * optic)
            loft(bm, [[(x, FACE_Y + GLASS - 0.0003, z) for x, z in disk],
                      [(x, FACE_Y + OPTIC, z) for x, z in disk]])
            paint(OPTICS)

    def rivet(u):
        e1 = u.orthogonal().normalized()
        e2 = u.cross(e1)

        def ring(r, h):
            return [tuple(u * h + (e1 * math.cos(math.pi * i / 4) + e2 * math.sin(math.pi * i / 4)) * r)
                    for i in range(8)]
        # 머리 끝 R+0.6 mm = 0.1181 — 원통 기수 내접(0.11825) 안이라 돌려도 옆면을 뚫고 나오지 않는다
        loft(bm, [ring(0.0018, EOIR_R - 0.0015), ring(0.0018, EOIR_R + 0.0003),
                  ring(0.0010, EOIR_R + 0.0006)])

    # 센서면 둘레 리벳 — 보어사이트에서 40°(센서면 가장자리 35° 바깥)
    RING = math.radians(40)
    for i in range(24):
        ph = 2 * math.pi * i / 24
        rivet(Vector((math.sin(RING) * math.cos(ph), math.cos(RING), math.sin(RING) * math.sin(ph))))
    # 비스듬한 패널 이음매 — 좌상 후방 축 둘레 62° 원(보어사이트에 가장 가까워도 48°). 앞쪽에만 리벳
    SEAM_AXIS, SEAM_BETA, W = (-0.80, -0.34, 0.49), math.radians(62), math.radians(0.35)
    loft(bm, [[tuple(dome_dir(SEAM_AXIS, SEAM_BETA + s, 2 * math.pi * i / 96) * (EOIR_R + 0.0006))
               for i in range(96)] for s in (-W, W)], cap_start=False, cap_end=False)
    for i in range(36):
        u = dome_dir(SEAM_AXIS, SEAM_BETA - math.radians(2.5), 2 * math.pi * i / 36)
        if u.y > 0.0:
            rivet(u)
    paint(SEAM)

    tilt = finish_bm("EOIR_Tilt", bm, SLOTS, col_model)
    tilt.location = EOIR_C

    # 방위축 — 형상 없는 엠프티. 사진처럼 돔만 보이고, 고각 헤드가 이 축을 탄다.
    pan = bpy.data.objects.new("EOIR_Pan", None)
    pan.empty_display_type, pan.empty_display_size = 'ARROWS', 0.08
    col_model.objects.link(pan)
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
parent_to(engine, fuselage)
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
        ("eoir_pan", 0.0, -35, 35, "EOIR 방위(pan) [deg], + = 우측"),
        ("eoir_tilt", 0.0, -45, 30, "EOIR 고각(tilt) [deg], + = 위"),
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
    # 범위 = 센서면 가장자리·창이 원통 기수에 먹히지 않는 **직사각형**. 가장자리가 보어사이트에서
    # 35°라 비는 방위가 고각에 따라 준다 — 축별 리밋은 그 결합 영역을 못 그리므로 안쪽 직사각형으로
    # 자른다. ±35 × −45…+30은 1° 격자 전체에서 간섭 0(원통 28각형 대비 해석 계산 — 테스트가 이
    # 두 줄의 값을 읽어 고정한다). 처음 둔 ±40은 모서리에서 센서면이 1.6 mm 먹혔다(리뷰에서 발견).
    limit_rot(eoir["pan"], 'z', -35, 35)
    limit_rot(eoir["tilt"], 'x', -45, 30)

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
    DEMO["eoir_pan"] = [(1, 0), (30, -35), (72, 35), (100, 25), (138, -15), (162, 0)]
    DEMO["eoir_tilt"] = [(1, 0), (30, -10), (72, -10), (100, -30), (138, -40), (162, 0)]
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
# 기본형은 후방 쿼터뷰(타면 변위가 보인다), EOIR형은 전방 쿼터뷰(헤드 센서면이 보인다)
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
    # 기본형: 엘레본 차동 + 러더 변위가 보이는 프레임 / EOIR형: 헤드가 우측 35°로 돌아 센서면이 카메라를 보는 프레임
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
