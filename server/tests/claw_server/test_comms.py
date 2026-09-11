"""교신 비행 로그 추출 — sim 결과 → LLM에 실을 유계 로그의 계약.

여기서 지키는 것:
  ① 유계성 — 2만 스텝급 런도 로그가 4KB 예산 안이다 (이 기능의 본체)
  ② 정직성 — phases가 null이면 그 이벤트를 **내지 않는다**(0으로 위장 금지),
     표본을 솎은 사실은 _n/_omitted/_stride 마커로 데이터에 남는다
  ③ 사고 규약 승계 — 접지 수치는 meta.phases 값만 쓴다(신호 재계산 금지 —
     stride 솎임이 −0.98을 −0.74로 보이게 한 웹 replay.js 사고), 뜬 플래그는
     이름별로(any_flag로 뭉개면 기준면 이탈이 DB 이탈로 오독)
  ④ 결측 내성 — None·"inf" 문자열(serialize 정책)이 섞여도 안 터진다
"""

import json
import math

from claw_server.comms import LOG_BUDGET, flight_log


def _sim(n=200, dt=0.5, with_phases=True):
    """완주 착륙 런의 축소 재현 — launch → cruise → flare 3구간."""
    t = [round(i * dt, 2) for i in range(n)]
    third = n // 3
    modes = (["launch"] * third + ["cruise"] * third
             + ["flare"] * (n - 2 * third))
    sig = {
        "mode": modes,
        "h": [float(i % 300) for i in range(n)],
        "V": [80.0 + (i % 10) for i in range(n)],
        "hdot": [1.0] * n,
        "theta": [0.1] * n,
        "phi": [0.0] * n,
        "launch_gx": [330.0 if i < 3 else 0.0 for i in range(n)],
        "limiter_active": [third <= i < third + 5 for i in range(n)],
    }
    phases = ({"launch_exit_t": t[2], "touchdown_t": t[n - 20],
               "stop_t": t[n - 2], "td_sink_rate": -0.92, "td_speed": 79.5}
              if with_phases
              else {"launch_exit_t": None, "touchdown_t": None, "stop_t": None,
                    "td_sink_rate": None, "td_speed": None})
    return {
        "kind": "sim",
        "t": t,
        "signals": sig,
        "envelope": {
            "stall_margin": [0.3] * n,
            "flags": {"alpha": [False] * n,
                      "altitude": [i == 50 for i in range(n)]},
            "worst_margin": 0.08, "worst_margin_t": t[70],
            "min_alt": 0.5, "min_alt_t": t[n - 19],
            "any_flag": True, "first_flag_t": t[50],
        },
        "meta": {
            "case": "cruise88", "t_end": t[-1], "nav": "NavErrorModel",
            "aborted": None,
            "runway": {"elevation": 0.0, "heading": 0.05964, "length": 1205.0},
            "launch": {"length": 10.0, "elev_angle": 0.2618, "exit_speed": 81.5},
            "origin": {"lat": 34.601303, "lon": 127.212067},
            "waypoints": [[2596.0, 155.0], [3294.0, 197.0]],
            "accept_radius": 100.0,
            "phases": phases,
        },
        "n_total": n,
    }


def test_로그가_예산_안이다_2만_스텝에서도():
    log = flight_log(_sim(n=20000, dt=0.01))
    raw = json.dumps(log, ensure_ascii=False)
    assert len(raw) <= LOG_BUDGET, f"{len(raw)}B — 예산 초과"
    # 자른 사실이 데이터에 남는다
    assert log["samples"]["_n"] == 20000
    assert log["samples"]["_omitted"] > 0


def test_모드_채터링에서도_예산이_지켜진다():
    """두 모드가 프레임마다 번갈아 드는 런(한계 접근 채터링 — 이 기능이 가장
    필요한 종류의 런)에서 스팬이 2만 개가 된다. 균등 표본만 줄여서는 modes
    행과 스팬 강제 포함이 예산을 1.9MB까지 뚫었다(리뷰 재현) — 스팬·전이도
    예산 루프의 축소 대상이어야 한다."""
    body = _sim(n=20000, dt=0.01)
    body["signals"]["mode"] = ["approach" if i % 2 else "flare"
                               for i in range(20000)]
    log = flight_log(body)
    raw = json.dumps(log, ensure_ascii=False)
    assert len(raw) <= LOG_BUDGET, f"{len(raw)}B — 예산 초과"
    # 잘랐다는 사실이 modes에 마커로 남는다 (조용한 절단 금지)
    assert any(isinstance(m, dict) and "_omitted_spans" in m for m in log["modes"])
    # 전이 생략 note는 설명 대상보다 먼저 오지 않는다 — 목록 끝에 선다
    notes = [i for i, e in enumerate(log["events"]) if e.get("kind") == "note"]
    assert notes and notes[-1] == len(log["events"]) - 1


def test_t가_신호보다_짧아도_안_터진다():
    """엔진 산출은 정합적이지만 '결측 내성' 선언의 빈틈 — t가 비어도 신호가
    길어도 IndexError가 사유 없는 트레이스백으로 새면 안 된다 (리뷰 지적)."""
    log = flight_log({"kind": "sim", "t": [],
                      "signals": {"mode": ["a", "b"], "h": [1.0, 2.0]},
                      "envelope": {}, "meta": {}})
    assert log["modes"] == []
    assert log["samples"]["rows"] == []
    body = _sim()
    body["signals"]["mode"] = body["signals"]["mode"] + ["extra"] * 30  # 신호가 t보다 길다
    out = flight_log(body)
    json.dumps(out, ensure_ascii=False)  # 그냥 돌아야 한다
    assert all(m.get("mode") != "extra" for m in out["modes"])  # t 밖 구간은 없다


def test_구간과_전이_이벤트가_모드_문자열에서_나온다():
    log = flight_log(_sim())
    assert [m["mode"] for m in log["modes"]] == ["launch", "cruise", "flare"]
    trans = [e for e in log["events"] if e["kind"] == "mode"]
    assert [e["note"] for e in trans] == ["launch → cruise", "cruise → flare"]
    # 구간 양끝 시각이 t에서 왔다
    assert log["modes"][0]["t0"] == 0.0


def test_접지_수치는_phases_값만_쓴다():
    body = _sim()
    log = flight_log(body)
    td = next(e for e in log["events"] if e["kind"] == "touchdown")
    assert td["sink_rate"] == -0.92  # 신호 재계산이 아니라 phases 그대로
    assert td["speed"] == 79.5
    assert td["t"] == body["meta"]["phases"]["touchdown_t"]
    assert any(e["kind"] == "stop" for e in log["events"])
    assert any(e["kind"] == "launch_exit" for e in log["events"])


def test_phases가_null이면_그_이벤트를_내지_않는다():
    log = flight_log(_sim(with_phases=False))
    kinds = {e["kind"] for e in log["events"]}
    assert "touchdown" not in kinds  # 0초 접지로 위장하지 않는다
    assert "stop" not in kinds
    assert "launch_exit" not in kinds


def test_뜬_플래그만_이름과_첫_시각으로_남는다():
    log = flight_log(_sim())
    flags = [e for e in log["events"] if e["kind"] == "flag"]
    assert [f["name"] for f in flags] == ["altitude"]  # alpha는 안 떴다
    assert flags[0]["t"] == 25.0  # i=50, dt=0.5


def test_리미터는_배열이_아니라_구간이다():
    log = flight_log(_sim())
    lim = [e for e in log["events"] if e["kind"] == "limiter"]
    assert len(lim) == 1
    assert lim[0]["t1"] > lim[0]["t0"]


def test_리미터_구간도_자르면_말한다():
    """스팬 상한(10) 초과 절단이 조용하면 안 된다 — 전이 생략 note와 같은 규약
    (최종 확인 리뷰 지적: 이 조각만 계약 밖에 남아 있었다)."""
    body = _sim()
    lim = [False] * len(body["t"])
    for k in range(12):  # 한 표본짜리 참 구간 12개 — 상한 10을 넘긴다
        lim[k * 10] = True
    body["signals"]["limiter_active"] = lim
    log = flight_log(body)
    assert len([e for e in log["events"] if e.get("kind") == "limiter"]) == 10
    assert any(e.get("kind") == "note" and "리미터 구간 2건 생략" in e["note"]
               for e in log["events"])


def test_모드_경계가_표본에_강제_포함된다():
    log = flight_log(_sim(n=20000, dt=0.01))
    ti = log["samples"]["fields"].index("t")
    ts = {row[ti] for row in log["samples"]["rows"]}
    for span in log["modes"]:  # 짧은 구간이 균등 stride에서 통째로 빠지면 안 된다
        assert span["t0"] in ts, f"{span['mode']} 시작이 표본에 없다"


def test_결측과_inf_문자열이_안_터진다():
    body = _sim()
    body["signals"]["h"][3] = None
    body["signals"]["V"][4] = "inf"
    body["envelope"]["worst_margin"] = "-inf"
    log = flight_log(body)
    json.dumps(log, ensure_ascii=False)  # 직렬화 가능
    assert log["envelope"]["worst_margin"] == "-inf"  # 값 위장 없이 그대로


def test_run_정보에_null_필드는_담지_않는다():
    body = _sim()
    body["meta"]["runway"] = None
    body["meta"]["aborted"] = "cancelled"
    log = flight_log(body)
    assert "runway" not in log["run"]
    assert log["run"]["aborted"] == "cancelled"  # 중단은 반드시 실린다
    assert log["run"]["waypoints_n"] == 2


def test_활주로가_있으면_접지에_축방향_횡편차가_붙는다():
    body = _sim()
    n = len(body["t"])
    body["signals"]["pn"] = [float(i) * 10 for i in range(n)]
    body["signals"]["pe"] = [1.0] * n
    log = flight_log(body)
    td = next(e for e in log["events"] if e["kind"] == "touchdown")
    assert "along" in td and "cross" in td
    assert math.isfinite(td["along"]) and math.isfinite(td["cross"])
