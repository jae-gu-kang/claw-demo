import pytest
import yaml

from claw.params import ComponentRegistry, ParamDef, ParamError, ParamSet, RegistryError

DEFS = [
    ParamDef("vehicle.mass.m0", 5000.0, "kg", "초기 총질량", lo=0.0),
    ParamDef("vehicle.geom.s_ref", 20.0, "m2", "기준 면적", lo=0.0),
    ParamDef("fcl.scas.pitch.kp", 1.2, "-", "피치 SCAS 비례게인"),
    ParamDef("fcl.rate_hz", 100, "Hz", "제어 주기", lo=1, hi=1000),
    ParamDef("fcl.alpha_limiter.on", True, "-", "α 리미터 사용"),
    ParamDef("guidance.path.algo", "los", "-", "경로추종 알고리즘", choices=("los", "l1", "vf")),
    ParamDef("vehicle.inertia.diag", [1000.0, 2000.0, 2500.0], "kg·m2", "관성 대각", lo=0.0),
]


def make_set(**overrides):
    return ParamSet(DEFS, overrides)


def test_defaults_applied():
    ps = make_set()
    assert ps["vehicle.mass.m0"] == 5000.0
    assert ps["guidance.path.algo"] == "los"
    assert ps["vehicle.inertia.diag"] == [1000.0, 2000.0, 2500.0]


def test_validation():
    ps = make_set()
    ps["fcl.scas.pitch.kp"] = 2.5
    assert ps["fcl.scas.pitch.kp"] == 2.5
    with pytest.raises(ParamError):
        ps["vehicle.mass.m0"] = -1.0  # 범위 위반
    with pytest.raises(ParamError):
        ps["fcl.rate_hz"] = 5000  # 상한 위반
    with pytest.raises(ParamError):
        ps["guidance.path.algo"] = "dijkstra"  # 허용값 외
    with pytest.raises(ParamError):
        ps["fcl.scas.pitch.kp"] = "high"  # 타입 오류
    with pytest.raises(ParamError):
        ps["no.such.param"] = 1.0  # 미정의


def test_fingerprint_stable_and_sensitive():
    a, b = make_set(), make_set()
    assert a.fingerprint() == b.fingerprint()  # 동일 스냅샷 → 동일 지문
    b["fcl.scas.pitch.kp"] = 1.3
    assert a.fingerprint() != b.fingerprint()  # 값 변경 → 지문 변경
    assert a.diff(b) == {"fcl.scas.pitch.kp": (1.2, 1.3)}


def test_copy_with_for_sweep():
    base = make_set()
    var = base.copy_with({"vehicle.mass.m0": 4500.0})
    assert base["vehicle.mass.m0"] == 5000.0  # 원본 불변
    assert var["vehicle.mass.m0"] == 4500.0
    assert base.diff(var) == {"vehicle.mass.m0": (5000.0, 4500.0)}


def test_yaml_round_trip(tmp_path):
    ps = make_set()
    ps["fcl.scas.pitch.kp"] = 1.7
    p = tmp_path / "params.yaml"
    ps.save_yaml(p)

    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert raw["vehicle"]["mass"]["m0"] == 5000.0  # 중첩 맵 저장 (사람 편집 친화)

    loaded = ParamSet.load_yaml(p, DEFS)
    assert loaded.as_dict() == ps.as_dict()
    assert loaded.fingerprint() == ps.fingerprint()  # 지문 보존


def test_yaml_unknown_key_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("vehicle:\n  mass:\n    m0: 100.0\n    typo_key: 1.0\n", encoding="utf-8")
    with pytest.raises(ParamError):
        ParamSet.load_yaml(p, DEFS)


def test_json_schema():
    schema = make_set().to_json_schema(title="claw-params")
    props = schema["properties"]
    assert schema["additionalProperties"] is False
    assert props["vehicle.mass.m0"]["minimum"] == 0.0
    assert "kg" in props["vehicle.mass.m0"]["description"]
    assert props["guidance.path.algo"]["enum"] == ["los", "l1", "vf"]
    assert props["fcl.alpha_limiter.on"]["type"] == "boolean"
    assert props["vehicle.inertia.diag"]["type"] == "array"


def test_duplicate_def_rejected():
    with pytest.raises(ParamError):
        ParamSet([DEFS[0], DEFS[0]])


def test_registry():
    reg = ComponentRegistry()
    defs = [ParamDef("lookahead", 500.0, "m", "선견 거리", lo=1.0)]
    reg.register("path_following", "los", lambda ps: ("los", ps.as_dict()), defs)

    assert reg.names("path_following") == ["los"]
    kind, params = reg.create("path_following", "los", {"lookahead": 800.0})
    assert kind == "los" and params["lookahead"] == 800.0

    schema = reg.schema("path_following", "los")
    assert schema["title"] == "path_following/los"
    assert schema["properties"]["lookahead"]["minimum"] == 1.0

    with pytest.raises(RegistryError):
        reg.register("path_following", "los", lambda ps: None)  # 중복 등록
    with pytest.raises(RegistryError):
        reg.create("path_following", "l1")  # 미등록
    assert reg.names("nonexistent") == []
