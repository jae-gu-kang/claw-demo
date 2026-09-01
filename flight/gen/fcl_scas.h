/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : ba6323a1825a7740
 * 엔진    : claw 0.1.0
 * scas — 기능축 분할, 17개 블록
 */
#ifndef CLAW_FCL_SCAS_H
#define CLAW_FCL_SCAS_H

#include "fcl_types.h"

/* fcl_step이 선언 순서대로 호출한다. 파라미터·상태 구조체는 fcl 전체와
 * 공유하므로 리셋·범프리스 웜스타트는 진입점 쪽 계약 그대로다. */
void fcl_scas_step(const fcl_params_t *prm, fcl_state_t *sta,
                   double theta, double phi, double p, double q, double r, double beta,
                   double sched_pitch_k_rate_y, double sched_pitch_ki_y, double sched_pitch_kp_y,
                   double sched_roll_k_rate_y, double sched_roll_ki_y, double sched_roll_kp_y,
                   double ap_hdg_sat_y, double lim_theta_lim_y, double *out_scas_pitch_sat,
                   double *out_scas_roll_sat, double *out_scas_yaw_sat);

#endif /* CLAW_FCL_SCAS_H */
