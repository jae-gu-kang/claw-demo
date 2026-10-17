"""generate_launcher.py 의 산출 GLB(`launcher.glb`) — 블렌더 없이 GLB만 읽어 확인한다.

실행: `pytest models`  (재생성은 README의 명령. 이 테스트는 커밋된 `.glb`를 본다)

가상환경은 발사관을 노드 이름과 **GLB에서 손으로 옮긴 치수**로 몬다(`web/world/src/core/launcher.ts`의
`LAUNCHER_GEOMETRY`). 디테일(볼트·스텐실·램프·둥근 모서리)을 덧붙여도 그 치수는 그대로여야 한다 —
캐니스터 개구·포구·레일 끝·피벗이 움직이면 기체가 관 밖에 서거나 발사 원점이 어긋난다.
"""

import json
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

    def materials(self):
        return {m["name"] for m in self.json.get("materials", [])}


@pytest.fixture(scope="module")
def glb():
    if not os.path.exists(GLB):
        pytest.fail("launcher.glb 가 없다 — README의 재생성 명령으로 만든다")
    return Glb(GLB)


def test_world_sources_parsed():
    assert LAUNCHER_NODES == ["Turntable", "Cradle", "Jack_FL", "Jack_FR", "Jack_RL", "Jack_RR"]
    assert {"turntableY", "cradleY", "muzzleZ", "tubeAftZ", "railTipZ", "turntableAftZ", "cradleAftZ",
            "rootScale"} <= set(GEOMETRY)


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


def test_nothing_on_the_cradle_intrudes_into_the_bore(glb):
    """크래들(외피·디테일)의 어떤 정점도 관 개구(반폭 1.32·반높이 0.42, 크래들 로컬 z −3.50…0.15) 안에 없다 —
    기체가 그 안에 선다. 개구 벽 위의 정점(경계)은 허용한다."""
    eps = 1e-3
    inside = [p for p in glb.positions("Cradle")
              if abs(p[0]) < 1.32 - eps and abs(p[1]) < 0.42 - eps and -3.50 + eps < p[2] < 0.15 - eps]
    assert not inside, inside[:5]


def test_cradle_underside_clears_the_fenders(glb):
    """선회하는 캐니스터 바닥(크래들 로컬 y −0.52 = 상판 기준 0.93)이 펜더 윗면(0.92) 위를 지난다 — 크래들 아랫면 디테일
    (보강 띠)은 그 1 cm 안에서만 솟는다. 넘으면 고각 0°에서 방위를 돌릴 때 띠가 펜더를 뚫는다."""
    assert min(p[1] for p in glb.positions("Cradle")) >= -0.529


def test_detail_materials_exist(glb):
    """실감을 내는 디테일 — 스텐실·타이어·미등이 GLB에 실렸다(칠이 빠지면 재질이 GLB에서 사라져 걸린다)."""
    assert {"Launcher_Marking", "Tyre", "Lamp_Red", "Lamp_Amber"} <= glb.materials()
