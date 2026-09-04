/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : a1a24ddcaf2e9fe3
 * 엔진    : claw 0.2.0
 * sched — 기능축 분할, 7개 블록
 */
#ifndef CLAW_FCL_SCHED_H
#define CLAW_FCL_SCHED_H

#include "fcl_types.h"

/* fcl_step이 선언 순서대로 호출한다. 파라미터·상태 구조체는 fcl 전체와
 * 공유하므로 리셋·범프리스 웜스타트는 진입점 쪽 계약 그대로다. */
void fcl_sched_step(const fcl_params_t *prm, fcl_state_t *sta,
                    double mach, double *out_sched_pitch_k_rate, double *out_sched_pitch_ki,
                    double *out_sched_pitch_kp, double *out_sched_roll_k_rate,
                    double *out_sched_roll_ki, double *out_sched_roll_kp);

#endif /* CLAW_FCL_SCHED_H */
