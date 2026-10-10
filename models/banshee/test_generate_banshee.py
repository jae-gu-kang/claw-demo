"""generate_banshee.py 의 산출 GLB(`banshee.glb`) — 블렌더 없이 GLB만 읽어 확인한다.

실행: `pytest models`  (재생성은 README의 명령. 이 테스트는 커밋된 `.glb`를 본다)

가상환경(web/world/src/scene/models.ts)이 이 모델을 shahed와 **같은 규약**으로 몬다:
로컬 +X 우현 · +Y 위 · +Z 후방, 엘레본 `rotation.x = δ`(+ = 뒷전 아래), 러더 `rotation.y = −δr`
(+ = 뒷전 오른쪽). 그 사실을 노드 이름이 아니라 **메시 정점을 실제로 돌려** 확인한다.
"""

import json
import math
import os
import struct

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GLB = os.path.join(HERE, "banshee.glb")
DRIVE_NODES = ["Elevon_In_L", "Elevon_Out_L", "Elevon_In_R", "Elevon_Out_R", "Rudder"]
# web/world/src/core/launcher.ts 의 VEHICLE_AFT_EXTENT — 원점 뒤로 이보다 길면 꼬리가 발사관 밖으로 나온다
VEHICLE_AFT_EXTENT = 1.90

# GLB는 커밋된 산출물이다 — 없으면 건너뛰지 않고 실패한다(건너뛰면 지워진 GLB가 초록으로 보인다).
assert os.path.exists(GLB), "banshee.glb 없음 — 커밋된 산출물이다. README의 재생성 명령으로 굽고 커밋할 것"


# ---- 4×4 행렬 (행 우선 리스트) ----------------------------------------------------------------

def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def trs(node):
    t = node.get("translation", [0.0, 0.0, 0.0])
    x, y, z, w = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    s = node.get("scale", [1.0, 1.0, 1.0])
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    return [[r[i][0] * s[0], r[i][1] * s[1], r[i][2] * s[2], t[i]] for i in range(3)] + [[0, 0, 0, 1]]


def rot(axis, a):
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return [[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]]
    return [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]]  # y


def apply(m, p):
    return [m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3)]


class Glb:
    def __init__(self, path):
        with open(path, "rb") as f:
            data = f.read()
        magic, _version, _length = struct.unpack_from("<4sII", data, 0)
        assert magic == b"glTF"
        off, self.bin = 12, b""
        while off < len(data):
            clen, ctype = struct.unpack_from("<I4s", data, off)
            chunk = data[off + 8:off + 8 + clen]
            if ctype == b"JSON":
                self.json = json.loads(chunk)
            elif ctype == b"BIN\x00":
                self.bin = chunk
            off += 8 + clen
        self.nodes = self.json["nodes"]
        self.index = {n.get("name"): i for i, n in enumerate(self.nodes)}
        self.parent = {c: i for i, n in enumerate(self.nodes) for c in n.get("children", [])}

    def node(self, name):
        return self.nodes[self.index[name]]

    def world(self, name, drive=None):
        """노드의 월드 행렬. drive = {노드 이름: (축, 각)} — three처럼 그 노드의 오일러 성분을 갈아 끼운다
        (모는 노드는 정지 회전이 항등이어야 한다 — test_drive_nodes_have_identity_rest가 고정)."""
        drive = drive or {}
        i, m = self.index[name], None
        while i is not None:
            local = trs(self.nodes[i])
            nm = self.nodes[i].get("name")
            if nm in drive:
                local = matmul(local, rot(*drive[nm]))
            m = local if m is None else matmul(local, m)
            i = self.parent.get(i)
        return m

    def positions(self, name):
        out = []
        mesh = self.json["meshes"][self.node(name)["mesh"]]
        for p in mesh["primitives"]:
            acc = self.json["accessors"][p["attributes"]["POSITION"]]
            view = self.json["bufferViews"][acc["bufferView"]]
            start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            flat = struct.unpack_from("<%df" % (acc["count"] * 3), self.bin, start)
            out += [flat[k:k + 3] for k in range(0, len(flat), 3)]
        return out

    def mesh_nodes_under(self, name):
        """name과 그 자손 중 메시가 있는 노드 이름."""
        out, stack = [], [self.index[name]]
        while stack:
            i = stack.pop()
            if "mesh" in self.nodes[i]:
                out.append(self.nodes[i]["name"])
            stack += self.nodes[i].get("children", [])
        return out

    def world_points(self, name, drive=None):
        return [apply(self.world(n, drive), p) for n in self.mesh_nodes_under(name) for p in self.positions(n)]


@pytest.fixture(scope="module")
def glb():
    return Glb(GLB)


def centre(pts):
    return [sum(p[k] for p in pts) / len(pts) for k in range(3)]


def test_root_declares_drive_nodes(glb):
    roots = [glb.nodes[i] for i in glb.json["scenes"][0]["nodes"]]
    assert len(roots) == 1
    declared = roots[0].get("extras", {}).get("claw_drive_nodes", "").split(",")
    assert declared == DRIVE_NODES
    for name in declared:
        assert name in glb.index, f"선언한 구동 노드가 없다: {name}"


def test_no_animation(glb):
    """가상환경은 클립을 재생하지 않는다 — 실으면 반입 꾸러미에 영구히 남는 바이트일 뿐이다."""
    assert not glb.json.get("animations")


def test_axes_nose_aft_starboard(glb):
    """로컬 +Z 후방(기수는 −Z), +X 우현, +Y 위 — shahed136.glb와 같은 축."""
    nose = centre(glb.world_points("Jet80_NoseCone"))
    fin = centre(glb.world_points("Jet80_Fin"))
    assert nose[2] < -1.0 < 0.5 < fin[2]
    assert fin[1] > 0.2                                         # 수직꼬리는 위
    assert centre(glb.world_points("Elevon_In_R"))[0] > 0.3     # 우익이 +X
    assert centre(glb.world_points("Elevon_In_L"))[0] < -0.3


def test_drive_nodes_have_identity_rest(glb):
    """three가 `rotation.x`/`.y`만 덮어쓰므로, 모는 노드의 정지 회전은 항등이어야 축이 힌지와 맞는다."""
    for name in DRIVE_NODES:
        q = glb.node(name).get("rotation", [0, 0, 0, 1])
        assert max(abs(a - b) for a, b in zip(q, [0, 0, 0, 1])) < 1e-6, name


def _aftmost(pts):
    return max(range(len(pts)), key=lambda k: pts[k][2])


@pytest.mark.parametrize("name", DRIVE_NODES[:4])
def test_elevon_positive_is_trailing_edge_down(glb, name):
    rest = glb.world_points(name)
    k = _aftmost(rest)
    moved = glb.world_points(name, {name: ("x", math.radians(15))})
    assert moved[k][1] < rest[k][1] - 0.01, f"{name}: rotation.x + 에 뒷전이 내려가야 한다"


def test_rudder_positive_rotation_y_is_trailing_edge_right(glb):
    """가상환경은 `rotation.y = −δr`(δr + = 뒷전 왼쪽)로 몬다 → rotation.y + = 뒷전 오른쪽(+X)."""
    rest = glb.world_points("Rudder")
    k = _aftmost(rest)
    moved = glb.world_points("Rudder", {"Rudder": ("y", math.radians(15))})
    assert moved[k][0] > rest[k][0] + 0.01
    assert abs(moved[k][1] - rest[k][1]) < 0.02                 # 힌지가 거의 수직 — 높이는 그대로


def test_fits_launcher_tube(glb):
    """원점 뒤 최대 길이 ≤ VEHICLE_AFT_EXTENT — 넘으면 발사관 안에 놓은 기체의 꼬리가 관 밖으로 나온다."""
    aft = max(p[2] for p in glb.world_points(glb.nodes[glb.json["scenes"][0]["nodes"][0]]["name"]))
    assert 1.0 < aft <= VEHICLE_AFT_EXTENT
