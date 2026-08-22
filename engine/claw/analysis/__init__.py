"""M10 analysis — 고유치·감쇠비·모드 분류, 이득/위상여유, 마진 맵 (도메인 문서 §4.2).

구현됨: damp / classify_lon(단주기·장주기) / classify_lat(더치롤·롤·나선) /
make_siso / loop_margins / margin_map (python-control 기반). pi_loop는 작동기
동특성(actuator_wn·zeta — 2차계 캐스케이드)·순수지연(delay_s — Padé 근사,
pade_order [기본값] 2) 포함 옵션 지원 (01 §4.2 [기본값] — 둘 다 미지정이면 기존과
동일한 플랜트 단독 마진, 포함 여부는 호출자가 결정).
duty — 폐루프 런의 타면 사용 통계(타각 범위별 체류 시간·포화·타율). 주파수영역
마진이 "선형화점에서 얼마나 안정한가"라면 이쪽은 "실제 런에서 작동기를 얼마나
썼는가"다 — 작동기 rate 요구 사양(01 v0.13 ≥10 rad/s)의 검증 창구.
후속: 보드선도 데이터 API, 100 vs 50 Hz 이산화 영향 비교.
"""

from claw.analysis.duty import duty_report, surface_positions
from claw.analysis.envelope import vn_envelope, vn_stall_boundary
from claw.analysis.margins import loop_margins, make_siso, margin_map, pi_loop
from claw.analysis.modes import classify_lat, classify_lon, damp

__all__ = [
    "damp",
    "classify_lon",
    "classify_lat",
    "make_siso",
    "pi_loop",
    "loop_margins",
    "margin_map",
    "vn_envelope",
    "vn_stall_boundary",
    "duty_report",
    "surface_positions",
]
