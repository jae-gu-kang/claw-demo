"""브리핑 가지치기 — LLM에 보내는 결과 본문의 크기·정직성 계약.

결과 본문은 종류마다 세 자릿수 배 차이가 난다(sim 최대 54MB — 실측). 여기서
지키는 것:
  ① 작은 본문은 한 글자도 안 바뀐다 (판정 행 5~9개짜리 배열이 잘리면 안 된다 —
     head-N 절단은 verify summary 5행·카드 7장을 소리 없이 먹는다)
  ② 큰 노드는 배열이든 dict든 같은 규칙으로 표본화되고, **자른 사실이 데이터
     안에 남는다**(_n·_omitted) — 브리핑이 "전부 봤다"고 말하지 못하게
  ③ 배제 경로(sim 시계열·verify 소스 동봉)는 통째로 마커가 되고, 같은 부모의
     판정 스칼라는 산다
  ④ 구조 dict(키 22개, 값 이질)는 키를 안 자른다 — 케이스명 키 dict(값 동질)만
     표본화한다. auto_design 최상위가 전자, margin_out.cases가 후자다
  ⑤ 별난 값 통과 — 400자리 int(auto_design budget 리터럴 실측)·"inf" 문자열
"""

import json

from claw_server.brief import KEEP_WHOLE_BYTES, prune


def _size(node) -> int:
    return len(json.dumps(node, ensure_ascii=False))


def test_작은_본문은_한_글자도_안_바뀐다():
    body = {
        "kind": "verify_flight",
        "summary": [{"key": f"k{i}", "label": "라벨 — 문장", "status": "pass",
                     "detail": "판정 상세 문장"} for i in range(7)],
        "verdict": "pass",
    }
    assert _size(body) < KEEP_WHOLE_BYTES  # 전제 — 판정 묶음은 경계 아래여야 한다
    assert prune(body, "unknown_kind") == body


def test_큰_배열은_표본과_생략_수로_말한다():
    rows = [{"case": f"c{i}", "value": "x" * 120} for i in range(200)]
    out = prune({"rows": rows}, "unknown")
    s = out["rows"]
    assert s["_n"] == 200
    assert s["_omitted"] == 195
    assert len(s["_sample"]) == 5
    assert s["_sample"][0]["case"] == "c0"


def test_케이스명_키_dict도_배열과_같은_규칙이다():
    # margin_map/auto_design의 벌크는 배열이 아니라 케이스명 키 dict다 (실측)
    cases = {f"M{i}": {"pm": 40 + i, "note": "y" * 200} for i in range(24)}
    out = prune({"cases": cases}, "unknown")
    s = out["cases"]
    assert s["_n"] == 24
    assert s["_omitted"] == 19
    assert len(s["_sample"]) == 5
    assert "M0" in s["_sample"]


def test_구조_dict는_키를_안_자른다_값만_줄인다():
    # auto_design 최상위(키 22개, 값 이질)를 본뜬다 — 여기서 키를 표본화하면
    # report·status 같은 판정이 사라진다. 큰 값 하나만 줄어야 한다
    body = {f"field{i}": f"v{i}" for i in range(20)}
    body["status"] = "converged"
    body["big"] = [{"row": i, "pad": "z" * 100} for i in range(500)]
    out = prune(body, "unknown")
    assert out["status"] == "converged"
    assert set(body) == set(out)  # 키 전부 생존
    assert out["big"]["_n"] == 500  # 큰 값만 표본화


def test_긴_문자열은_절단_사실을_함께_남긴다():
    # 4KB 이하 노드는 통째 유지가 계약이라(총량 유계) 절단은 예산을 넘는
    # 노드 안에서만 일어난다 — 6000자면 감싼 dict가 경계를 넘어 재귀에 들어간다
    out = prune({"note": "가" * 6000}, "unknown")
    assert out["note"].startswith("가" * 400)
    assert "5600자 생략" in out["note"]


def test_sim_배제_경로_시계열은_마커가_되고_판정_스칼라는_산다():
    body = {
        "kind": "sim",
        "t": list(range(40000)),
        "signals": {f"s{i}": list(range(1000)) for i in range(80)},
        "envelope": {
            "stall_margin": list(range(40000)),
            "flags": {"alpha": [0] * 40000},
            "worst_margin": 0.12,
            "any_flag": False,
        },
        "meta": {"phases": {"touchdown_t": 96.9}},
    }
    out = prune(body, "sim")
    assert isinstance(out["t"], str) and "제외" in out["t"]
    assert isinstance(out["signals"], str) and "제외" in out["signals"]
    assert isinstance(out["envelope"]["stall_margin"], str)
    assert isinstance(out["envelope"]["flags"], str)
    assert out["envelope"]["worst_margin"] == 0.12  # 판정 스칼라 생존
    assert out["meta"]["phases"]["touchdown_t"] == 96.9
    assert _size(out) < 4000  # 54MB급 본문이 프롬프트 예산 안으로


def test_verify는_소스_동봉을_빼고_판정_요약을_남긴다():
    body = {
        "kind": "verify_flight",
        "report": {
            "verdict": "pass",
            "summary": [{"key": "equiv", "status": "pass"}],
            "files": [{"name": f"f{i}.c", "text": "int x;\n" * 2000}
                      for i in range(16)],
        },
    }
    out = prune(body, "verify_flight")
    assert isinstance(out["report"]["files"], str) and "제외" in out["report"]["files"]
    assert out["report"]["verdict"] == "pass"
    assert out["report"]["summary"][0]["key"] == "equiv"


def test_모르는_kind는_일반_가지치기만_탄다():
    body = {"kind": "future_kind", "huge": ["x"] * 10000, "verdict": "ok"}
    out = prune(body, "future_kind")
    assert out["verdict"] == "ok"
    assert out["huge"]["_n"] == 10000


def test_별난_값이_안_터진다_거대_int와_inf_문자열():
    # auto_design config.budget_tune_evals가 400자리 int 리터럴이다 (실측 —
    # float 변환을 시도한 프로토타입이 OverflowError로 죽었다)
    body = {"budget": int("9" * 400), "gm": "inf", "pm": "-inf"}
    out = prune(body, "unknown")
    assert out["budget"] == int("9" * 400)
    assert out["gm"] == "inf"
    json.dumps(out)  # 직렬화 가능해야 한다


def test_표본은_판정상_나쁜_항목을_먼저_담는다():
    """앞 5개 고정이면 뒤쪽의 유일한 fail이 표본에서 빠진다 (리뷰 실측 — 이름
    붙은 체크 dict가 4KB를 넘는 순간 마지막 fail 항목이 조용히 생략됐다).
    _omitted가 정직하게 남긴 하지만, 소견서가 그 fail을 인용할 수 없게 된다."""
    checks = {f"check{i}": {"status": "ok", "note": "정상 판정 문장 " + "x" * 600}
              for i in range(9)}
    checks["actuator_sat"] = {"status": "fail", "note": "포화 3.2 s " + "x" * 600}
    out = prune({"checks": checks}, "unknown")
    assert out["checks"]["_n"] == 10
    assert "actuator_sat" in out["checks"]["_sample"]  # fail이 표본에 들어온다

    # 배열도 같은 규칙 — converged:false 케이스가 뒤에 있어도 표본에 담긴다
    rows = [{"case": f"c{i}", "converged": True, "pad": "y" * 500}
            for i in range(30)]
    rows[25] = {"case": "c25", "converged": False, "pad": "y" * 500}
    out2 = prune({"rows": rows}, "unknown")
    sampled_cases = [r["case"] for r in out2["rows"]["_sample"]]
    assert "c25" in sampled_cases


def test_표본_안의_큰_노드도_재귀로_줄어든다():
    # evaluate cases[*].stages(케이스당 7KB)가 표본에 들어와도 그 안이 또 준다
    big_case = {"stages": {f"st{i}": {"pad": "w" * 900} for i in range(11)},
                "name": "c0"}
    rows = [dict(big_case, name=f"c{i}") for i in range(30)]
    out = prune({"cases": rows}, "unknown")
    sampled = out["cases"]["_sample"][0]
    assert sampled["name"] == "c0"
    assert sampled["stages"]["_n"] == 11  # 안쪽 동질 dict도 표본화됐다
