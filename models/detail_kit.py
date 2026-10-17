"""기체·발사관 생성 스크립트가 함께 쓰는 디테일 도구 — 표면에 붙는 판·글자·이음선·볼트, 둥근 상자.

banshee 원본(`banshee/banshee_assembly.py`)이 실감을 내는 방법을 다른 모델에도 쓰려고 뽑았다: 도장 위 글자(스텐실),
나사가 둘린 점검판, 패널 이음선, 모서리가 둥근 상자. 텍스처 0장 규칙이라(`web/world/src/scene/materials.ts`) 전부
**형상**이다 — 곡면에 맞추려고 각 점을 대상 메시에 광선으로 투영해 앉힌다(`Surface`).

- 위쪽 함수(윤곽·간격·채우기)는 순수 파이썬이다 — `test_detail_kit.py`가 블렌더 없이 잰다.
- 아래쪽(`Surface`부터)은 블렌더 안에서만 돈다(bmesh·mathutils를 함수 안에서 import한다).
- 판·볼트·관·둥근 상자는 **닫힌 입체**다 — 면 법선을 다시 계산해도(`recalc_face_normals`) 바깥이 뒤집히지 않는다.
  **칠한 글자(`stencil`)와 이음선(`ribbon`, 기본)은 윗면만 있는 열린 조각**이다(옆벽은 보이지 않고 GLB만 붓는다) —
  만들 때 표면 법선 쪽으로 감아 두므로, 그 메시에서는 면 법선을 다시 계산하면 안 된다. 그래서 완성된 오브젝트에
  붙이는 `decorate`로 붙인다(다시 계산하지 않는다). 반환은 면 묶음 {"top", "side", "bottom"}이라 부르는 쪽이 윗면과
  옆면에 재질을 따로 줄 수 있다(옆면을 어둡게 하면 판 윤곽이 이음선처럼 읽힌다).
"""

import math
import os

# 스텐실 글꼴 — 있는 첫 파일(없으면 블렌더 내장 글꼴). 기계마다 글꼴이 달라 GLB 바이트가 갈릴 수 있다(banshee와 같다).
STENCIL_FONTS = ("/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
                 "C:/Windows/Fonts/bahnschrift.ttf",
                 "C:/Windows/Fonts/arialbd.ttf")


def first_font(paths=STENCIL_FONTS):
    return next((p for p in paths if os.path.exists(p)), None)


# ---------------------------------------------------------------------------- 순수 기하 (블렌더 불필요)


def rounded_rect(w, h, r, n_arc=4):
    """원점 중심 w×h 직사각형의 모서리를 반경 r로 깎은 윤곽 — 반시계 (u, v) 점 목록."""
    if r <= 0.0:
        raise ValueError("r > 0 이어야 한다 — 0이면 모서리 점이 겹친다")
    r = min(r, 0.5 * w, 0.5 * h)
    corners = ((0.5 * w - r, 0.5 * h - r, 0.0), (-0.5 * w + r, 0.5 * h - r, 90.0),
               (-0.5 * w + r, -0.5 * h + r, 180.0), (0.5 * w - r, -0.5 * h + r, 270.0))
    pts = []
    for cx, cy, a0 in corners:
        for j in range(n_arc + 1):
            a = math.radians(a0 + 90.0 * j / n_arc)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def circle(r, n=24, phase=0.0, center=(0.0, 0.0)):
    """반시계 원 윤곽 (u, v)."""
    return [(center[0] + r * math.cos(phase + 2.0 * math.pi * i / n),
             center[1] + r * math.sin(phase + 2.0 * math.pi * i / n)) for i in range(n)]


def resample_closed(pts, n):
    """닫힌 다각형 위에 호 길이로 같은 간격인 점 n개 (첫 점에서 시작)."""
    seg = [math.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    total = sum(seg)
    out, i, acc = [], 0, 0.0
    for k in range(n):
        s = total * k / n
        while acc + seg[i] < s - 1e-12:
            acc += seg[i]
            i += 1
        t = (s - acc) / seg[i] if seg[i] else 0.0
        a, b = pts[i], pts[(i + 1) % len(pts)]
        out.append(tuple(a[c] + t * (b[c] - a[c]) for c in range(len(a))))
    return out


def spaced(a, b, pitch, margin=0.0):
    """a→b 선분 위, 양 끝에서 margin 떨어진 구간을 pitch 이하 간격으로 고르게 나눈 점(양 끝 포함)."""
    d = math.dist(a, b)
    span = d - 2.0 * margin
    if span <= 0.0:
        return []
    n = max(1, math.ceil(span / pitch - 1e-9))
    return [tuple(a[c] + (b[c] - a[c]) * (margin + span * k / n) / d for c in range(len(a)))
            for k in range(n + 1)]


def fill_convex(outline, rings=3):
    """볼록 윤곽 안을 동심 고리로 채운다 — (점, 면). 점의 앞 len(outline)개는 윤곽 그대로다.

    한 장짜리 면이 아니라 고리로 나누는 까닭: 각 점을 곡면에 투영하므로 안쪽에도 점이 있어야 판이 곡면을 따른다."""
    n = len(outline)
    cx = sum(p[0] for p in outline) / n
    cy = sum(p[1] for p in outline) / n
    verts = []
    for k in range(rings):
        s = 1.0 - k / rings
        verts += [(cx + (p[0] - cx) * s, cy + (p[1] - cy) * s) for p in outline] if k else list(outline)
    verts.append((cx, cy))
    faces = []
    for k in range(rings - 1):
        o, i = k * n, (k + 1) * n
        faces += [(o + j, o + (j + 1) % n, i + (j + 1) % n, i + j) for j in range(n)]
    c, o = len(verts) - 1, (rings - 1) * n
    faces += [(o + j, o + (j + 1) % n, c) for j in range(n)]
    return verts, faces


# ---------------------------------------------------------------------------- 블렌더 안에서만


def _vec(p):
    from mathutils import Vector
    return Vector(p)


class Surface:
    """대상 메시(bmesh 또는 Mesh)의 BVH — 점을 정한 방향으로 쏘아 표면에 앉힌다.

    만든 순간의 형상을 복사해 둔다 — 뒤에 같은 bmesh에 디테일을 붙여도 그 디테일 위로 투영하지 않는다."""

    def __init__(self, src):
        import bmesh
        from mathutils.bvhtree import BVHTree
        if isinstance(src, bmesh.types.BMesh):
            tmp = src.copy()
        else:
            tmp = bmesh.new()
            tmp.from_mesh(src)
        bmesh.ops.triangulate(tmp, faces=tmp.faces[:])
        self.bvh = BVHTree.FromBMesh(tmp)
        tmp.free()

    def hit(self, p, d, reach=1.0):
        """p에서 −d로 reach만큼 물러난 곳에서 d로 쏜 첫 교점 — (위치, d를 거스르는 단위 법선)."""
        d = _vec(d).normalized()
        loc, nrm, _i, _dist = self.bvh.ray_cast(_vec(p) - d * reach, d, 2.0 * reach)
        if loc is None:
            raise ValueError("표면을 못 찾았다: p=%s d=%s" % (tuple(p), tuple(d)))
        if nrm.dot(d) > 0.0:
            nrm = -nrm
        return loc, nrm.normalized()


def _new_faces(bm, verts, faces):
    vs = [bm.verts.new(v) for v in verts]
    return [bm.faces.new([vs[i] for i in f]) for f in faces]


def _shell(bm, top, bottom, faces2d, closed_rim=None):
    """같은 위상의 윗점·아랫점 목록과 2D 면으로 닫힌 껍질을 만든다. rim은 경계 변(한 면만 쓰는 변)에서 찾는다."""
    vt = [bm.verts.new(p) for p in top]
    vb = [bm.verts.new(p) for p in bottom]
    out = {"top": [], "side": [], "bottom": []}
    count = {}
    for f in faces2d:
        out["top"].append(bm.faces.new([vt[i] for i in f]))
        out["bottom"].append(bm.faces.new([vb[i] for i in reversed(f)]))
        for a, b in zip(f, f[1:] + f[:1]):
            count[(a, b)] = count.get((a, b), 0) + 1
    for (a, b) in count:
        if (b, a) not in count:                          # 경계 변 — 옆벽
            out["side"].append(bm.faces.new((vt[b], vt[a], vb[a], vb[b])))
    import bmesh
    bmesh.ops.recalc_face_normals(bm, faces=out["top"] + out["side"] + out["bottom"])
    return out


def _skin(bm, pts, normals, faces):
    """윗면만 — 면마다 표면 법선 쪽을 바라보게 감는다(칠한 글자·이음선: 옆벽은 0.5 mm라 보이지 않고 정점만 늘린다)."""
    vs = [bm.verts.new(p) for p in pts]
    out = []
    for f in faces:
        a, b, c = (pts[i] for i in f[:3])
        nrm = sum((normals[i] for i in f), normals[f[0]] * 0.0)
        out.append(bm.faces.new([vs[i] for i in (f if (b - a).cross(c - a).dot(nrm) > 0.0 else f[::-1])]))
    return {"top": out, "side": [], "bottom": []}


def conformal(bm, surf, pts2d, faces2d, frame, d, lift=0.0006, thick=0.0008, sink=0.0004, solid=True):
    """2D 도형(점·면)을 frame=(원점, u, v) 평면에 놓고 d 방향으로 표면에 투영해 얇은 판으로 앉힌다.

    윗면은 표면 위 lift+thick, 아랫면은 표면 아래 sink — 바닥이 살짝 박혀 곡면 사이로 틈이 비치지 않는다.
    solid=False면 윗면만 만든다(닫힌 입체가 아니므로 부르는 쪽이 면 법선을 다시 계산하면 안 된다)."""
    o, u, v = (_vec(x) for x in frame)
    top, bottom, normals = [], [], []
    for x, y in pts2d:
        loc, n = surf.hit(o + u * x + v * y, d)
        top.append(loc + n * (lift + thick))
        bottom.append(loc - n * sink)
        normals.append(n)
    if not solid:
        return _skin(bm, top, normals, [list(f) for f in faces2d])
    return _shell(bm, top, bottom, [list(f) for f in faces2d])


def plate(bm, surf, w, h, r, frame, d, lift=0.0006, thick=0.0012, rings=3):
    """모서리가 둥근 점검판 — conformal 판. 반환 면 묶음."""
    verts, faces = fill_convex(rounded_rect(w, h, r), rings)
    return conformal(bm, surf, verts, faces, frame, d, lift, thick)


def disc(bm, surf, r, frame, d, lift=0.0006, thick=0.0025, n=24, rings=2):
    verts, faces = fill_convex(circle(r, n), rings)
    return conformal(bm, surf, verts, faces, frame, d, lift, thick)


def text_shape(text, font_path, cap_height, x_scale=1.0, spacing=1.0, max_edge=0.02):
    """글자를 평면 삼각형 (점, 면)으로 — 대문자 높이 cap_height, 원점 중심, +x로 읽힌다(banshee text_decal과 같은 길)."""
    import bmesh
    import bpy
    font = None
    if font_path:
        try:
            font = bpy.data.fonts.load(font_path)
        except Exception:                                # 글꼴이 없으면 블렌더 내장 글꼴
            font = None
    cu = bpy.data.curves.new("tmp_text", "FONT")
    cu.body = text
    if font:
        cu.font = font
    cu.size = 1.0
    cu.resolution_u = 3                                  # 곡선 분할 — 기본 12는 작은 글자에 과하다(GLB가 MB 단위로 붓는다)
    cu.space_character = spacing
    cu.align_x = "CENTER"
    tmp = bpy.data.objects.new("tmp_text", cu)
    bpy.context.scene.collection.objects.link(tmp)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bm = bmesh.new()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    if font:
        bpy.data.fonts.remove(font)

    ys = [vv.co.y for vv in bm.verts]
    xs = [vv.co.x for vv in bm.verts]
    k = cap_height / (max(ys) - min(ys))
    cx, cy = 0.5 * (max(xs) + min(xs)), 0.5 * (max(ys) + min(ys))
    for vv in bm.verts:
        vv.co = _vec(((vv.co.x - cx) * k * x_scale, (vv.co.y - cy) * k, 0.0))
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    # "T" 같은 글자는 높이 0인 조각 삼각형을 낸다 — 나누기 전에 걷어 낸다(banshee와 같은 처방)
    slivers = [f for f in bm.faces if 2.0 * f.calc_area() < 2e-5 * max(e.calc_length() for e in f.edges)]
    bmesh.ops.delete(bm, geom=slivers, context="FACES_ONLY")
    bmesh.ops.delete(bm, geom=[e for e in bm.edges if not e.link_faces], context="EDGES")
    bmesh.ops.delete(bm, geom=[vv for vv in bm.verts if not vv.link_faces], context="VERTS")
    for _ in range(10):
        long_edges = [e for e in bm.edges if e.calc_length() > max_edge]
        if not long_edges:
            break
        bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.verts.index_update()
    verts = [(vv.co.x, vv.co.y) for vv in bm.verts]
    faces = []
    for f in bm.faces:
        idx = [vv.index for vv in f.verts]
        a, b, c = (verts[i] for i in idx[:3])
        area = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        faces.append(idx if area > 0 else idx[::-1])     # 반시계로 맞춘다
    bm.free()
    return verts, faces


def stencil(bm, surf, text, font_path, cap_height, frame, d, x_scale=1.0, spacing=1.0,
            lift=0.0006, max_edge=0.02):
    """표면에 칠한 글자(윗면만) — frame=(가운데, 읽는 방향 u, 위 v). u×v가 바깥을 향하게 준다."""
    verts, faces = text_shape(text, font_path, cap_height, x_scale, spacing, max_edge)
    return conformal(bm, surf, verts, faces, frame, d, lift, 0.0, solid=False)


def ribbon(bm, surf, path, dirs, width, lift=0.0004, thick=0.0006, closed=False, solid=False):
    """표면을 따라가는 띠(이음선·띠 도색) — path 점마다 dirs[i] 방향으로 투영한다. 반환 면 묶음.
    solid=False(기본)면 윗면 띠만 — 칠한 선이라 옆벽이 보이지 않는다."""
    hits = [surf.hit(p, d) for p, d in zip(path, dirs)]
    m = len(hits)
    rings = []
    for i, (loc, n) in enumerate(hits):
        a = hits[(i - 1) % m if closed else max(i - 1, 0)][0]
        b = hits[(i + 1) % m if closed else min(i + 1, m - 1)][0]
        side = (b - a).cross(n).normalized() * (0.5 * width)
        base, top = loc - n * 0.0004, loc + n * (lift + thick)
        rings.append((top + side, top - side, base - side, base + side))
    if not solid:
        pts = [p for r in rings for p in r[:2]]
        nrm = [n for _loc, n in hits for _ in range(2)]
        faces = [(2 * i, 2 * ((i + 1) % m), 2 * ((i + 1) % m) + 1, 2 * i + 1)
                 for i in range(m if closed else m - 1)]
        return _skin(bm, pts, nrm, faces)
    out = {"top": [], "side": [], "bottom": []}
    vs = [[bm.verts.new(p) for p in r] for r in rings]
    for i in range(m if closed else m - 1):
        a, b = vs[i], vs[(i + 1) % m]
        out["top"].append(bm.faces.new((a[0], b[0], b[1], a[1])))
        out["side"].append(bm.faces.new((a[1], b[1], b[2], a[2])))
        out["bottom"].append(bm.faces.new((a[2], b[2], b[3], a[3])))
        out["side"].append(bm.faces.new((a[3], b[3], b[0], a[0])))
    if not closed:
        out["side"].append(bm.faces.new(vs[0][::-1]))
        out["side"].append(bm.faces.new(vs[-1]))
    import bmesh
    bmesh.ops.recalc_face_normals(bm, faces=out["top"] + out["side"] + out["bottom"])
    return out


def _frame(n):
    n = _vec(n).normalized()
    e1 = n.orthogonal().normalized()
    return n, e1, n.cross(e1)


def lathe(bm, base, axis, profile, n=12, phase=0.0):
    """축 axis 둘레 회전체 — profile = [(축 방향 거리, 반경)], 양 끝 막음. 볼트·리벳·램프·관·축에 쓴다."""
    axis, e1, e2 = _frame(axis)
    base = _vec(base)
    rings = []
    for s, r in profile:
        c = base + axis * s
        rings.append([c + (e1 * math.cos(phase + 2 * math.pi * k / n)
                           + e2 * math.sin(phase + 2 * math.pi * k / n)) * r for k in range(n)])
    vs = [[bm.verts.new(p) for p in ring] for ring in rings]
    faces = []
    for a, b in zip(vs, vs[1:]):
        faces += [bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k])) for k in range(n)]
    faces.append(bm.faces.new(vs[0][::-1]))
    faces.append(bm.faces.new(vs[-1]))
    import bmesh
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    return faces


def bolt(bm, surf, p, d, r=0.004, h=0.0025, hexagon=True):
    """표면에 앉은 볼트 머리(육각) 또는 둥근 리벳 머리 — 표면 아래로 살짝 박는다."""
    loc, n = surf.hit(p, d)
    if hexagon:
        return lathe(bm, loc - n * 0.001, n, [(0.0, r), (0.001 + 0.8 * h, r), (0.001 + h, 0.8 * r)], n=6)
    # 둥근 머리 — 작아서(수 mm) 고리 셋·6각이면 충분하다. 점이 많으면 리벳 줄 하나가 GLB를 수백 KB 붓는다
    return lathe(bm, loc - n * 0.001, n, [(0.0, r), (0.001 + 0.5 * h, 0.95 * r), (0.001 + h, 0.45 * r)], n=6)


def bolts(bm, surf, pts, d, **kw):
    out = []
    for p in pts:
        out += bolt(bm, surf, p, d, **kw)
    return out


def on_frame(frame, pts2d):
    """frame=(원점, u, v) 평면 위 2D 점 → 3D 점."""
    o, u, v = (_vec(x) for x in frame)
    return [o + u * x + v * y for x, y in pts2d]


def rounded_box(bm, p0, p1, r, seg=2):
    """축 정렬 상자(최소 모서리 p0, 최대 p1)의 모서리를 반경 r로 굴린다 — 빛이 모서리에 맺혀 실물처럼 읽힌다."""
    import bmesh
    tmp = bmesh.new()
    bmesh.ops.create_cube(tmp, size=1.0)
    size = [p1[i] - p0[i] for i in range(3)]
    c = [0.5 * (p0[i] + p1[i]) for i in range(3)]
    for vv in tmp.verts:
        vv.co = _vec([vv.co[i] * size[i] + c[i] for i in range(3)])
    bmesh.ops.bevel(tmp, geom=list(tmp.edges), offset=min(r, 0.45 * min(size)), segments=seg,
                    profile=0.5, affect="EDGES")
    tmp.verts.index_update()
    verts = [vv.co.copy() for vv in tmp.verts]
    faces = [[vv.index for vv in f.verts] for f in tmp.faces]
    tmp.free()
    return _new_faces(bm, verts, faces)


def tube(bm, points, r, n=8):
    """점열을 따라가는 원형 관(양 끝 막음) — 케이블·체인·파이프. 기준축을 앞 링에서 이어 받아 꼬이지 않는다."""
    pts = [_vec(p) for p in points]
    rings, e1 = [], None
    for i, p in enumerate(pts):
        d = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        e1 = d.orthogonal().normalized() if e1 is None else (e1 - d * e1.dot(d)).normalized()
        e2 = d.cross(e1)
        rings.append([p + (e1 * math.cos(2 * math.pi * k / n) + e2 * math.sin(2 * math.pi * k / n)) * r
                      for k in range(n)])
    vs = [[bm.verts.new(q) for q in ring] for ring in rings]
    faces = []
    for a, b in zip(vs, vs[1:]):
        faces += [bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k])) for k in range(n)]
    faces.append(bm.faces.new(vs[0][::-1]))
    faces.append(bm.faces.new(vs[-1]))
    import bmesh
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    return faces


def decorate(ob, fn):
    """완성된 오브젝트에 디테일을 붙인다 — fn(bm, 표면, 재질→슬롯, 월드→로컬).

    표면은 붙이기 **전** 형상이다(디테일 위로 투영하지 않는다). 월드→로컬은 오브젝트 원점만 뺀다 — 부모화·회전 전
    (생성 스크립트가 계층을 묶기 전)에 부른다는 전제다. 면 법선을 다시 계산하지 않는다(칠한 글자는 열린 조각이다).
    각진 모서리 표시는 부르는 쪽이 다시 한다(스크립트마다 shade_smooth가 있다)."""
    import bmesh
    from mathutils import Vector
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    surf = Surface(bm)
    origin = Vector(ob.location)

    def slot(mat):
        for i, m in enumerate(me.materials):
            if m == mat:
                return i
        me.materials.append(mat)
        return len(me.materials) - 1
    fn(bm, surf, slot, lambda q: Vector(q) - origin)
    bm.to_mesh(me)
    bm.free()


def paint(faces, index, smooth=False):
    """면 목록(또는 면 묶음 dict의 전부)에 재질 슬롯과 부드러운 음영을 준다."""
    if isinstance(faces, dict):
        faces = [f for group in faces.values() for f in group]
    for f in faces:
        f.material_index = index
        f.smooth = smooth
    return faces
