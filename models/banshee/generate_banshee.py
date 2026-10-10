"""Banshee Jet 80+ — CLAW 가상환경용 GLB(`banshee.glb`)를 굽는다.

실행:  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P models/banshee/generate_banshee.py

형상은 `banshee_assembly.py`(분해·조립 리그가 있는 원본 모델 — 그 파일은 손대지 않는다)가 만들고,
이 스크립트는 그 결과를 **가상환경이 모는 규약**에 맞춰 내보내기만 한다. 규약 정본은 이 폴더의 README.

1. 축 — 원본은 기수 −Y·좌익 +X(블렌더)라 glTF로 내보내면 shahed와 180° 돌아 있다. 루트를 Z축으로 180°
   돌려 `models/shahed-136`과 같은 축(glTF 로컬 +X 우현·+Y 위·+Z 후방)으로 맞춘다. 원점은 그대로
   MAC 25 % 동체 축선이다(`web/world/src/core/modelaxes.ts`가 원점을 무게중심 근처로 본다).
2. 노드 이름 — three는 이름의 점을 지운다(`Jet80_Elevon_In.L` → `Jet80_Elevon_InL`). 모는 노드만
   shahed와 같은 이름(`Elevon_In_L` …)으로 바꾼다. 엘레본은 원본 그대로 로컬 +X 회전 = 뒷전 아래라
   이름만 바꾸면 `rotation.x = δ`가 맞는다.
3. 러더 — 원본은 로컬 +X 회전 = 뒷전 왼쪽인데, 가상환경은 러더를 `rotation.y = −δr`(로컬 +Y 회전 = 뒷전
   오른쪽)로 몬다. 힌지 프레임 밑에 `Rudder_Frame`(블렌더 로컬 Z를 힌지 −X로 눕힘) › `Rudder`(항등,
   **모는 노드**) 두 겹을 끼우고, 원본 메시는 자리 그대로 `Rudder` 밑에 매단다. 블렌더 로컬 Z가 glTF 로컬 Y다.
4. 구동 노드 선언 — 루트의 사용자 속성 `claw_drive_nodes`(쉼표 목록)가 glTF extras로 실리고, 가상환경이
   이 모델에서 기대할 노드를 그것으로 정한다. 단발 러더·프로펠러 없음(쌍발 제트)을 「못 찾은 노드」로
   잘못 말하지 않게 하는 자리다.

조립 애니메이션(`explode_anim`)은 싣지 않는다 — 가상환경은 클립을 재생하지 않고(`scene/models.ts`),
실은 바이트는 반입 꾸러미에 영구히 남는다(`models/README.md`).
"""
import math
import os
import sys

import bpy
from mathutils import Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # models/ — blender_numpy
sys.path.insert(0, HERE)                   # banshee_assembly

# 사유·증상·복구는 models/blender_numpy.py 참조. **bpy.ops 호출 전에** 부른다.
from blender_numpy import ensure_numpy  # noqa: E402

ensure_numpy(repo_root=os.path.dirname(os.path.dirname(HERE)))

import banshee_assembly as src  # noqa: E402

OUT_GLB = os.path.join(HERE, "banshee.glb")
OUT_BLEND = os.path.join(HERE, "banshee.blend")

PRE = src.JET["prefix"]  # "Jet80_"
ELEVONS = {  # 원본 이름 → 가상환경 노드 이름 (L = 기체 좌익)
    PRE + "Elevon_In.L": "Elevon_In_L",
    PRE + "Elevon_Out.L": "Elevon_Out_L",
    PRE + "Elevon_In.R": "Elevon_In_R",
    PRE + "Elevon_Out.R": "Elevon_Out_R",
}
DRIVE_NODES = (*ELEVONS.values(), "Rudder")

bpy.ops.wm.read_factory_settings(use_empty=True)
src.build_all()
root = bpy.data.objects[PRE + "ROOT"]
coll = bpy.data.collections[src.JET["collection"]]

# ---- 0. 조립 상태로 굳힌다 -----------------------------------------------------------------
# 분해 이동은 `delta_location` 드라이버(스크립트 식 — 백그라운드에서는 자동 실행 허용 여부에 따라 평가가
# 갈린다)와 타임라인 키가 정한다. 둘 다 걷어 내고 0에 둔다 — 내보내기가 실행 환경에 따라 분해도를 굽지 않게.
root.animation_data_clear()
root["explode"] = root["explode_anim"] = 0.0
for ob in coll.all_objects:
    if ob.animation_data:
        for fc in list(ob.animation_data.drivers):
            if fc.data_path == "delta_location":
                ob.animation_data.drivers.remove(fc)
    ob.delta_location = (0.0, 0.0, 0.0)
bpy.context.view_layer.update()

# ---- 1. 축: 루트를 Z로 180° — 기수 +Y, 우현 +X -------------------------------------------
root.location = (0.0, 0.0, 0.0)
root.rotation_euler = (0.0, 0.0, math.pi)

# ---- 2. 엘레본 이름 ----------------------------------------------------------------------
for old, new in ELEVONS.items():
    bpy.data.objects[old].name = new
    assert bpy.data.objects[new].name == new, f"이름 충돌: {new}"

# ---- 3. 러더: 힌지 › Rudder_Frame(눕힘) › Rudder(항등, 모는 노드) › 원본 메시 ------------------
bpy.context.view_layer.update()
hinge = bpy.data.objects[PRE + "Hinge_Rudder"]
mesh = bpy.data.objects[PRE + "Rudder"]
keep = mesh.matrix_world.copy()


def empty(name, parent, basis):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = "ARROWS"
    ob.empty_display_size = 0.08
    coll.objects.link(ob)
    ob.parent = parent
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.matrix_basis = basis
    return ob


# Ry(−90°): 로컬 Z → 힌지 −X. Rudder의 +Z 회전 = 원본 메시의 −X 회전 = 뒷전 오른쪽.
frame = empty("Rudder_Frame", hinge, Matrix.Rotation(-math.pi / 2, 4, "Y"))
drive = empty("Rudder", frame, Matrix.Identity(4))
bpy.context.view_layer.update()
mesh.parent = drive
mesh.matrix_parent_inverse = drive.matrix_world.inverted() @ keep @ mesh.matrix_basis.inverted()
bpy.context.view_layer.update()
err = max(abs(a - b) for ra, rb in zip(mesh.matrix_world, keep) for a, b in zip(ra, rb))
assert err < 1e-6, f"러더 메시가 움직였다: {err}"

# ---- 4. 구동 노드 선언 (glTF extras → three userData) ---------------------------------------
root["claw_drive_nodes"] = ",".join(DRIVE_NODES)

# ---- 내보내기 ------------------------------------------------------------------------------
# 장면 전체 — 빈 장면에서 시작해 이 기체만 있다. 선택으로 고르면 숨긴 오브젝트(힌지·링키지)가 빠진다.
bpy.ops.export_scene.gltf(
    filepath=OUT_GLB, export_format="GLB", use_selection=False,
    export_animations=False, export_apply=False, export_yup=True, export_extras=True,
)
bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)
print("[gen] exported", os.path.basename(OUT_GLB), "— drive nodes:", ", ".join(DRIVE_NODES))
