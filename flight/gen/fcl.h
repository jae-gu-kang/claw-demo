/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : 8e540717b28eea23
 * 엔진    : claw 0.2.0
 */
#ifndef CLAW_FCL_H
#define CLAW_FCL_H

#include "fcl_types.h"

/* 빌드 요구 — 설계 시뮬과의 비트 일치는 아래 조건에서만 성립한다:
 *   · 부동소수 축약(FMA) 금지   예) -ffp-contract=off
 *   · 빠른 수학 최적화 금지     예) -ffast-math 를 쓰지 않는다
 * 측정: contract=fast로 빌드하면 곱셈-덧셈이 FMA로 합쳐져 중간 반올림이
 * 사라지고, 같은 입력에서 최대 2.8e-16 어긋난다 (clang 14, -O2).
 * 타깃 컴파일러·최적화 옵션 차이는 별도 확인(PIL)이 필요하다. */

extern const fcl_params_t fcl_params;

/* 상태를 초기값으로 되돌린다. 이산 계수는 생성 시점에 구워졌으므로
 * 런타임 초기화는 이것뿐이다 (별도 init 없음).
 * 트림 웜스타트·범프리스 전환은 리셋 후 상태 필드를 직접 대입한다. */
void fcl_reset(fcl_state_t *sta);

/* nav_valid = 0 이면 아무것도 실행하지 않고 직전 출력을 그대로 낸다
 * (상태도 동결). 첫 스텝부터 비활성일 수 있으므로 hold 초기값은
 * 통합 계층이 트림 값으로 채운다. */
void fcl_step(const fcl_params_t *prm, fcl_state_t *sta, fcl_out_t *out,
              double nav_valid, double theta, double phi, double psi, double p, double q,
              double r, double V, double alpha, double beta, double h, double hdot, double mach,
              double cmd_speed, double cmd_alt, double cmd_heading, double cmd_pitch,
              double cmd_hdot, double speed_on, double alt_on, double heading_on,
              double pitch_on, double hdot_on);

#endif /* CLAW_FCL_H */
