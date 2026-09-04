/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : a1a24ddcaf2e9fe3
 * 엔진    : claw 0.2.0
 * lim — 기능축 분할, 6개 블록
 */
#ifndef CLAW_FCL_LIM_H
#define CLAW_FCL_LIM_H

#include "fcl_types.h"

/* fcl_step이 선언 순서대로 호출한다. 파라미터·상태 구조체는 fcl 전체와
 * 공유하므로 리셋·범프리스 웜스타트는 진입점 쪽 계약 그대로다. */
void fcl_lim_step(const fcl_params_t *prm, fcl_state_t *sta,
                  double theta, double alpha, double mach, double ap_theta_out_y,
                  double *out_lim_a_margin, double *out_lim_theta_lim, double *out_lim_active);

#endif /* CLAW_FCL_LIM_H */
