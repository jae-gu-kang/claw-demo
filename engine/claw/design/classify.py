"""마진 부족 원인 분류기 — 4-verdict, 판정마다 수치 evidence 동반 (diagnose.py Finding 관례).

마진이 부족할 때 "breakpoint만 추가"가 아니라 **원인별로 다른 처방**을 낸다
(사용자 요구의 핵심). 실패 검증점 v·자리에 대해 순서대로:

1. structural_limit — v에서 튜너(tune_point — 자유 게인 국소 최적)를 돌려도
   **합격선**(criteria) 미달이거나 **그 자리의 설계가 성립하지 않았다**
   (SLOT_DESIGN_FAILED — 넷 다 안정한 게인은 내지만 목표대로 성형하지 못한 것이다)
   → 게인·
   breakpoint로는 불가 (게이트는 _slot_passes 한 곳에만 있다).
   action=escalate (**보고 전용** — 필터·작동기 대역폭·지연 예산 등 상위 설계
   변경은 어느 모드에서도 자동 적용하지 않는다). evidence로 교차 주파수 vs
   작동기 대역폭 비·지연 위상 기여에 더해 **완화 프로브**(_relief_probes —
   지연·작동기 대역폭을 하나씩 풀어 재튜닝하고 통과하면 이분으로 **최소 완화량**
   까지 실측)를 동봉한다: 자동 적용은 안 해도 "무엇을 얼마로 바꾸면 통과하는가"
   까지는 기계가 답해야 사람이 판단할 수 있다.
2. plant_variation — v를 낀 인접 앵커 간 model_distance.d_total > tol_plant
   (refine tol과 **같은 상수** — 기준 이원화 금지) → 트림 격자가 플랜트 변화를
   못 담는 것. action=promote v→anchor (검증 시 트림·선형화는 이미 완료 — 역할
   승격 후 TUNE부터 재실행). valley도 동시 성립하면 anchor가 상위 집합 처방이라
   이쪽을 택하고 note로 병기.
3. gain_interp_valley — 최적 게인은 통과 ∧ 보간 게인과의 괴리 > tol_gain ∧ 이웃
   breakpoint 자체는 통과 → 보간이 범인. action=promote v→breakpoint (최적
   게인을 그 점의 값으로) + FIT 국소 재실행. 단 v가 **앵커**면 얘기가 다르다 → 3′.
3′. fit_residual — 앵커에서의 보간 괴리. TUNE이 매 이터레이션 그 점의 자유 게인
   최적을 샘플에 넣으므로 격자가 성긴 게 아니라 적합이 그 점을 못 지나간 것이다.
   action=tighten_fit (허용치를 조이고 구간 수를 늘린다). 종전에는 이 경우도
   refit_at으로 냈는데, 앵커의 최적 게인을 샘플에 "고정"하는 것은 이미 그 값이
   샘플이라 **구조적으로 무효**였다 — applied로 기록되고 이터 예산만 태웠다.
4. simple_deficit — 나머지. 미달 폭이 히스테리시스 밴드 내면 좁은 골 가능성 —
   action=add_validation (v 좌우 중점 2개). 지속·확대되면 다음 이터레이션에서
   1~3으로 자연 재분류된다.
"""

import math

from claw.design.linmodels import model_distance
from claw.design.points import ROLE_ANCHOR, ROLE_BREAKPOINT, ROLE_RANK
from claw.design.schedmap import scheduled_gains
from claw.design.tune import TuneTargets, tune_point

# 그 자리의 **설계가 성립하지 않은** 사유 목록 — 구조 한계 게이트의 절반이다.
# tune.py의 목록을 import해서만 쓴다: 여기 손으로 옮겨 적으면 사유가 하나 늘 때
# 두 모듈의 판정이 조용히 갈린다
from claw.design.tune import SLOT_DESIGN_FAILED

VERDICTS = ("simple_deficit", "plant_variation", "gain_interp_valley", "structural_limit",
            "gain_sign_flip", "fit_residual")

# 자리(루프) → 관련 게인 슬롯 — valley 괴리·breakpoint 승격 값의 대상
LOOP_SLOTS = {
    "pitch_att": ("pitch.kp", "pitch.ki"),
    "pitch_rate": ("pitch.k_rate",),
    "roll_att": ("roll.kp", "roll.ki"),
    "roll_rate": ("roll.k_rate",),
    "yaw_rate": ("yaw.k_rate",),
}
_EPS = 1e-12
# 구조 한계 완화 프로브의 작동기 대역폭 배수. 데모 30 rad/s → 90 rad/s로, docs -01 §7
# 백로그가 적어 둔 소멸 경계(wn ≥ 50 rad/s)를 넘는 값이라 "대역폭이 병목인가"에 답한다.
_RELIEF_ACT_FACTOR = 3.0
_RELIEF_BISECT_N = 8  # 최소 완화량 이분 반복 — 브래킷 폭의 2^-8 = 1/256 정밀도
# 완화 축별 표시 정보 — 임계값의 향(≥/≤)·단위·화면 문장. 이분은 늘 **통과 쪽 끝**을
# 돌려주므로 방향은 언제나 "이 값이면 통과한다"로 읽힌다 (반올림이 안전한 쪽으로만).
_RELIEF_AXES = {
    "actuator_wn": {"name": "min_actuator_wn", "unit": "rad/s", "direction": ">=",
                    "text": "작동기 대역폭 ≥ {value:.3g} rad/s면 통과 (현재 {current:.3g})"},
    "delay_s": {"name": "max_delay_s", "unit": "s", "direction": "<=",
                "text": "지연 ≤ {value:.3g} s면 통과 (현재 {current:.3g})"},
}
# 자리 종류별 "달성 수치" 키 — 완화 전/후를 **같은 키로** 비교하기 위한 목록.
# achieved를 통째로 실으면 자리마다 모양이 달라 화면이 전후 비교를 그리지 못한다.
_ACHIEVED_KEYS = {
    "att": ("pm_deg", "gm_db", "wc_att", "wc0"),
    "pitch_rate": ("zeta_sp", "target"),
    "yaw_rate": ("zeta_dr", "target"),
    "roll_rate": ("roll_lambda", "target", "unstable", "participation"),
}


def _slot_passes(tune_out, loop_name, criteria) -> bool:
    """이 자리가 구조 한계를 **벗어났나** — 게이트·완화 프로브·이분 술어의 유일한 정의.

    둘 중 하나라도 걸리면 구조 한계다 (이 함수는 그 부정이다):
    - 자유 게인 최적의 판정이 fail — **합격선**(criteria)에조차 못 미친다.
    - 자리 사유가 **그 자리의 설계가 성립하지 않은** 축이다 (tune의 SLOT_DESIGN_FAILED:
      no_stable_gain·degenerate·margin_floor·bandwidth_collapse).

    종전 게이트는 `slot["status"] == "infeasible" or judged == "fail"`이었는데, 자리
    status는 **TuneTargets**(설계 목표 ζ_dr 0.5·PM 50°) 기준이고 judged는
    **MarginCriteria**(합격선 ζ 0.30·PM 45°) 기준이라 **서로 다른 자 둘을 OR로** 묶었다.
    그 간격은 히스테리시스로 일부러 둔 것인데 게이트가 그걸 결함으로 읽었다: 데모
    M0.6/h1000 yaw_rate를 ζ_dr 목표 0.95로 돌리면 달성 0.923(합격선 0.30의 3배)인데도
    reason=target_unreached라 escalate(적용 버튼 없는 처방)로 갔고, 한 카드 안에서
    evidence["tuned"]["judged"] == "ok"와 verdict가 서로를 부정했다.
    target_unreached·capped는 "설계 목표엔 못 갔으나 합격선은 통과"라 구조 한계가
    아니다 — evidence["tuned"]에는 그대로 실어 보내고(사용자는 알아야 한다) verdict는
    아래 분기(plant_variation / valley / fit_residual / simple_deficit)로 흘린다.

    자리 단위인 것도 판정의 일부다: 점 단위로 재면 이 자리를 고친 완화도 다른 축이
    못 따라오면 "해소 안 됨"으로 보고된다.
    """
    if _tuned_judgement(tune_out, loop_name, criteria) == "fail":
        return False
    return tune_out["slots"].get(loop_name, {}).get("reason") not in SLOT_DESIGN_FAILED


def _achieved_digest(tune_out, loop_name) -> dict | None:
    """튜닝 결과에서 이 자리의 달성 수치만 추린다 — 잴 것이 없으면 None."""
    if tune_out is None:
        return None
    ach = (tune_out.get("achieved") or {}).get(loop_name)
    if not ach:
        return None
    keys = _ACHIEVED_KEYS.get("att" if loop_name.endswith("_att") else loop_name, ())
    return {k: ach[k] for k in keys if k in ach}


def _min_relief(lm, design_base, loop_name, *, targets, criteria, act_kw, key,
                pass_value) -> tuple:
    """통과하는 **최소 완화량** — 고정 8회 이분, (통과 쪽 끝, 미달 쪽 끝)을 낸다.

    브래킷은 [현재값, 완화값]으로 시작한다. 양 끝은 이미 실측돼 있다: 현재값은
    structural_limit 게이트가 미달로, 완화값은 프로브가 통과로 판정한 값이다.
    술어는 그 게이트와 **같은 함수**(_slot_passes)라 "이분이 찾은 경계"와 "구조 한계
    경계"가 정의상 같은 선이다.

    **단조성 전제**: 작동기 대역폭은 클수록, 지연은 작을수록 유리하다. 물리적으로
    완전한 단조는 아니다 — 백오프·구제 마무리가 계단을 만들고, 작동기 공진이 특정
    대역에서 되레 마진을 깎는다 (실측: M0.6/h1000 pitch_att에서 wn 18은 미달인데 10은
    통과). 그래서 반환값은 "이 값에서 통과함을 실측했다"로만 읽어야 하고, 늘 **통과 쪽
    끝**을 돌려준다 — 오차가 안전한 방향으로만 생긴다. 미달 쪽 끝을 함께 내는 것은
    그 정밀도(구간 폭 = 초기 폭의 1/256)를 화면이 숨기지 않게 하기 위해서다.

    비용은 튜닝 8회다. tune_point 1회는 자리에 따라 크게 다르다 — 구제 마무리
    (_polish_att)가 도는 점은 ~270 ms, 안 도는 점은 ~35 ms(실측). 두 축이 모두
    해소되면 이분만 16회라 (점, 자리)당 최악 ~4.3초가 더 붙는다. 구조 한계는 드물어
    전체 실행에는 거의 영향이 없지만, 한 점이 통째로 구조 한계인 실행에서는 보인다.
    """
    bad, good = float(act_kw[key]), float(pass_value)
    for _ in range(_RELIEF_BISECT_N):
        mid = 0.5 * (bad + good)
        kw = dict(act_kw)
        kw[key] = mid
        if _slot_passes(tune_point(lm, design_base, targets=targets, **kw),
                        loop_name, criteria):
            good = mid
        else:
            bad = mid
    return good, bad


def _relief_probes(lm, design_base, loop_name, *, targets, criteria, act_kw,
                   base_out=None) -> list:
    """지연·작동기 대역폭을 하나씩만 완화해 재튜닝 — 병목 지목의 실측 근거.

    structural_limit는 "게인으로는 안 된다"까지만 말한다. 그다음 질문인 "그럼 무엇을
    바꾸나"는 상위 설계 결정이라 자동 적용하지 않지만, **판단 재료는 기계가 낼 수
    있다**. 종전 evidence는 ωc/작동기 비와 지연 위상 두 수치뿐이었는데 그 둘은 같이
    커지므로(둘 다 ωc에 비례) 어느 쪽이 병목인지 화면에서 읽어낼 수 없었다.
    프로브는 한 번에 하나씩만 바꿔 돌려 인과를 분리한다.

    각 항목은 세 가지를 낸다:
    - `resolves` — 그 완화로 구조 한계를 벗어나는가 (게이트와 **같은 함수**).
    - `achieved.before/after` — 완화 전후 달성 수치. 종전에는 프로브가 튜닝을 통째로
      한 번 더 돌리고 `out["achieved"]`를 버렸다: "지연을 빼면 PM 31° → 58°"를
      계산해 놓고 폐기한 것이다. 자리 종류에 맞는 키만 골라 같은 모양으로 싣는다.
    - `threshold` — resolves일 때만. 이분으로 잰 **최소 완화량**이다. "×3이면 통과"는
      예산이 아니다 (docs -01 §7 백로그 "작동기 대역폭 요구 사양 미도출"이 묻는 것은
      배수가 아니라 rad/s 값이다).

    비용은 구조 한계로 판정된 (점, 자리)당 튜닝 2회 + 해소된 축마다 8회다 — 최악
    18회. 1회가 ~35 ms(구제 마무리 없음)~270 ms(있음)라 최악 ~4.9초가 (점, 자리)당
    더 든다. 구조 한계는 드물다는 전제 위의 값이다.
    """
    act_wn = float(act_kw.get("actuator_wn") or 0.0)
    delay = float(act_kw.get("delay_s") or 0.0)
    plan = []
    if delay > 0.0:  # 이미 0이면 "지연을 빼 보라"가 답이 될 수 없다
        plan.append(("delay_s", 0.0, "지연 제거"))
    if act_wn > 0.0:
        plan.append(("actuator_wn", act_wn * _RELIEF_ACT_FACTOR,
                     f"작동기 대역폭 ×{_RELIEF_ACT_FACTOR:g}"))
    before = _achieved_digest(base_out, loop_name)
    probes = []
    for key, to_value, label in plan:
        kw = dict(act_kw)
        kw[key] = to_value
        out = tune_point(lm, design_base, targets=targets, **kw)
        slot = out["slots"].get(loop_name, {})
        # 구조 한계 게이트가 더 이상 성립하지 않으면 해소다 — 같은 함수를 부른다.
        # 식을 두 곳에 적으면 한쪽만 바뀐 날 프로브가 거짓 안도를 준다
        resolves = _slot_passes(out, loop_name, criteria)
        probe = {
            "change": key, "label": label, "from": act_kw.get(key), "to": to_value,
            "status": slot.get("status"), "reason": slot.get("reason"),
            "judged": _tuned_judgement(out, loop_name, criteria),
            "resolves": resolves,
            "achieved": {"before": before, "after": _achieved_digest(out, loop_name)},
        }
        if resolves:
            value, fail_at = _min_relief(
                lm, design_base, loop_name, targets=targets, criteria=criteria,
                act_kw=act_kw, key=key, pass_value=to_value,
            )
            spec = _RELIEF_AXES[key]
            current = float(act_kw[key])
            probe["threshold"] = {
                "name": spec["name"], "value": value, "unit": spec["unit"],
                "direction": spec["direction"], "current": current,
                "probe_value": to_value,
                # 통과/미달 양 끝 — 이 폭이 곧 실측 정밀도다 (초기 브래킷의 1/256)
                "bracket": [value, fail_at], "iterations": _RELIEF_BISECT_N,
                "text": spec["text"].format(value=value, current=current),
            }
        probes.append(probe)
    return probes


_LABEL = {"pm_deg": ("PM", "°"), "gm_db": ("GM", " dB"), "zeta": ("ζ", ""),
          "zeta_sp": ("ζ_sp", ""), "zeta_dr": ("ζ_dr", ""), "roll_lambda": ("λ", " rad/s")}
# λ의 히스테리시스만 절대값이 아니라 요구선 비율이다 [기본값] — λ 요구는 실행마다
# 다른 튜닝 목표에서 오므로(criteria.shortfall) 고정 폭이 뜻을 갖지 못한다.
_LAM_HYST_FRAC = 0.10


def _deficit_note(shortfall, hyst_pm, hyst_gm, hyst_zeta) -> str | None:
    """부족이 히스테리시스 밴드를 넘은 지표를 한 줄로 — 넘은 게 없으면 None.

    종전에는 PM만 봤다: GM 부족은 criteria가 계산해 놓고도 버려졌고(그래서 GM만
    모자란 점은 밴드를 아무리 넘어도 "지속 시 재분류" 경고가 안 붙었다), ζ는 헬퍼를
    안 거쳐 제 식으로 뺐다. 셋 다 같은 자로 재고 **넘은 것을 모두** 적는다 —
    한 자리에서 두 지표가 동시에 모자란 것이 흔하다.
    """
    bands = {"pm_deg": hyst_pm, "gm_db": hyst_gm,
             "zeta": hyst_zeta, "zeta_sp": hyst_zeta, "zeta_dr": hyst_zeta}
    over = []
    for key, rec in shortfall.items():
        band = bands.get(key)
        if band is None and key == "roll_lambda":
            band = _LAM_HYST_FRAC * rec["required"]
        if band is None or rec["deficit"] is None or rec["deficit"] <= band:
            continue
        label, unit = _LABEL.get(key, (key, ""))
        over.append(f"{label} 부족 {rec['deficit']:.3g}{unit} (밴드 {band:.3g})")
    if not over:
        return None
    return " · ".join(over) + " — 히스테리시스 초과, 지속 시 재분류 예상"


def _tuned_judgement(tune_out, loop_name, criteria) -> str:
    """v에서의 자유 게인 최적 결과 판정 — 자리 종류에 맞는 자로 잰다."""
    ach = tune_out["achieved"].get(loop_name)
    if ach is None:
        return "na"
    if loop_name.endswith("_att"):
        if "pm_deg" not in ach:
            return "na"
        return criteria.judge(ach)
    if loop_name == "roll_rate":
        # 롤은 감쇠가 아니라 대역폭이다. 종전에는 여기서도 zeta_dr을 찾았는데 롤
        # achieved에는 그 키가 없어 **항상 "na"**였다 — 롤이 실패해도 분류가 안 됐다
        if "roll_lambda" not in ach or not ach.get("target"):
            return "na"
        return criteria.judge_bandwidth(ach["roll_lambda"], ach["target"],
                                        unstable=bool(ach.get("unstable")),
                                        participation=ach.get("participation"))
    key = "zeta_sp" if loop_name == "pitch_rate" else "zeta_dr"
    if key not in ach:
        return "na"
    return criteria.judge_damping(ach[key])


def _first_finite(*values):
    """첫 유한 실수 — 없으면 **None**.

    `a or b`로 쓸 수 없다: **nan은 파이썬에서 truthy**라 폴백을 그대로 통과한다.
    교차가 없는 자리는 wcp가 nan이고(마진맵이 그렇게 낸다), 그게 새면 두 병목 수치가
    함께 nan이 되어 화면에서 사라진다.

    그렇다고 0.0으로 메우면 **더 나쁘다**. 이 값은 `wcp/actuator_wn`과
    `degrees(wcp·delay)`의 재료인데, 0.0이 들어가면 "작동기 여유 무한 · 지연이 위상을
    하나도 안 깎음" — **가능한 최선값**이 된다. 병목을 지목하라고 만든 두 수가
    "병목 아님"을 단정하는 셈이다. None이면 직렬화가 null로 내고 화면은 "—"로
    적는다 (`wc_over_actuator`가 작동기 인자 없을 때 이미 None을 내는 규약과 같다).
    """
    for v in values:
        if v is None:
            continue
        f = float(v)
        if math.isfinite(f):
            return f
    return None


def classify_margin_deficit(
    aircraft, v_name, loop_name, points, lms, trims, tables, design, margin_cases, *,
    criteria, design_base=None, targets=None, tol_plant=0.25, tol_gain=0.10,
    hysteresis_pm=5.0, hysteresis_gm=1.0, hysteresis_zeta=0.10,
    actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
) -> dict:
    """실패 (검증점, 자리) 하나의 원인 분류 — {"verdict", "action", "evidence"}.

    design vs design_base — **두 개가 필요하다**:
    - `design`은 실효 설계값(오케스트레이터의 `{**손설계, **적합 상수}`)이고,
      보간 게인 비교(`scheduled_gains`)의 기준이다.
    - `design_base`는 **손설계 정본**이고, 튜너가 부호와 탐색 브래킷을 잡는 값이다
      (`tune_point`은 design에서 그 둘만 읽는다: 브래킷 = 4×|k_design|).

    둘을 하나로 쓰면 자유 게인 최적이 적합 결과에 끌려간다. 실측(데모 M0.3/h1000,
    같은 플랜트·같은 목표, design만 다름): 손설계 브래킷은 roll.k_rate −0.592로
    λ 12.00을 달성하는데, 적합이 −0.05로 접힌 값을 브래킷으로 쓰면 −0.200(정확히
    천장 4×0.05)에서 λ 4.22로 끝난다 — **4.6배 틀린 g_opt**가 valley 괴리 계산과
    승격 게인에 그대로 들어간다. 상수가 0.0이면 그 자리는 아예 건너뛰고 0.0을
    "최적"이라 낸다.

    생략하면 design을 쓴다 (직접 호출·테스트 편의 — 오케스트레이터는 늘 넘긴다).
    """
    targets = targets if targets is not None else TuneTargets()
    design_base = design if design_base is None else design_base
    tr = trims[v_name]
    lm = lms.get(aircraft, tr)
    entry = margin_cases[v_name]["loops"][loop_name]
    evidence: dict = {
        "current": {k: entry.get(k) for k in
                    ("pm_deg", "gm_db", "zeta", "roll_lambda", "wcg", "wcp",
                     "orientation", "status")},
        # 요구 대비 부족을 **모든 verdict에** 싣는다 — 종전엔 simple_deficit의 note
        # 문자열로만 잠깐 쓰이고 버려져, 화면이 "현재 PM 38.2°"만 말하고 요구선도
        # 부족량도 못 냈다
        "shortfall": criteria.shortfall(entry),
    }

    # 0) 부호 뒤집힘 — 원인이 이미 확정된 경우다. 격자도 보간 valley도 아니고
    #    **적합이 설계 부호를 넘긴 것**이라, 앵커를 늘려도 다항이 다시 0을 가로지른다
    #    (실제로 겪었다: roll.ki 승격 처방을 반영해도 실패가 그대로였다).
    #    적합 단계의 부호 가드(fit._fit_preserving_sign)가 먼저 막지만, 상수 폴백까지
    #    실패했거나 API로 직접 주입된 다항이면 여기로 온다
    if entry.get("sign_flip"):
        tune_out = tune_point(
            lm, design_base, targets=targets,
            actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
            delay_s=delay_s, pade_order=pade_order,
        )
        slots = LOOP_SLOTS.get(loop_name, ())
        evidence["sign_flip"] = {
            "slots": entry["sign_flip"],
            "effective": {s: eff for s, eff in (entry.get("gains") or {}).items()},
            "design": {s: design.get(s) for s in slots},
        }
        return {
            "verdict": "gain_sign_flip",
            "action": {
                "type": "refit_at", "point": v_name,
                "gains": {s: tune_out["gains"][s] for s in slots if s in tune_out["gains"]},
                "note": "부호를 지키도록 그 점을 고정해 재적합 — 승격으로는 해결되지 않는다",
            },
            "evidence": evidence,
        }

    # 1) 자유 게인 국소 최적 — structural_limit 판별의 근거
    tune_out = tune_point(
        lm, design_base, targets=targets,
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
    )
    tuned_status = _tuned_judgement(tune_out, loop_name, criteria)
    slot = tune_out["slots"].get(loop_name, {})
    evidence["tuned"] = {
        # **자리 단위** status다. 점 단위(tune_out["status"])를 쓰면 같은 점의 다른
        # 축이 실패했을 때 이 자리까지 구조 한계로 끌려간다 — 실행 가능한 처방
        # (승격·재적합)이 적용 버튼 없는 에스컬레이션으로 바뀐다
        "status": slot.get("status"), "reason": slot.get("reason"),
        "point_status": tune_out["status"],  # 참고용 — 판정에는 안 쓴다
        "judged": tuned_status, "target": slot.get("target"),
        "achieved": tune_out["achieved"].get(loop_name), "notes": tune_out["notes"],
    }
    if not _slot_passes(tune_out, loop_name, criteria):
        wcp = _first_finite(entry.get("wcp"), entry.get("wc"))
        relief = _relief_probes(
            lm, design_base, loop_name, targets=targets, criteria=criteria,
            act_kw=dict(actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
                        delay_s=delay_s, pade_order=pade_order),
            base_out=tune_out,
        )
        resolved = [p for p in relief if p["resolves"]]
        # 결론 문장에 **임계값을 넣는다**. "작동기 대역폭 ×3이면 통과"는 배수라 사양이
        # 못 되지만 "≥ 20.4 rad/s면 통과 (현재 18)"는 그대로 예산이 된다. 아무 완화도
        # 안 통하면 종전 문구 그대로 — 그때는 답이 이 두 축 밖에 있다
        if resolved:
            tail = " / ".join(p["threshold"]["text"] if p.get("threshold")
                              else f"{p['label']} 시 통과" for p in resolved)
            tail += ": 병목은 게인이 아니라 이 예산이다"
        else:
            tail = "지연·작동기 대역폭을 완화해도 통과하지 못한다 — 플랜트·루프 구조 자체를 검토"
        evidence["bottleneck"] = {
            # 못 잰 교차는 None으로 흘린다 — 0으로 메우면 두 수가 "병목 아님"을 단정한다
            "wc_over_actuator": (wcp / actuator_wn) if (wcp is not None and actuator_wn)
            else None,
            "delay_phase_deg_at_wc": (math.degrees(wcp * delay_s) if wcp is not None
                                      else None),
            "relief": relief,
            "resolved_by": [p["label"] for p in resolved],
            # 임계값만 따로 모은다 — 화면이 relief를 훑지 않고도 예산을 쓸 수 있게
            "thresholds": {p["threshold"]["name"]: p["threshold"]["value"]
                           for p in resolved if p.get("threshold")},
            "note": "자유 게인으로도 기준 미달 — " + tail,
        }
        return {
            "verdict": "structural_limit",
            "action": {"type": "escalate", "point": v_name, "loop": loop_name},
            "evidence": evidence,
        }

    # 관련 슬롯의 보간 게인 vs 최적 게인 괴리 (valley 판별 재료)
    g_interp = scheduled_gains(tables, design, trims[v_name].case)
    slots = LOOP_SLOTS.get(loop_name, ())
    gaps = {}
    for slot in slots:
        go = tune_out["gains"].get(slot)
        if go is None:
            continue
        gaps[slot] = abs(g_interp[slot] - go) / max(abs(go), _EPS)
    max_gap = max(gaps.values(), default=0.0)
    evidence["interp_gap"] = {"per_slot": gaps, "max": max_gap, "tol": tol_gain}

    # 2) plant 급변 — v를 낀 인접 앵커의 플랜트 거리
    flank_a = points.flanking(v_name, ROLE_ANCHOR)
    if flank_a is not None:
        lo, hi, axis = flank_a
        tr_lo, tr_hi = trims.get(lo), trims.get(hi)
        if tr_lo is not None and tr_hi is not None and tr_lo.converged and tr_hi.converged:
            d = model_distance(lms.get(aircraft, tr_lo), lms.get(aircraft, tr_hi),
                               tr_lo, tr_hi)
            evidence["plant"] = {"pair": (lo, hi), "axis": axis,
                                 "d_total": d["d_total"], "tol": tol_plant,
                                 "detail": {k: d[k] for k in ("d_trim", "d_mode", "d_ctrl")}}
            if d["d_total"] > tol_plant:
                note = None
                if max_gap > tol_gain:
                    note = "valley도 동시 성립 — anchor 승격이 상위 집합 처방이라 이쪽을 택한다"
                return {
                    "verdict": "plant_variation",
                    "action": {"type": "promote", "to": ROLE_ANCHOR, "point": v_name,
                               "note": note},
                    "evidence": evidence,
                }

    # 3) 보간 valley — 최적은 통과 + 괴리 큼 + 이웃 breakpoint는 통과
    flank_b = points.flanking(v_name, ROLE_BREAKPOINT)
    if max_gap > tol_gain and flank_b is not None:
        lo, hi, axis = flank_b
        neighbor_ok = all(
            margin_cases.get(n, {}).get("loops", {}).get(loop_name, {}).get("status")
            not in ("fail",)
            for n in (lo, hi)
        )
        evidence["neighbors"] = {"pair": (lo, hi), "axis": axis, "pass": neighbor_ok}
        if neighbor_ok:
            opt_gains = {s: tune_out["gains"][s] for s in slots if s in tune_out["gains"]}
            role = points.get(v_name).role
            # **앵커에서의 괴리는 적합 실패다.** TUNE이 매 이터레이션 이 점의 자유 게인
            # 최적을 샘플에 넣는데도 보간이 그 값과 어긋난다면, 격자가 성긴 게 아니라
            # 적합 곡선이 이 점을 못 지나간 것이다. "최적 게인을 샘플에 고정"하는 처방은
            # **구조적으로 무효**다 — 이미 그 값이 샘플이고, 병합에서 튜닝 샘플이 이긴다
            # (orchestrator._stage_fit setdefault). 그런데도 applied로 기록되어 이터
            # 예산만 태웠다. 적합을 조이는 것이 이 자리의 유일한 실효 처방이다
            if role == ROLE_ANCHOR:
                return {
                    "verdict": "fit_residual",
                    "action": {
                        "type": "tighten_fit", "point": v_name, "slots": list(slots),
                        "note": "앵커의 보간 괴리 — 이 점의 샘플은 이미 최적이다."
                                " 적합 허용치를 조이고 구간 수를 늘려 곡선이 이 점을 지나게 한다",
                    },
                    "evidence": evidence,
                }
            # breakpoint는 TUNE이 안 도는 자리라 최적 게인 주입이 실제로 값을 바꾼다.
            # 역할은 단방향 래칫이라 승격을 요청하면 터진다 (세션 전량 소실)
            if ROLE_RANK[role] >= ROLE_RANK[ROLE_BREAKPOINT]:
                return {
                    "verdict": "gain_interp_valley",
                    "action": {"type": "refit_at", "point": v_name, "gains": opt_gains,
                               "note": "이미 breakpoint — 승격 대신 그 점의 최적 게인 고정"},
                    "evidence": evidence,
                }
            return {
                "verdict": "gain_interp_valley",
                "action": {"type": "promote", "to": ROLE_BREAKPOINT, "point": v_name,
                           "gains": opt_gains},
                "evidence": evidence,
            }

    # 4) 나머지 — 검증점 추가 (히스테리시스 밴드 밖이면 note로 확대 경고)
    deficit_note = _deficit_note(
        evidence["shortfall"], hysteresis_pm, hysteresis_gm, hysteresis_zeta
    )
    return {
        "verdict": "simple_deficit",
        "action": {"type": "add_validation", "point": v_name, "note": deficit_note},
        "evidence": evidence,
    }


def classify_failures(
    aircraft, points, lms, trims, tables, design, margin_out, *,
    criteria, design_base=None, targets=None, tol_plant=0.25, tol_gain=0.10,
    actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2,
) -> list:
    """마진맵 결과의 fail 목록 전체 분류 — 처방 카드 목록 (심각 순, id 부여).

    같은 점의 여러 자리 실패는 각각 분류하되, 같은 점에 상위 승격이 이미 나왔으면
    하위 처방은 중복이라 supersede로 표시한다 (같은 점을 두 번 승격할 수 없다 —
    points.promote 래칫).

    design_base(손설계 정본)를 함께 넘긴다 — 이유는 classify_margin_deficit 참조.
    """
    kw = dict(
        criteria=criteria, design_base=design_base, targets=targets,
        tol_plant=tol_plant, tol_gain=tol_gain,
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
    )
    actions = []
    promoted: dict = {}  # point → 최고 승격 역할
    rank = {ROLE_BREAKPOINT: 1, ROLE_ANCHOR: 2}
    for f in margin_out["failures"]:
        out = classify_margin_deficit(
            aircraft, f["case"], f["loop"], points, lms, trims, tables, design,
            margin_out["cases"], **kw,
        )
        act = out["action"]
        item = {
            "id": f"{out['verdict']}:{f['case']}:{f['loop']}",
            "case": f["case"], "loop": f["loop"],
            "verdict": out["verdict"], "action": act, "evidence": out["evidence"],
            "severity": f.get("severity"),
        }
        if act["type"] == "promote":
            prev = promoted.get(f["case"])
            if prev is not None and rank[prev] >= rank[act["to"]]:
                item["superseded_by"] = f"{f['case']}→{prev}"
            else:
                promoted[f["case"]] = act["to"]
        actions.append(item)
    return actions
