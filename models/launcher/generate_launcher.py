# 무인기 캐니스터 발사관(트레일러 탑재형) — 가동부가 분리되어 움직이는 .blend 생성 스크립트
#
# 실행:  blender -b --factory-startup -P generate_launcher.py
# 산출:  launcher.blend  (+ preview.png, launcher.glb)
#
# 같은 저장소의 SHAHED-136 모델과 같은 톤(스튜디오·재질 스타일·파이프라인). 방금 만든
# 무인기를 이 발사관에서 쏘는 세트로 어울리도록 설계했다.
#
# 좌표계(블렌더, Z-up): +Y = 발사(포구) 방향, +X 우측, +Z 상방. 지면 z = 0.
# 가동부 부호: 방위각 azimuth + = 좌현(포구가 -X쪽으로) 선회, 고각 elevation + = 포구 상승,
#             지지대 jack_deploy 0→1 = 접힘→지면으로 전개.
#
# 치수는 이미지 기반 근사의 시각화용 형상이며 실장비 설계 데이터가 아니다.

import bpy
import bmesh
import math
import os
import sys
from mathutils import Vector

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 내장 numpy가 못 뜨는 블렌더 빌드가 있다 — glTF 내보내기가 그때 조용히 빠진다.
# 사유·증상·복구는 models/blender_numpy.py 참조. **bpy.ops 호출 전에** 부른다.
sys.path.insert(0, os.path.dirname(OUT_DIR))  # models/
from blender_numpy import ensure_numpy  # noqa: E402

ensure_numpy(repo_root=os.path.dirname(os.path.dirname(OUT_DIR)))
TAU = 2.0 * math.pi

# ---------------------------------------------------------------- 기본 장면
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "Launcher"
scene.unit_settings.system = 'METRIC'
scene.unit_settings.length_unit = 'METERS'
scene.render.fps = 24
scene.frame_start, scene.frame_end = 1, 168

col_model = bpy.data.collections.new("Launcher")
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


def add_box(bm, p0, p1):
    """축 정렬 직육면체(min corner p0, max corner p1)."""
    (x0, y0, z0), (x1, y1, z1) = p0, p1
    v = [[[bm.verts.new((x, y, z)) for z in (z0, z1)] for y in (y0, y1)] for x in (x0, x1)]
    V = lambda i, j, k: v[i][j][k]
    bm.faces.new((V(0, 0, 0), V(0, 1, 0), V(0, 1, 1), V(0, 0, 1)))
    bm.faces.new((V(1, 0, 0), V(1, 0, 1), V(1, 1, 1), V(1, 1, 0)))
    bm.faces.new((V(0, 0, 0), V(0, 0, 1), V(1, 0, 1), V(1, 0, 0)))
    bm.faces.new((V(0, 1, 0), V(1, 1, 0), V(1, 1, 1), V(0, 1, 1)))
    bm.faces.new((V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)))
    bm.faces.new((V(0, 0, 1), V(0, 1, 1), V(1, 1, 1), V(1, 0, 1)))


def beam(bm, a, b, w, h, up=(0, 0, 1)):
    """a→b 를 잇는, 단면 w(측)×h(상하)의 방향성 각재."""
    a, b = Vector(a), Vector(b)
    d = b - a
    if d.length < 1e-9:
        return
    d.normalize()
    side = d.cross(Vector(up))
    if side.length < 1e-6:
        side = d.cross(Vector((1, 0, 0)))
    side.normalize()
    u2 = side.cross(d).normalized()

    def ring(c):
        return [c + side * (w / 2) + u2 * (h / 2), c + side * (w / 2) - u2 * (h / 2),
                c - side * (w / 2) - u2 * (h / 2), c - side * (w / 2) + u2 * (h / 2)]

    loft(bm, [ring(a), ring(b)])


def circle_ring(n, r, axis, at):
    pts = []
    for i in range(n):
        a = TAU * i / n
        u, v = r * math.cos(a), r * math.sin(a)
        if axis == 'x':
            pts.append((at[0], at[1] + u, at[2] + v))
        elif axis == 'y':
            pts.append((at[0] + u, at[1], at[2] + v))
        else:
            pts.append((at[0] + u, at[1] + v, at[2]))
    return pts


def cylinder(bm, c0, c1, r0, r1, axis, n=24):
    loft(bm, [circle_ring(n, r0, axis, c0), circle_ring(n, r1, axis, c1)])


def torus(bm, center, R, r, seg=20, side=10):
    """수평 링(견인 러넷용) — 중심 center, 주반경 R, 관반경 r."""
    C = Vector(center)
    grid = []
    for i in range(seg):
        a = TAU * i / seg
        radial = Vector((math.cos(a), math.sin(a), 0.0))
        mc = C + radial * R
        grid.append([bm.verts.new(mc + radial * (r * math.cos(TAU * j / side))
                                  + Vector((0, 0, r * math.sin(TAU * j / side))))
                     for j in range(side)])
    for i in range(seg):
        i2 = (i + 1) % seg
        for j in range(side):
            j2 = (j + 1) % side
            bm.faces.new((grid[i][j], grid[i2][j], grid[i2][j2], grid[i][j2]))


def make_mat(name, color, rough=0.6, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    m.diffuse_color = (*color, 1.0)
    return m


def shade_smooth(ob, angle_deg=35.0):
    me = ob.data
    for p in me.polygons:
        p.use_smooth = True
    try:
        me.use_auto_smooth = True
        me.auto_smooth_angle = math.radians(angle_deg)
    except AttributeError:
        pass


def finish(name, bm, mat, collection, pivot=(0, 0, 0), smooth=False):
    """bmesh를 오브젝트로. pivot을 원점으로 삼아(로컬화) 회전·이동 축을 맞춘다."""
    if any(pivot):
        bmesh.ops.translate(bm, verts=bm.verts, vec=(-pivot[0], -pivot[1], -pivot[2]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob.location = pivot
    collection.objects.link(ob)
    if smooth:
        shade_smooth(ob)
    return ob


def apply_modifiers(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    old = ob.data
    ob.data = me
    ob.modifiers.clear()
    bpy.data.meshes.remove(old)


def boolean_diff(ob, cutter):
    mod = ob.modifiers.new("cut", 'BOOLEAN')
    mod.object, mod.operation, mod.solver = cutter, 'DIFFERENCE', 'EXACT'
    apply_modifiers(ob)
    bpy.data.objects.remove(cutter)


# ---------------------------------------------------------------- 재질 (SHAHED와 같은 군용 매트 톤)
MAT_OLIVE = make_mat("LauncherOlive", (0.200, 0.220, 0.118), rough=0.62)   # 올리브 드랩(발사관·크래들)
MAT_FRAME = make_mat("LauncherFrame", (0.125, 0.140, 0.076), rough=0.60)   # 짙은 올리브(트레일러)
MAT_DARK = make_mat("DarkDetail", (0.055, 0.058, 0.062), rough=0.45)       # 타이어·히치
MAT_METAL = make_mat("Metal", (0.340, 0.350, 0.330), rough=0.40, metal=0.7)  # 잭·레일
MAT_TUBE = make_mat("CanisterInner", (0.022, 0.024, 0.028), rough=0.72)    # 발사관 내부(암부)

# 수직 배치 기준값
BED = 0.92          # 트레일러 상판 높이
TRUN = 1.78         # 트러니언(고각축) 높이
TT_PIV = (0.0, -0.10, BED)      # 턴테이블(방위각축) 피벗
CR_PIV = (0.0, -0.10, TRUN)     # 크래들(고각축) 피벗
# 잭 = 4모서리 아웃리거. 받침 footprint(x=±1.28)를 바퀴 트랙(±1.12)보다 넓게 잡아 전복 방지.
JACKS = {"FL": (1.28, 1.70), "FR": (-1.28, 1.70),
         "RL": (1.28, -2.35), "RR": (-1.28, -2.35)}   # (x, y) 모서리
JACK_TOP = 1.00       # 슬리브 상단(레그가 항상 이 안에 물려 있음)
JACK_TRAVEL = 0.46    # 전개 시 하강량 (레그 상단은 슬리브 안에 남음 → 항상 연결)

# ---------------------------------------------------------------- 트레일러 (정적)
bm = bmesh.new()
for sx in (0.92, -0.92):                                   # 세로 대들보
    beam(bm, (sx, -2.55, BED - 0.15), (sx, 1.85, BED - 0.15), 0.16, 0.30)
for y in (-2.40, -1.20, 0.0, 1.20, 1.75):                  # 가로 부재
    beam(bm, (-0.92, y, BED - 0.15), (0.92, y, BED - 0.15), 0.14, 0.20)
add_box(bm, (-1.02, -2.45, BED - 0.02), (1.02, 1.82, BED + 0.04))   # 상판
for sx in (1.12, -1.12):                                   # 펜더(흙받이)
    add_box(bm, (sx - 0.18, -0.72, BED + 0.04), (sx + 0.18, 0.34, BED + 0.16))
for (jx, jy) in JACKS.values():                            # 아웃리거 암 + 잭 슬리브(레그가 물리는 통)
    sx = 0.90 if jx > 0 else -0.90
    beam(bm, (sx, jy, BED - 0.06), (jx, jy, BED - 0.06), 0.12, 0.16)          # 프레임→모서리 수평 암
    beam(bm, (jx, jy, 0.55), (sx, jy, BED - 0.06), 0.06, 0.09)                # 대각 보강재
    add_box(bm, (jx - 0.09, jy - 0.09, 0.40), (jx + 0.09, jy + 0.09, JACK_TOP))  # 슬리브(통)
# 드로바(A-프레임) + 커플러 + 러넷
for sx in (0.52, -0.52):
    beam(bm, (sx, -2.45, BED - 0.18), (0.0, -3.80, 0.60), 0.12, 0.16)
add_box(bm, (-0.12, -3.92, 0.52), (0.12, -3.72, 0.70))
torus(bm, (0.0, -3.99, 0.61), 0.11, 0.035)
trailer = finish("Trailer", bm, MAT_FRAME, col_model)

# ---------------------------------------------------------------- 바퀴 (분리, 정적)
wheels = {}
for sx, tag in ((1.12, "L"), (-1.12, "R")):
    center = (sx, -0.20, 0.46)
    bm = bmesh.new()
    cylinder(bm, (sx - 0.15, -0.20, 0.46), (sx + 0.15, -0.20, 0.46), 0.46, 0.46, 'x', n=28)  # 타이어
    cylinder(bm, (sx - 0.16, -0.20, 0.46), (sx + 0.16, -0.20, 0.46), 0.17, 0.17, 'x', n=16)  # 허브
    wheels[tag] = finish("Wheel_" + tag, bm, MAT_DARK, col_model, pivot=center, smooth=True)

# ---------------------------------------------------------------- 지지대 잭 (분리, 전개)
# 텔레스코핑 레그: 상단은 늘 슬리브(z 0.40~1.00) 안에 물려 있고, 하단 풋패드가 지면(z=0)에
# 닿는다. 전개해도 트레일러↔지면이 슬리브-레그-패드로 끊김 없이 이어진다.
jacks = {}
for tag, (jx, jy) in JACKS.items():
    piv = (jx, jy, JACK_TOP)
    bm = bmesh.new()
    add_box(bm, (jx - 0.06, jy - 0.06, 0.50), (jx + 0.06, jy + 0.06, JACK_TOP))   # 내부 레그(슬리브에 물림)
    add_box(bm, (jx - 0.19, jy - 0.19, 0.44), (jx + 0.19, jy + 0.19, 0.50))       # 풋패드
    jacks[tag] = finish("Jack_" + tag, bm, MAT_METAL, col_model, pivot=piv)

# ---------------------------------------------------------------- 턴테이블 (방위각) + 고각 지지 기둥
bm = bmesh.new()
cylinder(bm, (0.0, -0.10, BED), (0.0, -0.10, BED + 0.24), 0.76, 0.66, 'z', n=32)      # 페데스탈
cylinder(bm, (0.0, -0.10, BED + 0.24), (0.0, -0.10, BED + 0.30), 0.70, 0.70, 'z', n=32)  # 상판 디스크
for sx in (0.66, -0.66):                                                              # 트러니언 기둥
    beam(bm, (sx, -0.10, BED + 0.30), (sx, -0.10, TRUN), 0.18, 0.18)
    cylinder(bm, (sx - 0.06, -0.10, TRUN), (sx + 0.10, -0.10, TRUN), 0.13, 0.13, 'x', n=16)  # 베어링 보스
turntable = finish("Turntable", bm, MAT_FRAME, col_model, pivot=TT_PIV, smooth=True)

# ---------------------------------------------------------------- 크래들 + 발사관 본체 (고각)
BX, BZ = 0.72, 0.62          # 박스 반폭·반높이
BY0, BY1 = -1.05, 0.85       # 박스 뒤·앞(포구)
# 단일 대형 캐니스터 개구 — 처음엔 2×2 관 4개였는데, 기체(스팬 2.5 m)가 그 관을 지날 수
# 없어 발사 순간 앞면을 뚫고 나오는 그림이 됐다. 개구 하나를 면 가득 뚫으면 루트 2.6배
# 확대 후 개구가 3.1×2.2 m라 기체가 통째로 드나든다(전체 확대는 아래 root.scale 주석).
TUBE_HX, TUBE_HZ = 0.66, 0.44   # 개구 반폭·반높이 (확대 전 로컬 — ×2.0이 스팬 2.5 m를 넘게)

bm = bmesh.new()
add_box(bm, (-BX, BY0, TRUN - BZ), (BX, BY1, TRUN + BZ))                     # 외피
for sx in (1, -1):
    x_in = sx * BX
    add_box(bm, (x_in, -0.95, TRUN - 0.50), (x_in + sx * 0.08, 0.55, TRUN + 0.55))  # 측면 장갑판
    cylinder(bm, (sx * BX, -0.10, TRUN), (sx * 0.95, -0.10, TRUN), 0.12, 0.12, 'x', n=16)  # 트러니언 스텁
cradle = finish("Cradle", bm, MAT_OLIVE, col_model, pivot=CR_PIV, smooth=True)

# 포구(+Y)에 단일 관통구 (불리언)
bm = bmesh.new()
add_box(bm, (-TUBE_HX, -0.90, TRUN - TUBE_HZ), (TUBE_HX, 1.20, TRUN + TUBE_HZ))
cutter = finish("cut_tube", bm, MAT_OLIVE, col_model)
boolean_diff(cradle, cutter)

# 캐니스터 내부 라이너(암부, 분리 오브젝트)
bm = bmesh.new()
add_box(bm, (-TUBE_HX + 0.025, -0.88, TRUN - TUBE_HZ + 0.025),
        (TUBE_HX - 0.025, 0.84, TRUN + TUBE_HZ - 0.025))
box_tubes = finish("Box_Tubes", bm, MAT_TUBE, col_model, pivot=CR_PIV)

# 상부 발사 레일 2줄 (금속, 포구 앞으로 돌출)
bm = bmesh.new()
for sx in (0.34, -0.34):
    beam(bm, (sx, -0.70, TRUN + BZ + 0.05), (sx, 1.45, TRUN + BZ + 0.05), 0.06, 0.10)
for y in (-0.4, 0.6):
    beam(bm, (-0.34, y, TRUN + BZ + 0.05), (0.34, y, TRUN + BZ + 0.05), 0.05, 0.06)
box_rails = finish("Box_Rails", bm, MAT_METAL, col_model, pivot=CR_PIV, smooth=True)

# ---------------------------------------------------------------- 루트 엠프티 + 계층
root = bpy.data.objects.new("LAUNCHER_Root", None)
root.empty_display_type = 'PLAIN_AXES'
root.empty_display_size = 1.0
# **전체 2.0배** — 기체(전장 3.5 m·스팬 2.5 m)가 캐니스터 박스 안에 들어가는 비례
# (사용자 지정 2~3배; 길이 3.52/1.9 = 1.85, 스팬 2.5/1.44 = 1.74가 하한이다).
# 상한을 안 쓰는 이유: 균일 확대는 캐니스터 **바닥도 올려서**(1.16×S), 시뮬 발사
# 원점(1.2 m)과의 높이 어긋남이 배율에 비례해 커진다 — 필요한 만큼만 키운다.
# 지오메트리 리터럴 수십 개를 고치는 대신 루트 스케일로 얹고 glTF가 노드 스케일로
# 내보낸다(export_apply=False). 런타임 관절 값은 전부 로컬(스케일 앞)이라 그대로 맞는다.
root.scale = (2.0, 2.0, 2.0)
col_model.objects.link(root)
bpy.context.view_layer.update()


def parent_to(child, parent):
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()


parent_to(trailer, root)
for tag in ("L", "R"):
    parent_to(wheels[tag], trailer)
for tag in JACKS:
    parent_to(jacks[tag], trailer)
parent_to(turntable, trailer)
parent_to(cradle, turntable)
parent_to(box_tubes, cradle)
parent_to(box_rails, cradle)

# ---------------------------------------------------------------- 조종 프로퍼티 + 드라이버
PROPS = [
    ("azimuth", 0.0, -100, 100, "방위각 [deg], + = 좌현 선회"),
    ("elevation", 0.0, 0, 48, "고각 [deg], + = 포구 상승"),
    ("jack_deploy", 0.0, 0, 1, "지지대 전개 0(접힘)→1(지면)"),
]
for name, default, lo, hi, desc in PROPS:
    root[name] = float(default)
    ui = root.id_properties_ui(name)
    ui.update(min=lo, max=hi, soft_min=lo, soft_max=hi, description=desc)


def add_rot_driver(ob, index, expr, prop_name):
    fc = ob.driver_add('rotation_euler', index)
    d = fc.driver
    d.type = 'SCRIPTED'
    v = d.variables.new()
    v.name = 'x'
    t = v.targets[0]
    t.id = root
    t.data_path = '["%s"]' % prop_name
    d.expression = expr


def add_loc_driver(ob, index, expr, prop_name):
    fc = ob.driver_add('location', index)
    d = fc.driver
    d.type = 'SCRIPTED'
    v = d.variables.new()
    v.name = 'x'
    t = v.targets[0]
    t.id = root
    t.data_path = '["%s"]' % prop_name
    d.expression = expr


# 방위각: 턴테이블 로컬 Z / 고각: 크래들 로컬 X
add_rot_driver(turntable, 2, 'radians(x)', "azimuth")
add_rot_driver(cradle, 0, 'radians(x)', "elevation")
# 지지대: 잭 로컬 Z 하강 (슬리브 상단에서 travel 만큼 — 상단은 슬리브 안에 남는다)
for tag in JACKS:
    add_loc_driver(jacks[tag], 2, '%.4f - %.4f * x' % (JACK_TOP, JACK_TRAVEL), "jack_deploy")

# 리밋
c = turntable.constraints.new('LIMIT_ROTATION')
c.use_limit_z = True
c.min_z, c.max_z = math.radians(-110), math.radians(110)
c.owner_space = 'LOCAL'
c = cradle.constraints.new('LIMIT_ROTATION')
c.use_limit_x = True
c.min_x, c.max_x = math.radians(-2), math.radians(52)
c.owner_space = 'LOCAL'

# ---------------------------------------------------------------- 데모 애니메이션 (전개→선회→고각)
DEMO = {
    "jack_deploy": [(1, 0), (30, 1), (168, 1)],
    "azimuth":     [(1, 0), (38, 0), (70, -32), (104, 24), (126, 0), (168, 0)],
    "elevation":   [(1, 0), (44, 0), (96, 42), (140, 42), (168, 30)],
}
for prop_name, keys in DEMO.items():
    for frame, value in keys:
        root[prop_name] = float(value)
        root.keyframe_insert(data_path='["%s"]' % prop_name, frame=frame)

# ---------------------------------------------------------------- 스튜디오 (SHAHED와 동일 톤)
world = bpy.data.worlds.new("Studio")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.82, 0.83, 0.85, 1.0)
scene.world = world

target = bpy.data.objects.new("CamTarget", None)
target.location = (0.0, 0.05, 1.55)
col_studio.objects.link(target)

cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 40
cam = bpy.data.objects.new("Camera", cam_data)
cam.location = (5.8, 5.6, 4.1)                   # 포구(+Y) 쪽 상방 3/4 — 캐니스터 관통구가 보인다
col_studio.objects.link(cam)
tc = cam.constraints.new('TRACK_TO')
tc.target, tc.track_axis, tc.up_axis = target, 'TRACK_NEGATIVE_Z', 'UP_Y'
scene.camera = cam

sun_data = bpy.data.lights.new("Sun", 'SUN')
sun_data.energy = 3.0
sun = bpy.data.objects.new("Sun", sun_data)
sun.rotation_euler = (math.radians(52), 0.0, math.radians(40))
col_studio.objects.link(sun)

fill_data = bpy.data.lights.new("Fill", 'AREA')
fill_data.energy = 700.0
fill_data.size = 6.0
fill = bpy.data.objects.new("Fill", fill_data)
fill.location = (-5.0, -4.5, 3.0)
col_studio.objects.link(fill)
fc = fill.constraints.new('TRACK_TO')
fc.target, fc.track_axis, fc.up_axis = target, 'TRACK_NEGATIVE_Z', 'UP_Y'

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

# ---------------------------------------------------------------- 저장 → 렌더 → three.js GLB
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, "launcher.blend"))
print("[gen] saved launcher.blend")

if os.environ.get("LAUNCHER_SKIP_RENDER") != "1":
    scene.frame_set(140)                        # 지지대 전개 + 고각 42° 히어로 프레임
    scene.render.filepath = os.path.join(OUT_DIR, "preview.png")
    try:
        bpy.ops.render.render(write_still=True)
        print("[gen] rendered preview.png")
    except Exception as exc:
        print("[gen] render failed:", exc)


# three.js(GLTFLoader)는 드라이버·커스텀 프로퍼티를 실행하지 않으므로, 가동부 모션을
# 프레임별로 샘플해 노드 트랜스폼 키프레임으로 굽고 단일 클립으로 내보낸다(SHAHED와 동일).
def export_threejs_glb(path):
    movable = [turntable, cradle] + [jacks[t] for t in JACKS]
    frames = range(scene.frame_start, scene.frame_end + 1)
    samples = {ob: [] for ob in movable}
    for f in frames:
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        for ob in movable:
            ev = ob.evaluated_get(dg)
            samples[ob].append((f, tuple(ev.rotation_euler), tuple(ev.location)))

    for ob in movable:
        if ob.animation_data:
            for d in list(ob.animation_data.drivers):
                ob.animation_data.drivers.remove(d)
        for con in list(ob.constraints):
            ob.constraints.remove(con)
    if root.animation_data:
        root.animation_data_clear()

    for ob, seq in samples.items():
        for f, rot, loc in seq:
            ob.rotation_euler = rot
            ob.location = loc
            ob.keyframe_insert("rotation_euler", frame=f)
            ob.keyframe_insert("location", frame=f)

    for ob in bpy.data.objects:
        ob.select_set(ob.name in {o.name for o in col_model.objects})

    common = dict(filepath=path, export_format='GLB', use_selection=True,
                  export_animations=True, export_frame_range=True,
                  export_apply=False, export_yup=True)
    try:
        bpy.ops.export_scene.gltf(export_animation_mode='SCENE',
                                  export_anim_scene_split_object=False, **common)
    except TypeError:
        bpy.ops.export_scene.gltf(**common)
    print("[gen] exported launcher.glb (three.js: rigged nodes + baked clip)")


try:
    export_threejs_glb(os.path.join(OUT_DIR, "launcher.glb"))
except Exception as exc:
    print("[gen] glb export skipped:", exc)

print("[gen] done. objects:", sorted(o.name for o in col_model.objects))
