"""generate_shahed136.py 의 산출 GLB — 블렌더 없이 GLB만 읽어 확인한다.

실행: `pytest models`  (재생성은 README의 명령. 이 테스트는 커밋된 `.glb`를 본다)

- 기본형(`shahed136.glb`)은 그대로다 — 원추 기수, EOIR 노드 없음.
- EOIR형(`shahed136_eoir.glb`)은 기수 대신 총알형 EO/IR 헤드가 붙고, 기본형의 노드를 **전부** 가진다
  (가상환경이 이름으로 조회하므로, 빠지면 타면이 조용히 안 움직인다 — web/world/src/scene/models.ts).
- 짐벌 부호는 구워진 클립에서 실측한다: pan + = 우측, tilt + = 위 (데모 키 프레임에서).
"""

import json
import math
import os
import re
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

    def mesh_max(self, name):
        """노드 메시(서브메시 전부)의 POSITION 최대 — 노드 로컬."""
        mesh = self.json["meshes"][self.nodes[self.index[name]]["mesh"]]
        maxs = [self.json["accessors"][p["attributes"]["POSITION"]]["max"]
                for p in mesh["primitives"]]
        return [max(m[k] for m in maxs) for k in range(3)]

    def materials_of(self, name):
        """노드 메시가 쓰는 재질 이름 — 안 쓰인 슬롯은 내보내기에서 빠지므로 실제로 칠해진 것만 남는다."""
        mesh = self.json["meshes"][self.nodes[self.index[name]]["mesh"]]
        return {self.json["materials"][p["material"]]["name"] for p in mesh["primitives"]}

    def aft_extent(self):
        """기체 원점에서 가장 뒤(glTF +Z)까지 [m] — 조상까지 더한 노드 이동 + 메시 bbox 최대.
        조상 노드는 이동만 가진다고 본다. 프로펠러의 구운 회전은 z축 둘레라 z 최대를 안 바꾼다."""
        parent = {c: i for i, n in enumerate(self.nodes) for c in n.get("children", [])}
        best = -math.inf
        for i, n in enumerate(self.nodes):
            if "mesh" not in n:
                continue
            z, j = 0.0, i
            while j is not None:
                z += self.nodes[j].get("translation", [0.0, 0.0, 0.0])[2]
                j = parent.get(j)
            best = max(best, z + self.mesh_max(n["name"])[2])
        return best

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


@pytest.mark.parametrize("name", ["shahed136.glb", "shahed136_eoir.glb"])
def test_rudder_positive_moves_trailing_edge_to_port(name):
    # 규약 §5: 러더 + = TE left — 기수 12시로 내려다볼 때 뒷전이 4시 → 8시.
    # 데모 키 114에서 두 러더가 +22°다. 뒷전은 노드 로컬 후방(+Z). 여기서 rotation.y = −δr이
    # 나오고, 가상환경이 그것을 쓴다(web/world/src/core/surfaces.ts의 rudderRotationY).
    g = load(name)
    a = math.radians(22)
    for node in ("Rudder_L", "Rudder_R"):
        te = rotate(g.rotation_at(node, frame_time(114)), (0.0, 0.0, 1.0))
        assert te == pytest.approx((-math.sin(a), 0.0, math.cos(a)), abs=0.01)     # −X = 좌현


ENGINE_MATERIALS = {"Engine_Block", "Engine_Fins", "Engine_Copper", "Engine_Alloy",
                    "Engine_Wire", "Engine_Exhaust"}


@pytest.mark.parametrize("name", ["shahed136.glb", "shahed136_eoir.glb"])
def test_exposed_engine_and_wooden_propeller(name):
    # 참고 사진: 날개 뒷전 뒤로 드러난 수평대향 4기통(핀 달린 실린더·흡기 스택·구리 링기어·
    # 점화선·배기) + 나무 2엽 프로펠러와 알루미늄 허브. 칠이 빠지면 재질이 GLB에서 사라져 걸린다.
    g = load(name)
    assert g.parent_of("Engine") == "Fuselage"
    assert ENGINE_MATERIALS <= g.materials_of("Engine")
    assert {"Prop_Wood", "Engine_Alloy"} <= g.materials_of("Propeller")
    # 블레이드 끝 반경(로컬 블렌더 z → glTF y) — 종전 모델과 같은 0.45 m
    lo, hi = g.mesh_min("Propeller"), g.mesh_max("Propeller")
    assert max(-lo[1], hi[1]) == pytest.approx(0.45, abs=0.01)


@pytest.mark.parametrize("name", ["shahed136.glb", "shahed136_eoir.glb"])
def test_aft_extent_matches_launcher_constant(name):
    # web/world/src/core/launcher.ts의 VEHICLE_AFT_EXTENT(1.90 m)는 이 값을 손으로 옮긴 상수다 —
    # 기체를 발사관 안에 맞추는 데 쓴다. 꼬리를 바꿔 여기가 움직이면 그 상수도 같이 바꾼다.
    assert load(name).aft_extent() == pytest.approx(1.905, abs=0.002)


def test_eoir_is_drop_in_with_gimbal_nodes(eoir):
    missing = [n for n in VEHICLE_NODES + EOIR_NODES if n not in eoir.index]
    assert not missing
    assert eoir.parent_of("EOIR_Pan") == "Fuselage"
    assert eoir.parent_of("EOIR_Tilt") == "EOIR_Pan"
    assert "mesh" not in eoir.nodes[eoir.index["EOIR_Pan"]]     # 방위축은 형상 없는 엠프티


def _limit_values(axis_name, axis):
    """generate_shahed136.py의 `limit_rot(eoir[...], axis, lo, hi)` 값 — 리밋은 .blend에만 있어
    GLB에서 읽을 수 없으므로 소스에서 읽는다(여기 숫자를 따로 적으면 둘이 조용히 갈린다)."""
    with open(os.path.join(HERE, "generate_shahed136.py"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"limit_rot\(eoir\[\"%s\"\], '%s', (-?\d+), (-?\d+)\)" % (axis_name, axis), src)
    assert m, "%s 리밋 줄을 못 찾았다" % axis_name
    return int(m.group(1)), int(m.group(2))


def _nose_intrusion(points, pan, tilt):
    """자세 (pan, tilt)에서 헤드 점들이 원통 기수(28각형 r 0.119, y 1.29~1.46, 축 z −0.005) 안으로
    들어간 최대 깊이 [m]. 점은 블렌더 로컬(돔 중심 = 원통 끝 원판 중심 기준)이다."""
    a, t = math.radians(-pan), math.radians(tilt)
    ca, sa, ct, st = math.cos(a), math.sin(a), math.cos(t), math.sin(t)
    n = 28
    rin = 0.119 * math.cos(math.pi / n)
    worst = 0.0
    for x, y, z in points:
        y1, z1 = ct * y - st * z, st * y + ct * z                # Rx(tilt)
        wx, wy = ca * x - sa * y1, 1.46 + sa * x + ca * y1       # Rz(−pan) 뒤 돔 중심으로
        if not 1.29 < wy < 1.46:
            continue
        th = math.atan2(z1, wx) % (2 * math.pi)
        mid = (math.floor(th / (2 * math.pi / n)) + 0.5) * 2 * math.pi / n
        proj = math.hypot(wx, z1) * math.cos(th - mid)          # 그 변의 법선 방향 거리
        if proj < rin:
            worst = max(worst, min(1.46 - wy, rin - proj))
    return worst


def test_eoir_limits_keep_sensor_face_out_of_nose_cylinder(eoir):
    # 리밋 직사각형 안 어느 자세에서도 센서면 가장자리·가장자리 가까운 창이 원통 기수에 먹히지 않는다.
    # 먹힘은 경계 가까이서 나므로 경계 5° 띠는 1°, 안쪽은 5° 격자로 본다. 처음의 ±40은 여기서 걸린다.
    mesh = eoir.json["meshes"][eoir.nodes[eoir.index["EOIR_Tilt"]]["mesh"]]
    by_mat = {}
    for p in mesh["primitives"]:
        mat = eoir.json["materials"][p["material"]]["name"]
        by_mat.setdefault(mat, []).extend(                       # glTF → 블렌더 로컬
            (gx, -gz, gy) for gx, gy, gz in eoir.accessor(p["attributes"]["POSITION"]))
    # 센서면 = 하우징의 가장 앞 평면, 가장자리 반경은 그 평면 위 점에서 잰다 — 치수를 적어 두지 않는다
    face_y = max(y for _, y, _ in by_mat["EOIR_Housing"])
    rim = max(math.hypot(x, z) for x, y, z in by_mat["EOIR_Housing"] if y > face_y - 5e-4)
    pts = [(x, y, z) for mat, vs in by_mat.items() if mat != "EOIR_Seam"   # 이음매·리벳은 돔과 함께 숨는다
           for x, y, z in vs
           if math.hypot(x, z) > 0.7 * rim and (mat != "EOIR_Housing" or y > face_y - 5e-4)]
    assert pts
    z_lo, z_hi = _limit_values("pan", "z")                       # 로컬 Z 회전 = −pan
    p_lo, p_hi = -z_hi, -z_lo
    t_lo, t_hi = _limit_values("tilt", "x")
    poses = [(pan, tilt) for pan in range(p_lo, p_hi + 1) for tilt in range(t_lo, t_hi + 1)
             if (pan % 5 == 0 and tilt % 5 == 0) or pan < p_lo + 5 or pan > p_hi - 5
             or tilt < t_lo + 5 or tilt > t_hi - 5]
    worst, at = max((_nose_intrusion(pts, pan, tilt), (pan, tilt)) for pan, tilt in poses)
    assert worst == 0.0, "리밋 안 %s에서 센서면이 %.2f mm 먹힌다" % (at, worst * 1e3)


def test_eoir_replaces_nose_cone(eoir):
    # 총알형 기수: 원통 기수(동체)가 1.46에서 끝나고, 그 끝 원판 중심에 한 치 작은 헤드 돔이
    # 반구로 맞물린다. 돔 앞은 센서면으로 평평히 잘렸고(0.096) 창 테두리가 2.5 mm 솟으므로
    # 최전방은 1.46 + 0.0985 — 구 반경(0.1175)이 아니다.
    assert eoir.mesh_min("Fuselage")[2] == pytest.approx(-1.46, abs=0.002)
    pan = eoir.nodes[eoir.index["EOIR_Pan"]]
    assert pan["translation"][2] == pytest.approx(-1.46, abs=0.002)
    tilt_min = eoir.mesh_min("EOIR_Tilt")
    assert pan["translation"][2] + tilt_min[2] == pytest.approx(-1.5585, abs=0.001)


def test_eoir_head_has_photo_style_sensor_face(eoir):
    # 쓰이지 않는 재질 슬롯은 내보내기에서 빠진다 — 창·테두리가 하우징색으로 칠해지면 여기서 걸린다.
    # EO(파랑)·IR(검보라)·레이저(녹색) 창과 붉은 가스켓, 광학부, 패널 이음매가 모두 있어야 한다.
    assert {"EOIR_Housing", "EOIR_Gasket", "EOIR_Lens_EO", "EOIR_Lens_IR", "EOIR_Laser",
            "EOIR_Optics", "EOIR_Seam"} <= eoir.materials_of("EOIR_Tilt")


# 부호만이 아니라 축과 크기까지 — 이득이 두 배로 구워지거나 축이 바뀌어도 걸린다.
# 데모 키 프레임에서 잰다(구운 키가 프레임마다 있어 보간이 끼지 않는다).
@pytest.mark.parametrize("frame, pan_deg", [(72, 35), (30, -35)])
def test_eoir_pan_turns_boresight_about_up_axis(eoir, frame, pan_deg):
    a = math.radians(pan_deg)
    look = rotate(eoir.rotation_at("EOIR_Pan", frame_time(frame)), BORESIGHT)
    assert look == pytest.approx((math.sin(a), 0.0, -math.cos(a)), abs=0.01)   # + = 우현(+X)


def test_eoir_tilt_turns_boresight_about_lateral_axis(eoir):
    a = math.radians(-40)                                                       # 데모 키 138
    look = rotate(eoir.rotation_at("EOIR_Tilt", frame_time(138)), BORESIGHT)
    assert look == pytest.approx((0.0, math.sin(a), -math.cos(a)), abs=0.01)   # + = 위(+Y)
