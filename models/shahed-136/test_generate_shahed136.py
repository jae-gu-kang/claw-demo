"""generate_shahed136.py 의 산출 GLB — 블렌더 없이 GLB만 읽어 확인한다.

실행: `pytest models`  (재생성은 README의 명령. 이 테스트는 커밋된 `.glb`를 본다)

- 기본형(`shahed136.glb`)은 그대로다 — 원추 기수, EOIR 노드 없음.
- EOIR형(`shahed136_eoir.glb`)은 기수 대신 짐벌 볼이 붙고, 기본형의 노드를 **전부** 가진다
  (가상환경이 이름으로 조회하므로, 빠지면 타면이 조용히 안 움직인다 — web/world/src/scene/models.ts).
- 짐벌 부호는 구워진 클립에서 실측한다: pan + = 우측, tilt + = 위 (데모 키 프레임에서).
"""

import json
import math
import os
import struct

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 24

# web/world/src/scene/models.ts 의 VEHICLE_NODES
VEHICLE_NODES = ["Elevon_In_L", "Elevon_Out_L", "Elevon_In_R", "Elevon_Out_R",
                 "Rudder_L", "Rudder_R", "Propeller"]
EOIR_NODES = ["EOIR_Pan", "EOIR_Tilt"]


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

    def parent_of(self, name):
        i = self.index[name]
        for n in self.nodes:
            if i in n.get("children", []):
                return n.get("name")
        return None

    def accessor(self, i):
        acc = self.json["accessors"][i]
        assert acc["componentType"] == 5126             # float
        width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[acc["type"]]
        view = self.json["bufferViews"][acc["bufferView"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        flat = struct.unpack_from("<%df" % (acc["count"] * width), self.bin, start)
        return [flat[k:k + width] for k in range(0, len(flat), width)]

    def mesh_min(self, name):
        """노드 메시(서브메시 전부)의 POSITION 최소 — 노드 로컬."""
        mesh = self.json["meshes"][self.nodes[self.index[name]]["mesh"]]
        mins = [self.json["accessors"][p["attributes"]["POSITION"]]["min"]
                for p in mesh["primitives"]]
        return [min(m[k] for m in mins) for k in range(3)]

    def rotation_at(self, name, t):
        """구워진 클립에서 노드 회전 쿼터니언(x, y, z, w)을 시각 t [s]에 선형 보간."""
        target = self.index[name]
        for anim in self.json["animations"]:
            for ch in anim["channels"]:
                if ch["target"].get("node") == target and ch["target"]["path"] == "rotation":
                    s = anim["samplers"][ch["sampler"]]
                    # CUBICSPLINE이면 출력이 키당 3개(접선 포함)라 아래 인덱스가 조용히 어긋난다
                    assert s.get("interpolation", "LINEAR") == "LINEAR"
                    times = [v[0] for v in self.accessor(s["input"])]
                    quats = self.accessor(s["output"])
                    if t <= times[0]:
                        return quats[0]
                    for k in range(1, len(times)):
                        if t <= times[k]:
                            a = (t - times[k - 1]) / (times[k] - times[k - 1])
                            q = [p + a * (r - p) for p, r in zip(quats[k - 1], quats[k])]
                            n = math.sqrt(sum(c * c for c in q))
                            return [c / n for c in q]
                    return quats[-1]
        raise AssertionError("%s 에 rotation 트랙이 없다" % name)


def rotate(q, v):
    """쿼터니언 (x, y, z, w)로 벡터 회전."""
    x, y, z, w = q
    u = (x, y, z)
    uv = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    uuv = (u[1] * uv[2] - u[2] * uv[1], u[2] * uv[0] - u[0] * uv[2], u[0] * uv[1] - u[1] * uv[0])
    return tuple(v[k] + 2.0 * (w * uv[k] + uuv[k]) for k in range(3))


def frame_time(frame):
    return frame / FPS                                          # 실측: 1프레임 키가 t = 1/24


# glTF Y-up 노드 로컬: 블렌더 +Y(기수) → −Z, +X(우현) → +X, +Z(위) → +Y
BORESIGHT = (0.0, 0.0, -1.0)


def load(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        pytest.fail("%s 가 없다 — README의 재생성 명령으로 만든다" % name)
    return Glb(path)


@pytest.fixture(scope="module")
def base():
    return load("shahed136.glb")


@pytest.fixture(scope="module")
def eoir():
    return load("shahed136_eoir.glb")


def test_base_keeps_cone_nose_and_has_no_gimbal(base):
    for n in VEHICLE_NODES:
        assert n in base.index
    assert not [n for n in base.index if n and n.startswith("EOIR")]
    # 원추 기수 끝 = 블렌더 y 1.75 → glTF z −1.75
    assert base.mesh_min("Fuselage")[2] == pytest.approx(-1.75, abs=0.01)


def test_eoir_is_drop_in_with_gimbal_nodes(eoir):
    missing = [n for n in VEHICLE_NODES + EOIR_NODES if n not in eoir.index]
    assert not missing
    assert eoir.parent_of("EOIR_Pan") == "Fuselage"
    assert eoir.parent_of("EOIR_Tilt") == "EOIR_Pan"


def test_eoir_replaces_nose_cone(eoir):
    # 동체는 칼라(1.44)에서 끝나고, 그 앞은 볼(중심 1.47)이 채운다. 볼 앞면은 창으로 평평히
    # 잘렸고(0.085) 경통이 4 mm 솟으므로 최전방은 1.47 + 0.089 — 구 반경(0.10)이 아니다.
    assert eoir.mesh_min("Fuselage")[2] == pytest.approx(-1.44, abs=0.005)
    pan = eoir.nodes[eoir.index["EOIR_Pan"]]
    assert pan["translation"][2] == pytest.approx(-1.47, abs=0.005)
    tilt_min = eoir.mesh_min("EOIR_Tilt")
    assert pan["translation"][2] + tilt_min[2] == pytest.approx(-1.559, abs=0.002)


def test_eoir_ball_has_window_and_lenses(eoir):
    # 쓰이지 않는 재질 슬롯은 내보내기에서 빠진다 — 창이 하우징색으로 칠해지면 여기서 걸린다
    mesh = eoir.json["meshes"][eoir.nodes[eoir.index["EOIR_Tilt"]]["mesh"]]
    used = {eoir.json["materials"][p["material"]]["name"] for p in mesh["primitives"]}
    assert {"EOIR_Housing", "EOIR_Window", "EOIR_Lens_EO", "EOIR_Lens_IR"} <= used


# 부호만이 아니라 축과 크기까지 — 이득이 두 배로 구워지거나 축이 바뀌어도 걸린다.
# 데모 키 프레임에서 잰다(구운 키가 프레임마다 있어 보간이 끼지 않는다).
@pytest.mark.parametrize("frame, pan_deg", [(72, 45), (30, -45)])
def test_eoir_pan_turns_boresight_about_up_axis(eoir, frame, pan_deg):
    a = math.radians(pan_deg)
    look = rotate(eoir.rotation_at("EOIR_Pan", frame_time(frame)), BORESIGHT)
    assert look == pytest.approx((math.sin(a), 0.0, -math.cos(a)), abs=0.01)   # + = 우현(+X)


def test_eoir_tilt_turns_boresight_about_lateral_axis(eoir):
    a = math.radians(-60)                                                       # 데모 키 138
    look = rotate(eoir.rotation_at("EOIR_Tilt", frame_time(138)), BORESIGHT)
    assert look == pytest.approx((0.0, math.sin(a), -math.cos(a)), abs=0.01)   # + = 위(+Y)
