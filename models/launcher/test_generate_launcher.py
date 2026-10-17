"""generate_launcher.py 의 산출 GLB(`launcher.glb`) — 블렌더 없이 GLB만 읽어 확인한다.

실행: `pytest models`  (재생성은 README의 명령. 이 테스트는 커밋된 `.glb`를 본다)

가상환경은 발사관을 노드 이름과 **GLB에서 손으로 옮긴 치수**로 몬다(`web/world/src/core/launcher.ts`의
`LAUNCHER_GEOMETRY`). 디테일(볼트·스텐실·램프·둥근 모서리)을 덧붙여도 그 치수는 그대로여야 한다 —
캐니스터 개구·포구·레일 끝·피벗이 움직이면 기체가 관 밖에 서거나 발사 원점이 어긋난다.
"""

import json
import math
import os
import re
import struct

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
GLB = os.path.join(HERE, "launcher.glb")
WORLD = os.path.join(HERE, "..", "..", "web", "world", "src")


def _world_source(rel):
    with open(os.path.join(WORLD, rel), encoding="utf-8") as f:
        return f.read()


def _launcher_nodes():
    """web/world/src/scene/models.ts 의 LAUNCHER_NODES — 원문에서 읽는다(손 사본은 한쪽만 고쳐도 통과한다)."""
    body = re.search(r"LAUNCHER_NODES = \[(.*?)\]", _world_source("scene/models.ts"), re.S).group(1)
    return re.findall(r'"([^"]+)"', body)


def _launcher_geometry():
    """web/world/src/core/launcher.ts 의 LAUNCHER_GEOMETRY 숫자 칸(로컬 값 — rootScale 곱하기 전) — 원문에서 읽는다."""
    src = _world_source("core/launcher.ts")
    body = src[src.index("export const LAUNCHER_GEOMETRY"):src.index("} as const;", src.index("LAUNCHER_GEOMETRY"))]
    return {k: float(v) for k, v in re.findall(r"\b(\w+): (-?\d+(?:\.\d+)?),", body)}


LAUNCHER_NODES = _launcher_nodes()
GEOMETRY = _launcher_geometry()


class Glb:
    def __init__(self, path):
        with open(path, "rb") as f:
            data = f.read()
        magic, _version, _length = struct.unpack_from("<4sII", data, 0)
        assert magic == b"glTF"
        clen, _ctype = struct.unpack_from("<I4s", data, 12)
        self.json = json.loads(data[20:20 + clen])
        blen, _btype = struct.unpack_from("<I4s", data, 20 + clen)
        self.bin = data[28 + clen:28 + clen + blen]
        self.nodes = self.json["nodes"]
        self.index = {n.get("name"): i for i, n in enumerate(self.nodes)}

    def node(self, name):
        return self.nodes[self.index[name]]

    def bbox(self, name):
        prims = self.json["meshes"][self.node(name)["mesh"]]["primitives"]
        acc = [self.json["accessors"][p["attributes"]["POSITION"]] for p in prims]
        return ([min(a["min"][k] for a in acc) for k in range(3)],
                [max(a["max"][k] for a in acc) for k in range(3)])

    def positions(self, name):
        out = []
        for p in self.json["meshes"][self.node(name)["mesh"]]["primitives"]:
            acc = self.json["accessors"][p["attributes"]["POSITION"]]
            view = self.json["bufferViews"][acc["bufferView"]]
            start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            flat = struct.unpack_from("<%df" % (acc["count"] * 3), self.bin, start)
            out += [flat[k:k + 3] for k in range(0, len(flat), 3)]
        return out

    def triangles(self, name):
        """노드 메시의 삼각형(정점 셋, 감김 순서 그대로) — 면 방향을 볼 때 쓴다."""
        out = []
        for p in self.json["meshes"][self.node(name)["mesh"]]["primitives"]:
            pos_acc = self.json["accessors"][p["attributes"]["POSITION"]]
            view = self.json["bufferViews"][pos_acc["bufferView"]]
            start = view.get("byteOffset", 0) + pos_acc.get("byteOffset", 0)
            flat = struct.unpack_from("<%df" % (pos_acc["count"] * 3), self.bin, start)
            pts = [flat[k:k + 3] for k in range(0, len(flat), 3)]
            idx_acc = self.json["accessors"][p["indices"]]
            view = self.json["bufferViews"][idx_acc["bufferView"]]
            start = view.get("byteOffset", 0) + idx_acc.get("byteOffset", 0)
            fmt = {5121: "B", 5123: "H", 5125: "I"}[idx_acc["componentType"]]
            idx = struct.unpack_from("<%d%s" % (idx_acc["count"], fmt), self.bin, start)
            out += [(pts[idx[k]], pts[idx[k + 1]], pts[idx[k + 2]]) for k in range(0, len(idx), 3)]
        return out

    def materials(self):
        return {m["name"] for m in self.json.get("materials", [])}


@pytest.fixture(scope="module")
def glb():
    if not os.path.exists(GLB):
        pytest.fail("launcher.glb 가 없다 — README의 재생성 명령으로 만든다")
    return Glb(GLB)


def test_world_sources_parsed():
    assert LAUNCHER_NODES == ["Turntable", "Cradle", "Jack_FL", "Jack_FR", "Jack_RL", "Jack_RR", "Door_L", "Door_R"]
    assert {"turntableY", "cradleY", "muzzleZ", "tubeAftZ", "railTipZ", "turntableAftZ", "cradleAftZ",
            "rootScale", "doorOpenDeg"} <= set(GEOMETRY)
    # 문 열림각은 GLB에 안 실린다(드라이버 상수) — 생성 스크립트의 DOOR_OPEN과 가상환경 값을 원문끼리 대조한다
    with open(os.path.join(HERE, "generate_launcher.py"), encoding="utf-8") as f:
        door_open = float(re.search(r"^DOOR_OPEN = (\d+(?:\.\d+)?)", f.read(), re.M).group(1))
    assert GEOMETRY["doorOpenDeg"] == door_open


def test_driven_nodes_exist(glb):
    assert not [n for n in LAUNCHER_NODES if n not in glb.index]


def test_root_scale_and_pivots_match_world_constants(glb):
    assert glb.node("LAUNCHER_Root")["scale"] == pytest.approx([GEOMETRY["rootScale"]] * 3)
    tt, cr = glb.node("Turntable")["translation"], glb.node("Cradle")["translation"]
    assert tt[1] == pytest.approx(GEOMETRY["turntableY"], abs=1e-4)
    assert tt[2] == pytest.approx(GEOMETRY["turntableAftZ"], abs=1e-4)
    assert cr[1] == pytest.approx(GEOMETRY["cradleY"], abs=1e-4)
    assert cr[2] == pytest.approx(GEOMETRY["cradleAftZ"], abs=1e-4)


def test_canister_bore_and_rail_tip_are_unchanged(glb):
    """`Box_Tubes` bbox가 포구·관 뒤끝, `Box_Rails` bbox가 레일 끝이다 — 디테일을 여기 붙이면 그 값이 움직인다."""
    lo, hi = glb.bbox("Box_Tubes")
    assert lo[2] == pytest.approx(GEOMETRY["muzzleZ"], abs=0.005)
    assert hi[2] == pytest.approx(GEOMETRY["tubeAftZ"], abs=0.005)
    assert glb.bbox("Box_Rails")[0][2] == pytest.approx(GEOMETRY["railTipZ"], abs=0.005)


def test_bore_liner_is_open_at_the_muzzle_and_faces_inward(glb):
    """관 라이너(`Box_Tubes`, 암부)는 포구 쪽이 **뚫려** 있고 면이 관 안쪽을 본다. 닫힌 상자면 그 앞면이 포구를 판자처럼
    막아, 문이 열려도 관 속(과 그 안의 기체)이 안 보인다 — 하늘 환경광을 받아 올리브 판으로 읽혔다(v2.01 이전)."""
    tris = glb.triangles("Box_Tubes")
    assert tris
    covering = [t for t in tris if all(abs(p[2] - GEOMETRY["muzzleZ"]) < 0.01 for p in t)]
    assert not covering, covering[:2]
    lo, hi = glb.bbox("Box_Tubes")
    mid = [(a + b) / 2 for a, b in zip(lo, hi)]
    for a, b, c in tris:
        n = [(b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
             (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
             (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])]
        out = [(a[k] + b[k] + c[k]) / 3 - mid[k] for k in range(3)]
        assert sum(n[k] * out[k] for k in range(3)) < 0, (a, b, c)    # 안쪽(가운데)을 본다


def test_nothing_on_the_cradle_intrudes_into_the_bore(glb):
    """크래들(외피·디테일)의 어떤 정점도 관 개구(반폭 1.32·반높이 0.42, 크래들 로컬 z −3.50…0.15) 안에 없다 —
    기체가 그 안에 선다. 개구 벽 위의 정점(경계)은 허용한다."""
    eps = 1e-3
    inside = [p for p in glb.positions("Cradle")
              if abs(p[0]) < 1.32 - eps and abs(p[1]) < 0.42 - eps and -3.50 + eps < p[2] < 0.15 - eps]
    assert not inside, inside[:5]


def test_nothing_on_the_cradle_caps_the_bore_or_its_exit(glb):
    """관 속과 그 앞 통로(포구 앞)를 가로지르는 크래들 면이 없다 — 정점 검사는 모서리가 개구 벽에 걸친 판을 못 본다.
    불리언(EXACT)이 겹친 껍질(외피·장갑판·트러니언 스텁) 위에서 절개 상자의 앞면(포구 앞 0.35)을 남겨 포구를 막고
    있었다(v2.01에서 외피만 자른 뒤 덧붙이게 고침). 면 중심이 통로 안이면 막힌 것이다."""
    eps = 2e-3
    caps = []
    for a, b, c in glb.triangles("Cradle"):
        m = [(a[k] + b[k] + c[k]) / 3 for k in range(3)]
        if abs(m[0]) < TUBE_HX - eps and abs(m[1]) < TUBE_HY - eps and m[2] < 0.15 - eps:
            caps.append(m)
    assert not caps, caps[:3]


def test_cradle_underside_clears_the_fenders(glb):
    """선회하는 캐니스터 바닥(크래들 로컬 y −0.52 = 상판 기준 0.93)이 펜더 윗면(0.92) 위를 지난다 — 크래들 아랫면 디테일
    (보강 띠)은 그 1 cm 안에서만 솟는다. 넘으면 고각 0°에서 방위를 돌릴 때 띠가 펜더를 뚫는다."""
    assert min(p[1] for p in glb.positions("Cradle")) >= -0.529


# ---------------------------------------------------------------- 포구 문
# 크래들 로컬(glTF): 포구 면 z = −3.50, 포구 테 앞면 −3.535(+ 볼트 머리). 관 개구 반폭 1.32·반높이 0.42.
MUZZLE_FACE = -3.50
FACE_CLEAR = -3.54           # 문은 어떤 각에서도 이보다 앞(더 음수)에 있다 — 포구 테·볼트 머리를 긁지 않는다
TUBE_HX, TUBE_HY = 1.32, 0.42


def _door_points(glb, name, deg):
    """문 정점을 크래들 로컬로 — 경첩(노드 원점) 둘레로 three `rotation.y = deg`만큼 돌려서."""
    t = glb.node(name).get("translation", [0.0, 0.0, 0.0])
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(t[0] + x * c + z * s, t[1] + y, t[2] - x * s + z * c) for x, y, z in glb.positions(name)]


def _door_angle(name, f=1.0):
    """세계가 넣는 값 — 우현(+x) 문은 −열림각, 좌현(−x) 문은 +열림각이 바깥·앞으로 연다(core/launcher.ts)."""
    return (-1.0 if name == "Door_R" else 1.0) * GEOMETRY["doorOpenDeg"] * f


def test_doors_hang_on_the_cradle_and_close_the_muzzle(glb):
    """문은 크래들의 자식(고각·방위를 같이 탄다)이고, 닫히면 둘이 관 개구를 다 덮는다 — 그 뒤에 기체가 서 있다."""
    cradle = glb.node("Cradle")
    for name in ("Door_L", "Door_R"):
        assert glb.index[name] in cradle["children"], name
    assert glb.node("Door_R")["translation"][0] > TUBE_HX and glb.node("Door_L")["translation"][0] < -TUBE_HX
    shut = _door_points(glb, "Door_L", 0.0) + _door_points(glb, "Door_R", 0.0)
    assert max(p[2] for p in shut) <= FACE_CLEAR                       # 포구 면 앞
    # 두 짝이 만나는 틈(가운데)을 빼고 개구 폭·높이를 덮는다
    xs = sorted(p[0] for p in shut)
    assert xs[0] <= -TUBE_HX and xs[-1] >= TUBE_HX
    assert min(p[1] for p in shut) <= -TUBE_HY and max(p[1] for p in shut) >= TUBE_HY
    assert max(min(abs(p[0]) for p in _door_points(glb, n, 0.0)) for n in ("Door_L", "Door_R")) < 0.02


def test_doors_swing_clear_of_the_canister_face(glb):
    """열리는 내내(0°→열림각) 문 정점이 포구 면 뒤로 들어가지 않는다 — 경첩이 바깥 모서리 밖에 있어서다."""
    for name in ("Door_L", "Door_R"):
        for k in range(0, 21):
            pts = _door_points(glb, name, _door_angle(name, k / 20))
            assert max(p[2] for p in pts) <= FACE_CLEAR, (name, k)


def test_open_doors_clear_the_exit_corridor(glb):
    """다 열리면 관 개구를 앞으로 늘인 통로(|x| < 1.32, |y| < 0.42, 포구 앞) 안에 문 정점이 없다 — 기체가 지나간다."""
    for name in ("Door_L", "Door_R"):
        inside = [p for p in _door_points(glb, name, _door_angle(name))
                  if abs(p[0]) < TUBE_HX and abs(p[1]) < TUBE_HY and p[2] < MUZZLE_FACE]
        assert not inside, (name, inside[:3])


def test_doors_pass_under_the_rails(glb):
    """문 윗변이 상부 레일 바닥 아래다 — 문은 수직축으로 돌아 높이가 안 변하므로, 이게 맞으면 어느 각에서도 레일을 안 친다."""
    rails_bottom = min(p[1] for p in glb.positions("Box_Rails"))
    for name in ("Door_L", "Door_R"):
        assert max(p[1] for p in _door_points(glb, name, 0.0)) < rails_bottom, name


def test_detail_materials_exist(glb):
    """실감을 내는 디테일 — 스텐실·타이어·미등이 GLB에 실렸다(칠이 빠지면 재질이 GLB에서 사라져 걸린다)."""
    assert {"Launcher_Marking", "Tyre", "Lamp_Red", "Lamp_Amber"} <= glb.materials()
