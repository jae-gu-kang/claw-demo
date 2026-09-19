"""탑재 제어법칙 C 생성 라우트 (02 §1 · 07 §4, M16).

여기서 지키는 것은 셋이다:
  ① 산출물 정본 경로(`flight/generate.py`)와 **같은 코드**가 나오는가 — 조립을 재현하지
     않는다는 계약의 실질. 서버가 자기 나름대로 조립하면 웹에 보이는 코드와
     FCC에 넘어가는 코드가 달라진다. 커밋본(`flight/gen/`)과 정본 경로의 일치는
     `flight/tests/test_parity.py` 몫이다 — 서버 테스트는 예제 자리에 회귀 픽스처를 두므로
     커밋본(제품 예제)과 직접 비교하지 않고 같은 예제로 정본 경로를 돌려 비교한다
  ② 편집한 파라미터가 실제로 생성 코드에 반영되는가
  ③ 구성 오류가 422로 나오는가 (판정은 엔진, 매핑만 서버)

C 코드의 정확성(비트 일치·컴파일)은 `flight/tests/test_parity.py` 소관이다.
"""

import importlib.util
import re
from pathlib import Path

GENERATE = Path(__file__).resolve().parents[4] / "flight" / "generate.py"


def _generated():
    """flight/generate.py build() — 지금 예제 자리의 문서로 정본 경로를 돌린 {파일: 내용}."""
    spec = importlib.util.spec_from_file_location("flight_generate", GENERATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build()


def _post(client, **over):
    return client.post("/api/codegen/flight", json=over)


def test_생성_결과가_flight_generate_산출물과_같다(client):
    """기본 형상 = flight/generate.py 정본 경로. 서버가 조립을 따로 재현하지 않는다는 증거."""
    r = _post(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["artifact"] == "fcl"
    assert body["dt"] == 0.01
    assert body["groups"] == ["sched", "ap", "lim", "scas", "mix"]

    files = {f["name"]: f["text"] for f in body["files"]}
    committed = _generated()
    for name, text in files.items():
        assert name in committed, f"{name}이 generate.py 산출물에 없다"
        assert text == committed[name], (
            f"{name}이 generate.py 산출물과 다르다 — 서버가 다른 형상을 조립하고 있다"
        )
    # scas_yaw는 이 라우트의 산출물이 아니다(제어법칙 전체만) — 그 차이는 정상
    assert set(committed) - set(files) == {
        "scas_yaw.c", "scas_yaw.h", "scas_yaw_params.c", "scas_yaw_params.h", "scas_yaw_types.h",
    }
    # 이미지도 정본 경로(generate.image_for)와 같다 — 같은 기체·같은 값·같은 계보
    import base64

    from claw.profile import example_profile

    spec = importlib.util.spec_from_file_location("flight_generate_image", GENERATE)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert base64.b64decode(body["param_image"]["base64"]) == gen.image_for(example_profile())[1]
    assert body["param_image"]["name"] == "example-delta.bin"


def test_읽는_순서를_서버가_정해_준다(client):
    """생성물이 12개다 — "어디부터 보나"가 곧 사용성이다."""
    files = _post(client).json()["files"]
    order = [f["name"] for f in files]
    assert order[:4] == ["fcl.h", "fcl_types.h", "fcl.c", "fcl_sched.h"]
    assert order[-2:] == ["claw_rt.h", "claw_rt.c"]
    # 서브시스템은 실행 순서대로, 짝은 .h 먼저
    parts = [n for n in order if n.startswith("fcl_") and "_types" not in n
             and "_params" not in n]
    assert parts == [
        "fcl_sched.h", "fcl_sched.c", "fcl_ap.h", "fcl_ap.c", "fcl_lim.h", "fcl_lim.c",
        "fcl_scas.h", "fcl_scas.c", "fcl_mix.h", "fcl_mix.c",
    ]
    roles = {f["name"]: f["role"] for f in files}
    assert roles["fcl.h"] == "진입점"
    assert roles["fcl.c"] == "조립부"
    assert roles["fcl_params.c"] == "파라미터 로더"
    assert order[-4:-2] == ["fcl_params.h", "fcl_params.c"]  # 로더는 서브시스템 뒤, 공용 런타임 앞
    assert roles["claw_rt.c"] == "공용 런타임"
    assert all(f["lines"] > 0 for f in files)


def test_편집한_게인은_C가_아니라_이미지에_박힌다(client):
    """웹에서 값을 고치는 목적 자체 — 값이 이미지에 실려야 하고, C 파일은 한 바이트도 안 바뀌어야 한다(v1.12)."""
    base = _post(client).json()
    edited = _post(client, autopilot={"kp_alt": 0.008}).json()
    assert edited["files"] == base["files"], "값만 바꿨는데 C가 달라졌다"
    assert edited["structure_fingerprint"] == base["structure_fingerprint"]
    assert edited["param_fingerprint"] != base["param_fingerprint"], "값이 바뀌었는데 파라미터 지문이 같다"
    # 표준 템플릿에서 고도 kp는 1점 표 자리다 — 목록의 그 표 값이 편집값이다
    listing = edited["param_image"]["listing"]
    assert re.search(r"sched_alt_kp — 절점 표 n = 1\n    bp  = [^\n]*\n    val = 0\.008\n", listing), listing[:2000]
    assert "val = 0.008\n" not in base["param_image"]["listing"]


def test_편집한_scas가_이미지에_박힌다(client):
    """SCAS도 AP와 같은 계약 — 스케줄이 안 붙은 자리(요축)와 스케줄 대상이 아닌
    파라미터(washout_tau)가 이미지까지 내려가야 웹의 편집이 의미를 갖는다."""
    import math

    axes = {
        "pitch": {"kp": -2.0, "ki": -0.5, "k_rate": 0.4, "out_lo": -0.35, "out_hi": 0.35},
        "roll": {"kp": 1.0, "ki": 0.1, "k_rate": -0.2, "out_lo": -0.35, "out_hi": 0.35},
        "yaw": {"kp": 0.7, "ki": 0.0, "k_rate": 0.8, "washout_tau": 3.0,
                "out_lo": -0.35, "out_hi": 0.35},
    }
    base = _post(client).json()
    edited = _post(client, scas=axes).json()
    assert edited["files"] == base["files"]
    assert edited["param_fingerprint"] != base["param_fingerprint"], "값이 바뀌었는데 지문이 같다"
    listing = edited["param_image"]["listing"]
    assert re.search(r"sched_yaw_kp — 절점 표 n = 1\n    bp  = [^\n]*\n    val = 0\.7\n", listing)
    # 워시아웃 시정수는 dt로 계산한 계수로 실린다
    assert f"scas_yaw_wo_p" in listing and repr(math.exp(-0.01 / 3.0)) in listing
    assert repr(math.exp(-0.01 / 3.0)) not in base["param_image"]["listing"]


def test_형상_변형은_C를_그대로_두고_이미지만_바꾼다(client):
    """EO/IR형은 질량·관성만 바꾸는 변형이다 — 탑재 C·구조 지문·법칙 값(파라미터 지문)이 기본형과 같고, 이미지는 계보
    칸(프로파일 지문)만 다르다. 기체가 바뀌어도 코드는 그대로라는 v1.12 목표 상태의 서버 쪽 증명."""
    import base64

    from claw.profile import load_shipped_example

    # 서버 테스트는 예제 자리에 구 기체 픽스처를 두므로(conftest) 제품 예제를 사본으로 올려 그 형상 변형을 쓴다
    d = load_shipped_example()
    d.update(id="shipped-delta-variant", name="제품 예제 사본", is_example=False)
    assert client.post("/api/profiles", json={"document": d}).status_code == 201
    base = _post(client, profile={"id": "shipped-delta-variant"}).json()
    eoir = _post(client, profile={"id": "shipped-delta-variant", "variant": "eoir"}).json()
    assert eoir["files"] == base["files"]
    assert eoir["structure_fingerprint"] == base["structure_fingerprint"]
    assert eoir["param_fingerprint"] == base["param_fingerprint"]
    assert base64.b64decode(eoir["param_image"]["base64"]) != base64.b64decode(base["param_image"]["base64"])
    assert eoir["param_image"]["name"] == "shipped-delta-variant-eoir.bin"


def test_scas_부분_주입은_422(client):
    """세 축 전부가 계약 — sim 라우트와 같은 사유로 막힌다 (build_scas 공유)."""
    r = _post(client, scas={"pitch": {"kp": -2.0}})
    assert r.status_code == 422 and "세 축 전부 필요" in r.text


def test_스케줄을_끄면_구조가_바뀐다(client):
    """게인 스케줄 유무가 구조에 드러난다 — 파일 하나가 통째로 사라진다."""
    off = _post(client, with_schedule=False).json()
    assert "sched" not in off["groups"]
    names = {f["name"] for f in off["files"]}
    assert "fcl_sched.c" not in names
    # 스케줄이 없으면 게인이 신호가 아니라 상수 파라미터가 된다 — 명시 구조 옵션이라 구조 지문이 움직인다
    scas = next(f["text"] for f in off["files"] if f["name"] == "fcl_scas.c")
    assert "prm->scas_pitch_pid_kp" in scas
    assert off["structure_fingerprint"] != _post(client).json()["structure_fingerprint"]


def test_리미터를_끄면_출력도_줄어든다(client):
    off = _post(client, with_limiter=False).json()
    assert "lim" not in off["groups"]
    types = next(f["text"] for f in off["files"] if f["name"] == "fcl_types.h")
    assert "alpha_margin" not in types, "리미터를 껐는데 엔벨로프 출력이 남았다"
    assert off["structure_fingerprint"] != _post(client).json()["structure_fingerprint"]


def test_제어주기가_이산계수를_바꾼다(client):
    """dt는 튜닝 파라미터가 아니라 형상의 일부 — 구조 지문(DT 매크로)과 이미지 값(이산 계수)이 함께 움직인다."""
    fast = _post(client, control_hz=200.0).json()
    slow = _post(client).json()
    assert fast["dt"] == 0.005
    assert fast["structure_fingerprint"] != slow["structure_fingerprint"]
    assert fast["param_fingerprint"] != slow["param_fingerprint"]
    types = next(f["text"] for f in fast["files"] if f["name"] == "fcl_types.h")
    assert "#define FCL_DT 0.005" in types


def test_미정의_게인_키는_422(client):
    r = _post(client, gain_tables={
        "pitch.nope": {"axes": {"mach": [0.2, 0.8]}, "data": [1.0, 2.0]},
    })
    assert r.status_code == 422
    # 무엇이 허용인지까지 말해 준다 — 자리 정본은 엔진 SCHEDULABLE이다
    detail = str(r.json()["detail"])
    assert "스케줄 불가 게인" in detail and "k_rate" in detail


def test_범위를_벗어난_ap_파라미터는_422(client):
    """판정은 엔진 ParamDef — 서버가 범위를 다시 적지 않는다."""
    r = _post(client, autopilot={"nonexistent_gain": 1.0})
    assert r.status_code == 422


def test_비유한값은_서버가_막는다(client):
    """NaN은 ParamDef 범위 비교를 조용히 통과하므로 경계에서 차단한다."""
    r = client.post(
        "/api/codegen/flight",
        content='{"autopilot": {"kp_alt": NaN}}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422


def test_다항_게인_스케줄이_생성_코드에_박힌다(client):
    """kind='poly' 태그 페이로드(01 §3.4 다항 런타임) — claw_polyeval1d 경로 방출."""
    poly = {
        "kind": "poly",
        "axis": "mach",
        "segments": [
            {"x0": 0.15, "x1": 0.3, "coeffs": [-8.0, 0.0], "c": 0.225, "h": 0.075},
            {"x0": 0.3, "x1": 0.95, "coeffs": [-3.0, 2.0, -0.5], "c": 0.625, "h": 0.325},
        ],
    }
    r = _post(client, gain_tables={"pitch.kp": poly})
    assert r.status_code == 200, r.text
    files = {f["name"]: f["text"] for f in r.json()["files"]}
    assert "claw_polyeval1d" in files["fcl_sched.c"], "다항 평가 호출이 없다"
    assert "claw_polyeval1d" in files["claw_rt.c"], "공용 런타임에 다항 헬퍼가 없다"
    assert "sched_pitch_kp — 다항 표" in r.json()["param_image"]["listing"], "구간 경계 배열이 이미지에 없다"
    # 절점 표 대 다항 표는 명시 구조 옵션이다 — 구조 지문이 움직인다
    assert r.json()["structure_fingerprint"] != _post(client).json()["structure_fingerprint"]
    # 기존 테이블 페이로드(kind 없음)와 혼재 가능 — 태그드 유니언 하위호환
    table = {"axes": {"mach": [0.15, 0.95]}, "data": [1.0, 0.5]}
    r2 = _post(client, gain_tables={"pitch.kp": poly, "roll.kp": table})
    assert r2.status_code == 200, r2.text
    sched2 = next(f["text"] for f in r2.json()["files"] if f["name"] == "fcl_sched.c")
    assert "claw_polyeval1d" in sched2 and "claw_lookup1d" in sched2


def test_다항_구간_불연속은_422(client):
    poly = {
        "kind": "poly", "axis": "mach",
        "segments": [
            {"x0": 0.15, "x1": 0.3, "coeffs": [1.0], "c": 0.2, "h": 0.1},
            {"x0": 0.4, "x1": 0.95, "coeffs": [1.0], "c": 0.6, "h": 0.3},  # 0.3→0.4 갭
        ],
    }
    r = _post(client, gain_tables={"pitch.kp": poly})
    assert r.status_code == 422
    assert "불연속" in r.text


def test_부분_자동조종_지정은_이_기체의_설계값_위에_덧댄다(client):
    """안 보낸 경로 게인은 기체 설계값 그대로여야 한다 — ParamDef 기본값(구 합성 기체의 설계값)으로 채우면 200 kg급
    기체의 승강률 게인이 0.196 → 0.08로 조용히 바뀐다(v1.10 리뷰, 시뮬 라우트도 같은 규칙). 설계값과 같은 값 하나만
    보내면 안 보낸 것과 바이트 동일해야 한다."""
    from claw.profile import load_shipped_example

    d = load_shipped_example()
    d.update(id="shipped-delta-codegen", name="제품 예제 사본", is_example=False, variants=[])
    assert client.post("/api/profiles", json={"document": d}).status_code == 201
    ref = {"id": "shipped-delta-codegen"}
    base = _post(client, profile=ref)
    part = _post(client, profile=ref, autopilot={"kp_alt": d["law"]["design"]["autopilot"]["kp_alt"]})
    assert base.status_code == 200 and part.status_code == 200, part.text
    assert part.json()["files"] == base.json()["files"]
    assert part.json()["param_fingerprint"] == base.json()["param_fingerprint"]
    listing = part.json()["param_image"]["listing"]
    assert re.search(r"ap_vs_pid_kp\s+= 0\.196\b", listing), "승강률 게인이 기체 설계값이 아니다"


def test_unseeded_aircraft_flight_code_is_a_422_with_the_document_path(client, unseeded_doc):
    """게인 미설계 기체의 탑재 C 생성은 422 — detail {path, message} (웹 안내 링크 근거)."""
    assert client.post("/api/profiles", json={"document": unseeded_doc("no-gains-cg")}).status_code == 201
    r = client.post("/api/codegen/flight", json={"profile": {"id": "no-gains-cg"}})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["path"] == "/law/design", r.text
