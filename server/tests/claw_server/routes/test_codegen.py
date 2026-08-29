"""탑재 제어법칙 C 생성 라우트 (02 §1·§2.2, M16).

여기서 지키는 것은 셋이다:
  ① 커밋된 산출물(`flight/gen/`)과 **같은 코드**가 나오는가 — 조립을 재현하지
     않는다는 계약의 실질. 서버가 자기 나름대로 조립하면 웹에 보이는 코드와
     FCC에 넘어가는 코드가 달라진다
  ② 편집한 파라미터가 실제로 생성 코드에 반영되는가
  ③ 구성 오류가 422로 나오는가 (판정은 엔진, 매핑만 서버)

C 코드의 정확성(비트 일치·컴파일)은 `flight/tests/test_parity.py` 소관이다.
"""

import re
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parents[4] / "flight" / "gen"


def _post(client, **over):
    return client.post("/api/codegen/flight", json=over)


def test_생성_결과가_커밋된_산출물과_같다(client):
    """기본 형상 = flight/gen/ 정본. 서버가 조립을 따로 재현하지 않는다는 증거."""
    r = _post(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["artifact"] == "fcl"
    assert body["dt"] == 0.01
    assert body["groups"] == ["sched", "ap", "lim", "scas", "mix"]

    files = {f["name"]: f["text"] for f in body["files"]}
    committed = {p.name: p.read_text(encoding="utf-8") for p in GEN_DIR.glob("*.[ch]")}
    for name, text in files.items():
        assert name in committed, f"{name}이 커밋 산출물에 없다"
        assert text == committed[name], (
            f"{name}이 커밋본과 다르다 — 서버가 다른 형상을 조립하고 있다"
        )
    # scas_yaw는 이 라우트의 산출물이 아니다(제어법칙 전체만) — 그 차이는 정상
    assert set(committed) - set(files) == {
        "scas_yaw.c", "scas_yaw.h", "scas_yaw_data.c", "scas_yaw_types.h",
    }


def test_읽는_순서를_서버가_정해_준다(client):
    """생성물이 12개다 — "어디부터 보나"가 곧 사용성이다."""
    files = _post(client).json()["files"]
    order = [f["name"] for f in files]
    assert order[:4] == ["fcl.h", "fcl_types.h", "fcl.c", "fcl_sched.h"]
    assert order[-2:] == ["claw_rt.h", "claw_rt.c"]
    # 서브시스템은 실행 순서대로, 짝은 .h 먼저
    parts = [n for n in order if n.startswith("fcl_") and "_types" not in n
             and "_data" not in n]
    assert parts == [
        "fcl_sched.h", "fcl_sched.c", "fcl_ap.h", "fcl_ap.c", "fcl_lim.h", "fcl_lim.c",
        "fcl_scas.h", "fcl_scas.c", "fcl_mix.h", "fcl_mix.c",
    ]
    roles = {f["name"]: f["role"] for f in files}
    assert roles["fcl.h"] == "진입점"
    assert roles["fcl.c"] == "조립부"
    assert roles["fcl_data.c"] == "파라미터 데이터"
    assert roles["claw_rt.c"] == "공용 런타임"
    assert all(f["lines"] > 0 for f in files)


def test_편집한_게인이_생성_코드에_박힌다(client):
    """웹에서 값을 고치는 목적 자체 — 안 박히면 이 화면은 장식이다."""
    base = _post(client).json()
    edited = _post(client, autopilot={"kp_alt": 0.008}).json()
    assert edited["fingerprint"] != base["fingerprint"], "값이 바뀌었는데 지문이 같다"

    def data_c(body):
        return next(f["text"] for f in body["files"] if f["name"] == "fcl_data.c")

    # _data.c는 필드명을 정렬 패딩한다 (생성 데이터도 리뷰 대상 문서라서)
    assigned = re.compile(r"\.ap_alt_pid_kp\s+= 0\.008,")
    assert assigned.search(data_c(edited)), "편집값이 파라미터 데이터에 없다"
    assert not assigned.search(data_c(base))
    # 값만 바뀌었으므로 구조 파일은 그대로여야 한다
    def top(body):
        return next(f["text"] for f in body["files"] if f["name"] == "fcl.c")

    assert top(edited) == top(base)


def test_편집한_scas가_생성_코드에_박힌다(client):
    """SCAS도 AP와 같은 계약 — 스케줄이 안 붙은 자리(요축)와 스케줄 대상이 아닌
    파라미터(washout_tau)가 탑재 C까지 내려가야 웹의 편집이 의미를 갖는다."""
    axes = {
        "pitch": {"kp": -2.0, "ki": -0.5, "k_rate": 0.4, "out_lo": -0.35, "out_hi": 0.35},
        "roll": {"kp": 1.0, "ki": 0.1, "k_rate": -0.2, "out_lo": -0.35, "out_hi": 0.35},
        "yaw": {"kp": 0.7, "ki": 0.0, "k_rate": 0.8, "washout_tau": 3.0,
                "out_lo": -0.35, "out_hi": 0.35},
    }
    base = _post(client).json()
    edited = _post(client, scas=axes).json()
    assert edited["fingerprint"] != base["fingerprint"], "값이 바뀌었는데 지문이 같다"

    def data_c(body):
        return next(f["text"] for f in body["files"] if f["name"] == "fcl_data.c")

    assert re.search(r"\.scas_yaw_pid_kp\s+= 0\.7,", data_c(edited))
    # 워시아웃 시정수는 상수가 아니라 dt로 구운 계수로 박힌다 (tau=3.0 주석이 근거)
    assert "tau=3.0 s" in data_c(edited)
    assert "tau=3.0 s" not in data_c(base)


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
    # 스케줄이 없으면 게인이 신호가 아니라 상수 파라미터가 된다
    scas = next(f["text"] for f in off["files"] if f["name"] == "fcl_scas.c")
    assert "prm->scas_pitch_pid_kp" in scas


def test_리미터를_끄면_출력도_줄어든다(client):
    off = _post(client, with_limiter=False).json()
    assert "lim" not in off["groups"]
    types = next(f["text"] for f in off["files"] if f["name"] == "fcl_types.h")
    assert "alpha_margin" not in types, "리미터를 껐는데 엔벨로프 출력이 남았다"


def test_제어주기가_이산계수를_바꾼다(client):
    """dt는 튜닝 파라미터가 아니라 형상의 일부 — 지문이 함께 움직여야 한다."""
    fast = _post(client, control_hz=200.0).json()
    slow = _post(client).json()
    assert fast["dt"] == 0.005
    assert fast["fingerprint"] != slow["fingerprint"]
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
    assert "sched_pitch_kp_kn" in files["fcl_data.c"], "구간 경계 배열이 없다"
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
