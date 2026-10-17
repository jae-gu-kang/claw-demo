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
import detail_kit as kit  # noqa: E402 — 표면 디테일(판·글자·볼트·둥근 상자), models/detail_kit.py

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
    except AttributeError:                      # 4.1+ — 자동 스무스가 없어져 날카로운 모서리를 직접 표시
        me.set_sharp_from_angle(angle=math.radians(angle_deg))


def finish(name, bm, mat, collection, pivot=(0, 0, 0), smooth=False):
    """bmesh를 오브젝트로. pivot을 원점으로 삼아(로컬화) 회전·이동 축을 맞춘다. mat은 재질 하나 또는 슬롯 목록."""
    if any(pivot):
        bmesh.ops.translate(bm, verts=bm.verts, vec=(-pivot[0], -pivot[1], -pivot[2]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in (mat if isinstance(mat, (list, tuple)) else [mat]):
        me.materials.append(m)
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
MAT_DARK = make_mat("DarkDetail", (0.055, 0.058, 0.062), rough=0.45)       # 히치·커넥터·전선관
MAT_METAL = make_mat("Metal", (0.340, 0.350, 0.330), rough=0.40, metal=0.7)  # 잭·레일·볼트
MAT_TUBE = make_mat("CanisterInner", (0.022, 0.024, 0.028), rough=0.72)    # 발사관 내부(암부)
# 디테일 재질 — 스텐실·타이어·램프 (test_generate_launcher.py가 GLB에 실렸는지 본다)
MAT_MARK = make_mat("Launcher_Marking", (0.700, 0.690, 0.620), rough=0.70)   # 바랜 흰 스텐실
MAT_TYRE = make_mat("Tyre", (0.030, 0.030, 0.032), rough=0.88)
MAT_LAMP_R = make_mat("Lamp_Red", (0.550, 0.020, 0.015), rough=0.15)
MAT_LAMP_A = make_mat("Lamp_Amber", (0.750, 0.330, 0.020), rough=0.15)
FONT = kit.first_font()

# 수직 배치 기준값 — 2026-09-02 개정: 높이는 낮추고 수평은 2배 (사용자 지정)
# 기체(전장 3.65 m·스팬 2.5 m)가 캐니스터 밖으로 삐져나와, 관 길이·폭을 지면 기준
# 2배로 늘리고 서 있는 높이는 오히려 낮췄다(축 3.56→2.90 m — 시뮬 발사 원점과의
# 어긋남도 그만큼 준다). root.scale 2.0은 그대로이므로 로컬 값 = 지면 미터의 절반.
BED = 0.80          # 트레일러 상판 높이 (0.92에서 낮춤)
TRUN = 1.45         # 트러니언(고각축) 높이 (1.78에서 낮춤 — 지면 기준 축 2.9 m)
# 트러니언을 관 뒤끝 근처로 — 관이 7.6 m라 피벗이 중앙이면 고각 15°에서 이미 뒤끝이
# 상판을 뚫는다(선회 반경 4 m). 뒤끝 0.3 뒤에 두면 48°에서도 상판 위 0.04가 남는다.
TT_PIV = (0.0, -0.90, BED)      # 턴테이블(방위각축) 피벗 — 트러니언 기둥이 디스크 위에 서게 뒤로
CR_PIV = (0.0, -1.80, TRUN)     # 크래들(고각축) 피벗
# 잭 = 4모서리 아웃리거. 받침 footprint(x=±2.56)를 바퀴 트랙(±2.24)보다 넓게 잡아 전복 방지.
JACKS = {"FL": (2.56, 3.40), "FR": (-2.56, 3.40),
         "RL": (2.56, -4.70), "RR": (-2.56, -4.70)}   # (x, y) 모서리
JACK_TOP = 1.00       # 슬리브 상단(레그가 항상 이 안에 물려 있음)
JACK_TRAVEL = 0.46    # 전개 시 하강량 (레그 상단은 슬리브 안에 남음 → 항상 연결)


# ---------------------------------------------------------------- 디테일 도구 (banshee와 같은 방법)
# 텍스처 0장 규칙이라 실감은 형상에서 낸다 — 둥근 모서리, 볼트 줄, 스텐실, 미등·반사판, 트레드 타이어,
# 공구함·연료통, 안전 체인·보조 바퀴. 가상환경이 쓰는 치수(관 개구·포구·레일 끝·피벗·잭 행정)는 그대로다 —
# test_generate_launcher.py가 GLB에서 고정한다. 캐니스터 쓸림(선회 반경 약 3.0, 바닥 0.93)과 고각 48°의 뒤끝
# 여유(상판 위 0.04) 안으로는 아무것도 세우지 않는다.
def hexbolt(bm, p, n, r=0.014, h=0.012):
    """평면 위 육각 볼트 — p: 표면 점, n: 바깥 법선."""
    p, n = Vector(p), Vector(n).normalized()
    return kit.lathe(bm, p - n * 0.003, n, [(0.0, r), (0.003 + 0.75 * h, r), (0.003 + h, 0.8 * r)], n=6)


def decorate(ob, fn):
    """완성된 오브젝트에 디테일을 붙이고(detail_kit.decorate) 각진 모서리를 다시 표시한다."""
    kit.decorate(ob, fn)
    shade_smooth(ob)


def rect_ring(y0, y1, z0, z1, pitch):
    """y–z 평면 직사각형 둘레의 점 — 둘레 길이를 pitch 이하 간격으로."""
    per = 2.0 * ((y1 - y0) + (z1 - z0))
    return kit.resample_closed([(y0, z0), (y1, z0), (y1, z1), (y0, z1)], max(4, round(per / pitch)))


# ---------------------------------------------------------------- 트레일러 (정적)
TR_MATS = [MAT_FRAME, MAT_DARK, MAT_METAL, MAT_LAMP_R, MAT_LAMP_A, MAT_OLIVE, MAT_TYRE]
FR_, DK_, MT_, LR_, LA_, OL_, TY_ = range(len(TR_MATS))
bm = bmesh.new()
for sx in (1.84, -1.84):                                   # 세로 대들보
    beam(bm, (sx, -5.10, BED - 0.16), (sx, 3.70, BED - 0.16), 0.20, 0.34)
for y in (-4.80, -3.30, -1.80, -0.30, 1.20, 2.40, 3.55):   # 가로 부재
    beam(bm, (-1.84, y, BED - 0.16), (1.84, y, BED - 0.16), 0.16, 0.22)
kit.rounded_box(bm, (-2.04, -4.90, BED - 0.02), (2.04, 3.64, BED + 0.04), 0.012)   # 상판
for sx in (2.24, -2.24):                                   # 펜더(흙받이) — 2축을 덮는다
    kit.rounded_box(bm, (sx - 0.22, -1.85, BED + 0.02), (sx + 0.22, 0.85, BED + 0.12), 0.035)  # 상단 0.92 < 선회하는 캐니스터 바닥 0.93
    kit.paint(kit.rounded_box(bm, (sx - 0.20, 0.86, 0.20), (sx + 0.20, 0.885, BED + 0.06), 0.006), DK_)  # 흙받이 고무
for (jx, jy) in JACKS.values():                            # 아웃리거 암 + 잭 슬리브(레그가 물리는 통)
    sx = 1.80 if jx > 0 else -1.80
    beam(bm, (sx, jy, BED - 0.06), (jx, jy, BED - 0.06), 0.12, 0.16)          # 프레임→모서리 수평 암
    beam(bm, (jx, jy, 0.55), (sx, jy, BED - 0.06), 0.06, 0.09)                # 대각 보강재
    kit.rounded_box(bm, (jx - 0.09, jy - 0.09, 0.40), (jx + 0.09, jy + 0.09, JACK_TOP), 0.015)  # 슬리브(통)
    out = 1.0 if jx > 0 else -1.0                          # 잭 크랭크 — 슬리브 위에서 바깥으로 꺾인 손잡이
    kit.paint(kit.tube(bm, [(jx, jy, JACK_TOP - 0.02), (jx, jy, JACK_TOP + 0.05),
                            (jx + out * 0.11, jy, JACK_TOP + 0.05), (jx + out * 0.11, jy, JACK_TOP + 0.12)],
                       0.012, n=8), MT_)
# 드로바(A-프레임) + 커플러 + 러넷
for sx in (1.00, -1.00):
    beam(bm, (sx, -4.85, BED - 0.18), (0.0, -7.40, 0.60), 0.12, 0.16)
kit.rounded_box(bm, (-0.14, -7.55, 0.50), (0.14, -7.30, 0.72), 0.02)
torus(bm, (0.0, -7.64, 0.61), 0.12, 0.038)
# 안전 체인 2줄 — 커플러 옆에서 드로바로 처진다
for sx in (1.0, -1.0):
    a, b = Vector((sx * 0.10, -7.32, 0.58)), Vector((sx * 0.46, -6.55, 0.58))
    kit.paint(kit.tube(bm, [a + (b - a) * (k / 10) + Vector((0, 0, -0.20 * 4 * (k / 10) * (1 - k / 10)))
                            for k in range(11)], 0.010, n=6), MT_, smooth=True)
# 보조 바퀴(잭 휠) — 왼쪽 드로바 중간, 바퀴가 지면(z 0)에 닿는다
JW = (0.47, -6.25)
kit.paint(kit.rounded_box(bm, (JW[0] - 0.06, JW[1] - 0.06, 0.56), (JW[0] + 0.06, JW[1] + 0.06, 0.70), 0.01), FR_)
kit.paint(kit.lathe(bm, (JW[0], JW[1], 0.18), (0, 0, 1), [(0.0, 0.032), (0.62, 0.032)], n=12), MT_, smooth=True)
kit.paint(kit.tube(bm, [(JW[0], JW[1], 0.78), (JW[0], JW[1], 0.82), (JW[0] + 0.12, JW[1], 0.82),
                        (JW[0] + 0.12, JW[1], 0.88)], 0.010, n=8), MT_)
for fx in (-0.05, 0.04):                                    # 포크 — 바퀴 양옆 두 판
    kit.paint(kit.rounded_box(bm, (JW[0] + fx, JW[1] - 0.03, 0.10), (JW[0] + fx + 0.01, JW[1] + 0.03, 0.22), 0.003), MT_)
kit.paint(kit.rounded_box(bm, (JW[0] - 0.05, JW[1] - 0.03, 0.21), (JW[0] + 0.05, JW[1] + 0.03, 0.23), 0.004), MT_)
kit.paint(kit.lathe(bm, (JW[0] - 0.035, JW[1], 0.10), (1, 0, 0),
                    [(0.0, 0.07), (0.01, 0.10), (0.06, 0.10), (0.07, 0.07)], n=20), TY_, smooth=True)
# 미등 — 뒤 가로 부재 끝에 하우징, 바깥쪽 빨강·안쪽 호박색 렌즈
for sx in (1.62, -1.62):
    o = 1.0 if sx > 0 else -1.0
    kit.paint(kit.rounded_box(bm, (sx - 0.20, 3.63, 0.56), (sx + 0.20, 3.69, 0.70), 0.012), DK_)
    kit.paint(kit.rounded_box(bm, (min(sx + o * 0.01, sx + o * 0.18), 3.685, 0.58),
                              (max(sx + o * 0.01, sx + o * 0.18), 3.703, 0.68), 0.006), LR_)
    kit.paint(kit.rounded_box(bm, (min(sx - o * 0.18, sx - o * 0.01), 3.685, 0.58),
                              (max(sx - o * 0.18, sx - o * 0.01), 3.703, 0.68), 0.006), LA_)
# 옆 반사판(호박색) — 대들보 바깥면 앞·뒤 + 대들보 볼트 줄
for sx in (1.0, -1.0):
    xo = sx * 1.94
    for y0 in (-4.55, 3.15):
        kit.paint(kit.rounded_box(bm, (min(xo, xo + sx * 0.012), y0, 0.62), (max(xo, xo + sx * 0.012), y0 + 0.10, 0.68),
                                  0.004), LA_)
    for y in kit.spaced((0.0, -5.0, 0.0), (0.0, 3.6, 0.0), 0.55, margin=0.25):
        if min(abs(y[1] - jy) for jy in (-4.70, 3.40)) > 0.14 and not (-4.60 < y[1] < -4.40 or 3.10 < y[1] < 3.30):
            kit.paint(hexbolt(bm, (xo, y[1], 0.75), (sx, 0, 0)), MT_)
            kit.paint(hexbolt(bm, (xo, y[1], 0.53), (sx, 0, 0)), MT_)
# 공구함·연료통 — 앞 상판(선회하는 캐니스터의 쓸림 반경 밖, 턴테이블 축에서 3.4 이상)
kit.paint(kit.rounded_box(bm, (-1.70, -4.80, BED + 0.04), (-0.50, -4.25, BED + 0.34), 0.02), OL_)
kit.paint(kit.rounded_box(bm, (-1.715, -4.815, BED + 0.30), (-0.485, -4.235, BED + 0.36), 0.015), OL_)  # 뚜껑
for x in (-1.45, -0.75):
    kit.paint(kit.rounded_box(bm, (x - 0.035, -4.83, BED + 0.24), (x + 0.035, -4.81, BED + 0.32), 0.004), MT_)
kit.paint(kit.lathe(bm, (-1.60, -4.24, BED + 0.355), (1, 0, 0), [(0.0, 0.012), (1.0, 0.012)], n=8), MT_, smooth=True)
for x0 in (0.70, 0.81):                                    # 연료통 두 개 — 위 손잡이 세 줄
    kit.paint(kit.rounded_box(bm, (x0, -4.78, BED + 0.04), (x0 + 0.083, -4.607, BED + 0.275), 0.012), OL_)
    kit.paint(kit.tube(bm, [(x0 + 0.0415, -4.75, BED + 0.27), (x0 + 0.0415, -4.75, BED + 0.30),
                            (x0 + 0.0415, -4.637, BED + 0.30), (x0 + 0.0415, -4.637, BED + 0.27)], 0.007, n=6), OL_)
trailer = finish("Trailer", bm, TR_MATS, col_model)


def trailer_markings(bm, surf, slot, L):
    mark = slot(MAT_MARK)
    for sx in (1.0, -1.0):                                 # 대들보 바깥면 — 밖에서 볼 때 왼쪽→오른쪽
        u, d = (0.0, sx, 0.0), (-sx, 0.0, 0.0)
        kit.paint(kit.stencil(bm, surf, "LCH-02", FONT, 0.10, (L((sx * 2.3, -3.70, 0.66)), u, (0, 0, 1)), d,
                              spacing=1.05), mark)
        kit.paint(kit.stencil(bm, surf, "MAX LOAD 6500 KG", FONT, 0.036,
                              (L((sx * 2.3, 2.40, 0.66)), u, (0, 0, 1)), d, spacing=1.08), mark)
    for sx in (2.24, -2.24):                               # 펜더 위 「NO STEP」 — 바깥에 선 사람이 읽는다
        o = 1.0 if sx > 0 else -1.0
        kit.paint(kit.stencil(bm, surf, "NO STEP", FONT, 0.07, (L((sx, -0.50, 1.2)), (0, o, 0), (-o, 0, 0)),
                              (0, 0, -1), spacing=1.1), mark)


decorate(trailer, trailer_markings)

# ---------------------------------------------------------------- 바퀴 (분리, 정적)
# 확대는 배치로 푼다 — 트랙·축거를 2배로 벌리고 축을 하나 더 단다(2축 4륜).
# 바퀴 자체를 수평만 2배 하면 타원이 되므로 반지름은 원형 그대로 둔다.
# 타이어는 단면(비드→옆면→트레드→옆면→비드→안쪽)을 축 둘레로 돌려 닫고, 트레드 고리는 러그를 엇갈려 판다.
TYRE_PROFILE = [(-0.150, 0.215, 0), (-0.158, 0.30, 0), (-0.150, 0.37, 0), (-0.128, 0.392, 1), (-0.045, 0.400, 1),
                (0.045, 0.400, 1), (0.128, 0.392, 1), (0.150, 0.37, 0), (0.158, 0.30, 0), (0.150, 0.215, 0)]
TYRE_N, LUG = 64, 0.014


def tyre(bm, c):
    rings = []
    for k, (ax, r, tread) in enumerate(TYRE_PROFILE):
        ring = []
        for i in range(TYRE_N):
            a = TAU * i / TYRE_N
            rr = r - (LUG if tread and ((i // 2 + (k >= 5)) % 2) else 0.0)
            ring.append(bm.verts.new((c[0] + ax, c[1] + rr * math.cos(a), c[2] + rr * math.sin(a))))
        rings.append(ring)
    faces = []
    for ra, rb in zip(rings, rings[1:] + rings[:1]):       # 안쪽(비드→비드)까지 이어 닫는다
        faces += [bm.faces.new((ra[i], ra[(i + 1) % TYRE_N], rb[(i + 1) % TYRE_N], rb[i])) for i in range(TYRE_N)]
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    return faces


wheels = {}
for sx, tag in ((2.24, "L"), (-2.24, "R")):
    out = 1.0 if sx > 0 else -1.0
    bm = bmesh.new()
    for ay in (-1.30, 0.30):                                # 앞·뒤 축
        kit.paint(tyre(bm, (sx, ay, 0.40)), 0, smooth=True)
        kit.paint(kit.lathe(bm, (sx - out * 0.14, ay, 0.40), (out, 0, 0), [(0.0, 0.214), (0.25, 0.214)], n=28),
                  1, smooth=True)                           # 림 통
        kit.paint(kit.lathe(bm, (sx + out * 0.10, ay, 0.40), (out, 0, 0),
                            [(0.0, 0.20), (0.012, 0.20), (0.02, 0.15), (0.035, 0.15)], n=28), 1, smooth=True)  # 림 면
        kit.paint(kit.lathe(bm, (sx + out * 0.125, ay, 0.40), (out, 0, 0),
                            [(0.0, 0.075), (0.03, 0.075), (0.045, 0.05), (0.05, 0.0)], n=20), 2, smooth=True)  # 허브캡
        for i in range(6):                                  # 휠 너트
            a = TAU * i / 6
            kit.paint(hexbolt(bm, (sx + out * 0.135, ay + 0.11 * math.cos(a), 0.40 + 0.11 * math.sin(a)),
                              (out, 0, 0), r=0.016, h=0.018), 2)
    wheels[tag] = finish("Wheel_" + tag, bm, [MAT_TYRE, MAT_FRAME, MAT_METAL], col_model,
                         pivot=(sx, -0.50, 0.40), smooth=True)

# ---------------------------------------------------------------- 지지대 잭 (분리, 전개)
# 텔레스코핑 레그: 상단은 늘 슬리브(z 0.40~1.00) 안에 물려 있고, 하단 풋패드가 지면(z=0)에
# 닿는다. 전개해도 트레일러↔지면이 슬리브-레그-패드로 끊김 없이 이어진다.
jacks = {}
for tag, (jx, jy) in JACKS.items():
    piv = (jx, jy, JACK_TOP)
    bm = bmesh.new()
    kit.rounded_box(bm, (jx - 0.06, jy - 0.06, 0.50), (jx + 0.06, jy + 0.06, JACK_TOP), 0.008)   # 내부 레그(슬리브에 물림)
    kit.paint(kit.rounded_box(bm, (jx - 0.19, jy - 0.19, 0.44), (jx + 0.19, jy + 0.19, 0.50), 0.012), 1)  # 풋패드
    for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        kit.paint(hexbolt(bm, (jx + dx * 0.14, jy + dy * 0.14, 0.50), (0, 0, 1), r=0.016, h=0.014), 0)
    jacks[tag] = finish("Jack_" + tag, bm, [MAT_METAL, MAT_DARK], col_model, pivot=piv, smooth=True)

# ---------------------------------------------------------------- 턴테이블 (방위각) + 고각 지지 기둥
bm = bmesh.new()
cylinder(bm, (0.0, -0.90, BED), (0.0, -0.90, BED + 0.24), 1.40, 1.24, 'z', n=40)      # 페데스탈
cylinder(bm, (0.0, -0.90, BED + 0.24), (0.0, -0.90, BED + 0.30), 1.32, 1.32, 'z', n=40)  # 상판 디스크
for sx in (1.32, -1.32):                                                              # 트러니언 기둥 (피벗 y=-1.80)
    beam(bm, (sx, -1.80, BED + 0.30), (sx, -1.80, TRUN), 0.22, 0.22)
    cylinder(bm, (sx - 0.08, -1.80, TRUN), (sx + 0.12, -1.80, TRUN), 0.15, 0.15, 'x', n=16)  # 베어링 보스
    face = sx + 0.12 if sx > 0 else sx - 0.08                                          # 보스 바깥면 볼트 6
    for i in range(6):
        a = TAU * i / 6 + TAU / 12
        kit.paint(hexbolt(bm, (face, -1.80 + 0.10 * math.cos(a), TRUN + 0.10 * math.sin(a)),
                          (1.0 if sx > 0 else -1.0, 0, 0)), 1)
# 선회 링기어 — 디스크 아래 톱니 96개(페데스탈에 반쯤 묻힌 링)
teeth = [1.300 if i % 2 == 0 else 1.278 for i in range(192)]
n0 = len(bm.faces)
loft(bm, [[(r * math.cos(TAU * i / 192), -0.90 + r * math.sin(TAU * i / 192), z) for i, r in enumerate(teeth)]
          for z in (BED + 0.175, BED + 0.235)])
bm.faces.ensure_lookup_table()
kit.paint([bm.faces[i] for i in range(n0, len(bm.faces))], 1)
for i in range(40):                                          # 디스크 윗면 볼트 원
    a = TAU * i / 40
    kit.paint(hexbolt(bm, (1.22 * math.cos(a), -0.90 + 1.22 * math.sin(a), BED + 0.30), (0, 0, 1),
                      r=0.016, h=0.012), 1)
turntable = finish("Turntable", bm, [MAT_FRAME, MAT_METAL], col_model, pivot=TT_PIV, smooth=True)

# ---------------------------------------------------------------- 크래들 + 발사관 본체 (고각)
BX, BZ = 1.44, 0.52          # 박스 반폭·반높이 — 폭은 2배, 높이는 오히려 슬림하게
BY0, BY1 = -2.10, 1.70       # 박스 뒤·앞(포구) — 길이 2배 (지면 기준 7.6 m)
# 단일 대형 캐니스터 개구. 지면 기준 개구 5.3×1.8 m·내부 길이 7.2 m — 기체(스팬 2.5 m·
# 전장 3.65 m)가 통째로 들어가고도 남는다. 관 뒤끝은 0.15 두께 벽으로 막힌 폐쇄 브리치.
TUBE_HX, TUBE_HZ = 1.32, 0.42   # 개구 반폭·반높이 (확대 전 로컬)

bm = bmesh.new()
kit.rounded_box(bm, (-BX, BY0, TRUN - BZ), (BX, BY1, TRUN + BZ), 0.035)            # 외피 — 모서리를 굴린다
for sx in (1, -1):
    x_in = sx * BX
    kit.rounded_box(bm, (min(x_in, x_in + sx * 0.08), -1.90, TRUN - 0.44),
                    (max(x_in, x_in + sx * 0.08), 1.10, TRUN + 0.48), 0.015)           # 측면 장갑판
    cylinder(bm, (sx * BX, -1.80, TRUN), (sx * 1.60, -1.80, TRUN), 0.15, 0.15, 'x', n=16)  # 트러니언 스텁
cradle = finish("Cradle", bm, [MAT_OLIVE, MAT_METAL, MAT_MARK, MAT_DARK], col_model, pivot=CR_PIV, smooth=True)

# 포구(+Y)에 단일 관통구 (불리언) — 뒤끝(-1.95)은 박스 뒤(-2.10)에 못 미쳐 브리치가 남는다
bm = bmesh.new()
add_box(bm, (-TUBE_HX, -1.95, TRUN - TUBE_HZ), (TUBE_HX, 2.05, TRUN + TUBE_HZ))
cutter = finish("cut_tube", bm, MAT_OLIVE, col_model)
boolean_diff(cradle, cutter)


def cradle_details(bm, surf, slot, L):
    """개구(|x| < 1.32, |z − TRUN| < 0.42) 안으로는 아무것도 넣지 않는다 — 기체가 그 안에 선다."""
    olive, metal, mark, dark = slot(MAT_OLIVE), slot(MAT_METAL), slot(MAT_MARK), slot(MAT_DARK)

    def box(p0, p1, r, mat):
        kit.paint(kit.rounded_box(bm, L(p0), L(p1), r), mat)

    def bolt_at(p, n, **kw):
        kit.paint(hexbolt(bm, L(p), n, **kw), metal)

    # 보강 띠 — 윗면·아랫면을 가로지른다(옆은 장갑판). 아랫면 띠는 8 mm만 솟는다 — 캐니스터 바닥(0.93)이 펜더
    # 윗면(0.92) 위를 지나므로, 그보다 내려오면 고각 0°에서 선회할 때 펜더를 뚫는다(test_generate_launcher.py)
    for y in (-1.35, -0.25, 0.85):
        box((-BX + 0.04, y - 0.03, TRUN + BZ - 0.01), (BX - 0.04, y + 0.03, TRUN + BZ + 0.022), 0.008, olive)
        box((-BX + 0.04, y - 0.03, TRUN - BZ - 0.008), (BX - 0.04, y + 0.03, TRUN - BZ + 0.01), 0.004, olive)
    # 포구 테 — 개구 둘레로 3.5 cm 솟은 틀 + 볼트, 위 앞모서리에 덮개 경첩
    rim = [((-BX + 0.03, TRUN + TUBE_HZ + 0.005), (BX - 0.03, TRUN + BZ - 0.03)),
           ((-BX + 0.03, TRUN - BZ + 0.03), (BX - 0.03, TRUN - TUBE_HZ - 0.005)),
           ((TUBE_HX + 0.005, TRUN - TUBE_HZ - 0.005), (BX - 0.03, TRUN + TUBE_HZ + 0.005)),
           ((-BX + 0.03, TRUN - TUBE_HZ - 0.005), (-TUBE_HX - 0.005, TRUN + TUBE_HZ + 0.005))]
    for (x0, z0), (x1, z1) in rim:
        box((x0, BY1 - 0.01, z0), (x1, BY1 + 0.035, z1), 0.006, olive)
    for x in kit.spaced((-1.30, 0, 0), (1.30, 0, 0), 0.26):
        for z in (TRUN + 0.47, TRUN - 0.47):
            bolt_at((x[0], BY1 + 0.035, z), (0, 1, 0))
    for x0, x1 in ((-1.30, -0.95), (-0.25, 0.25), (0.95, 1.30)):
        kit.paint(kit.lathe(bm, L((x0, BY1 + 0.005, TRUN + BZ - 0.004)), (1, 0, 0), [(0.0, 0.026), (x1 - x0, 0.026)],
                            n=12), metal, smooth=True)
    # 인양 고리 — 윗면 네 모서리
    for x in (-1.25, 1.25):
        for y in (-1.95, 1.50):
            box((x - 0.06, y - 0.05, TRUN + BZ - 0.01), (x + 0.06, y + 0.05, TRUN + BZ + 0.02), 0.006, metal)
            kit.paint(kit.tube(bm, [L((x, y + 0.055 * math.cos(TAU * k / 24), TRUN + BZ + 0.012 + 0.055 * math.sin(TAU * k / 24)))
                                    for k in range(13)], 0.011, n=8), metal, smooth=True)
    # 장갑판 볼트 둘레(트러니언 스텁 둘레는 건너뛴다) + 스텐실
    for sx in (1.0, -1.0):
        xo = sx * (BX + 0.08)
        for y, z in rect_ring(-1.855, 1.055, TRUN - 0.395, TRUN + 0.435, 0.30):
            if math.hypot(y + 1.80, z - TRUN) > 0.24:
                bolt_at((xo, y, z), (sx, 0, 0))
        u, d = (0.0, sx, 0.0), (-sx, 0.0, 0.0)
        for text, cap, y, z in (("DANGER", 0.13, -0.35, TRUN + 0.22),
                                ("ROCKET BLAST AREA - KEEP CLEAR 100 M", 0.045, -0.35, TRUN + 0.04),
                                ("UAV CANISTER  LC-2   LOT 0917", 0.030, -0.35, TRUN - 0.28)):
            kit.paint(kit.stencil(bm, surf, text, FONT, cap, (L((sx * 2.0, y, z)), u, (0, 0, 1)), d, spacing=1.06),
                      mark)
        # 명판 — 뒤 아래, 금속 판 + 작은 볼트 넷
        part = kit.plate(bm, surf, 0.22, 0.12, 0.01, (L((sx * 2.0, -1.35, TRUN - 0.22)), u, (0, 0, 1)), d,
                         thick=0.004)
        kit.paint(part, metal, smooth=True)
        for dy, dz in ((-0.09, -0.04), (0.09, -0.04), (0.09, 0.04), (-0.09, 0.04)):
            bolt_at((xo + sx * 0.0045, -1.35 + sx * dy, TRUN - 0.22 + dz), (sx, 0, 0), r=0.007, h=0.005)
    # 윗면 「NO STEP」(레일 사이, 뒤에서 읽힌다) · 뒷면 「DANGER BACKBLAST」
    kit.paint(kit.stencil(bm, surf, "NO STEP", FONT, 0.07, (L((0.0, -1.62, TRUN + 1.0)), (1, 0, 0), (0, 1, 0)), (0, 0, -1),
                          spacing=1.1), mark)
    kit.paint(kit.stencil(bm, surf, "DANGER  BACKBLAST", FONT, 0.075,
                          (L((0.0, BY0 - 0.5, TRUN + 0.25)), (1, 0, 0), (0, 0, 1)), (0, 1, 0), spacing=1.08), mark)
    # 뒷면 탯줄 커넥터 + 전선관(우현 아래 모서리를 따라 앞으로)
    box((0.62, BY0 - 0.06, TRUN - 0.32), (0.98, BY0 + 0.01, TRUN - 0.06), 0.01, dark)
    kit.paint(kit.lathe(bm, L((0.80, BY0 - 0.06, TRUN - 0.19)), (0, -1, 0),
                        [(0.0, 0.055), (0.05, 0.055), (0.05, 0.045), (0.065, 0.045)], n=16), metal, smooth=True)
    kit.paint(kit.tube(bm, [L((0.98, BY0 - 0.03, TRUN - 0.30)), L((1.30, BY0 - 0.03, TRUN - 0.44)),
                            L((BX + 0.03, BY0 + 0.15, TRUN - 0.475)), L((BX + 0.03, 0.90, TRUN - 0.475))], 0.024, n=10),
              dark, smooth=True)
    for y in (-1.40, -0.70, 0.0, 0.70):
        box((BX - 0.005, y - 0.03, TRUN - 0.51), (BX + 0.065, y + 0.03, TRUN - 0.44), 0.006, metal)


decorate(cradle, cradle_details)

# 캐니스터 내부 라이너(암부, 분리 오브젝트)
bm = bmesh.new()
add_box(bm, (-TUBE_HX + 0.025, -1.93, TRUN - TUBE_HZ + 0.025),
        (TUBE_HX - 0.025, 1.68, TRUN + TUBE_HZ - 0.025))
box_tubes = finish("Box_Tubes", bm, MAT_TUBE, col_model, pivot=CR_PIV)

# 상부 발사 레일 2줄 (금속, 포구 앞으로 돌출)
bm = bmesh.new()
for sx in (0.68, -0.68):
    beam(bm, (sx, -1.40, TRUN + BZ + 0.05), (sx, 2.90, TRUN + BZ + 0.05), 0.07, 0.11)
for y in (-0.8, 0.6, 1.9):
    beam(bm, (-0.68, y, TRUN + BZ + 0.05), (0.68, y, TRUN + BZ + 0.05), 0.05, 0.06)
box_rails = finish("Box_Rails", bm, MAT_METAL, col_model, pivot=CR_PIV, smooth=True)

# ---------------------------------------------------------------- 루트 엠프티 + 계층
root = bpy.data.objects.new("LAUNCHER_Root", None)
root.empty_display_type = 'PLAIN_AXES'
root.empty_display_size = 1.0
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

# **전체 2.0배** — 로컬 좌표를 지면 미터의 절반으로 쓰는 규약. 반드시 부모화 **뒤에**
# 건다: parent_to가 부모 월드행렬의 역을 캡처하므로, 스케일을 먼저 걸면 자식이 0.5를
# 물려받아 확대가 통째로 상쇄된다 — 실제로 그렇게 구워져 화면의 발사관이 1배로 남은
# 회귀가 있었다(2026-09-02). 지금 순서면 역행렬이 단위행렬이라 ×2가 전 계층에 산다.
# 런타임 관절 값(회전·잭 하강 0.46)은 전부 로컬이라 스케일과 무관하게 그대로 맞는다.
root.scale = (2.0, 2.0, 2.0)
bpy.context.view_layer.update()

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
target.location = (0.0, 0.10, 1.45)
col_studio.objects.link(target)

cam_data = bpy.data.cameras.new("Camera")
cam_data.lens = 32
cam = bpy.data.objects.new("Camera", cam_data)
cam.location = (16.0, 13.0, 9.0)                 # 포구(+Y) 쪽 상방 3/4 — 캐니스터 관통구가 보인다
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
