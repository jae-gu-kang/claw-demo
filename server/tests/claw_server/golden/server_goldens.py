"""예제 기체(구 데모) 서버 응답 골든 — 프로파일 이관 전 HEAD에서 굳힌다 (02 §5.6).

라우트가 make_demo_*를 직접 부르던 것을 프로파일 해석기로 바꿔도 **응답이 바이트 단위로
같아야** 한다(키 순서 포함 — hexjson이 dict 순서를 보존한다). 항목마다 (client, wait)를 받아
값을 돌려주는 함수이고, 저장본은 profile_example/*.json이다.

긴 시계열은 조각별 sha256 + 표본으로 줄인다(shrink). 실행마다 달라지는 키(경과 시간)는
VOLATILE로 뺀다 — 캡처가 두 번 계산해 결정론을 확인하므로 새 휘발 키는 거기서 드러난다.
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "engine/claw/tests/golden"))

import hexjson  # noqa: E402

VOLATILE = {"elapsed_ms"}
LONG = 50


def _strip(x):
    """휘발 키만 뺀다 — 긴 목록 원소 안쪽에도 적용한다(요약하기 전에)."""
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def shrink(x):
    if isinstance(x, dict):
        return {k: shrink(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        if len(x) > LONG:
            return {"__digest__": hexjson.digest(_strip(x))}
        return [shrink(v) for v in x]
    return x


def _get(client, url):
    r = client.get(url)
    assert r.status_code == 200, r.text
    return r.json()


def _job(client, wait, url, body, timeout=300.0):
    r = client.post(url, json=body)
    assert r.status_code == 202, r.text
    j = wait(r.json()["id"], timeout=timeout)
    assert j["status"] == "done", j
    return _get(client, f"/api/results/{j['result_id']}")


def vn_envelope(client, wait):
    return {
        "default": _get(client, "/api/analysis/vn-envelope?alt=1000&fuel=200"),
        "override": _get(client, "/api/analysis/vn-envelope?alt=3000&fuel=400&alpha_margin=0"
                                 "&n_limit_pos=5&mach_d=0.85"),
    }


def design_envelope(client, wait):
    return {
        "default": _get(client, "/api/analysis/design-envelope?fuel=200"),
        "full": _get(client, "/api/analysis/design-envelope?fuel=300&q_max=20000&alt_min=0"
                             "&alt_max=9000&nz=3&iso_tas=100,200&mach_margin=1.2&n_limit_neg=-2"),
    }


def gains(client, wait):
    return {"catalog": _get(client, "/api/gains/catalog"),
            "demo": _get(client, "/api/gains/demo")}


def trim_batch(client, wait):
    cases = [{"mach": m, "alt": 1000.0, "fuel": 200.0} for m in (0.40, 0.45, 0.50, 0.6, 0.7)]
    return _job(client, wait, "/api/trim/batch", {"cases": cases, "fingerprint": "fp-golden"})


def envelope_scan(client, wait):
    cases = [
        {"name": "ok0", "mach": 0.3, "alt": 1000.0, "fuel": 200.0},
        {"name": "ok1", "mach": 0.45, "alt": 1000.0, "fuel": 200.0},
        {"name": "slow", "mach": 0.12, "alt": 1000.0, "fuel": 200.0},
        {"name": "fast", "mach": 0.605, "alt": 1000.0, "fuel": 200.0},
    ]
    return _job(client, wait, "/api/analysis/design-envelope-scan",
                {"cases": cases, "fingerprint": "fp-env"})


def margin_map(client, wait):
    return _job(client, wait, "/api/analysis/margin-map", {
        "cases": [{"mach": m, "alt": 1000.0, "fuel": 200.0} for m in (0.35, 0.4, 0.45)],
        "loops": [{"name": "pitch_q", "axis": "lon", "x_out": "q", "u_in": "de",
                   "kp": 0.5, "ki": 0.8}],
        "fingerprint": "fp-mm",
    })


def sim_hold(client, wait):
    return _job(client, wait, "/api/sim/run", {
        "trim": {"name": "design", "mach": 0.45, "alt": 1000.0, "fuel": 200.0},
        "modes": [{"name": "climb", "speed": 140.0, "alt": 1050.0, "heading": 0.2,
                   "exit": ["alt_ge", 1045.0], "next": "cruise"},
                  {"name": "cruise", "speed": 140.0, "alt": 1050.0, "heading": 0.2,
                   "exit": ["time_ge", 1e9]}],
        "t_end": 10.0,
        "fingerprint": "fp-sim-golden",
    })


def sim_landing(client, wait):
    return _job(client, wait, "/api/sim/run", {
        "trim": {"mach": 0.0, "alt": 0.0, "fuel": 300.0, "condition": "ground"},
        "runway": {"elevation": 0.0, "heading": 0.0, "length": 1500.0},
        "launch": {"length": 10.0, "elev_angle": math.radians(15.0), "exit_speed": 81.5},
        "nav": {"seed": 11},
        "nav_grade": "rtk",
        "modes": [
            {"name": "launch", "speed": 110.0, "pitch": math.radians(21.0),
             "heading": 0.0, "exit": ["off_rail"], "next": "climb"},
            {"name": "climb", "speed": 110.0, "pitch": math.radians(21.0),
             "heading": 0.0, "exit": ["alt_ge", 250.0], "next": "cruise"},
            {"name": "cruise", "speed": 88.0, "alt": 300.0, "heading": 0.0,
             "exit": ["time_ge", 1e9]},
        ],
        "t_end": 30.0, "dt_plant": 0.01, "control_hz": 100.0,
        "actuators": {"wn": 30.0, "zeta": 0.7, "rate_max": 10.0},
        "fuel_flow": 0.3,
        "fingerprint": "fp-landing-golden",
    }, timeout=600.0)


def influence_structural(client, wait):
    r = client.post("/api/influence/structural", json={})
    assert r.status_code == 200, r.text
    return r.json()


def influence_openloop(client, wait):
    return _job(client, wait, "/api/influence/openloop", {
        "cases": [{"name": "c45", "mach": 0.45, "alt": 1000.0, "fuel": 200.0}],
        "params": ["table.pitch.k_rate", "fcl/ScasAxis.pitch.kp"],
        "fingerprint": "fp-ol",
    })


def influence_sweep(client, wait):
    return _job(client, wait, "/api/influence/sweep", {
        "cases": [{"name": "c45", "mach": 0.45, "alt": 1000.0, "fuel": 200.0}],
        "knobs": ["table.pitch.kp"], "span": [0.1],
        "t_settle": 2.0, "t_step": 4.0,
    }, timeout=600.0)


GOLDENS = {
    "vn_envelope": vn_envelope,
    "design_envelope": design_envelope,
    "gains": gains,
    "trim_batch": trim_batch,
    "envelope_scan": envelope_scan,
    "margin_map": margin_map,
    "sim_hold": sim_hold,
    "sim_landing": sim_landing,
    "influence_structural": influence_structural,
    "influence_openloop": influence_openloop,
    "influence_sweep": influence_sweep,
}
