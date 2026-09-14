/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR에서, 값은 파라미터 이미지에서 온다).
 * 그래프    : fcl
 * 구조 지문 : bc5d7dc7d4ee4c60
 * 엔진      : claw 0.2.0
 * ap — 기능축 분할, 32개 블록
 */
#ifndef CLAW_FCL_AP_H
#define CLAW_FCL_AP_H

#include "fcl_types.h"

/* fcl_step이 선언 순서대로 호출한다. 파라미터·상태 구조체는 fcl 전체와
 * 공유하므로 리셋·범프리스 웜스타트는 진입점 쪽 계약 그대로다. */
void fcl_ap_step(const fcl_params_t *prm, fcl_state_t *sta,
                 double psi, double V, double h, double hdot, double mach, double cmd_speed,
                 double cmd_alt, double cmd_heading, double cmd_pitch, double cmd_hdot,
                 double speed_on, double alt_on, double heading_on, double pitch_on,
                 double hdot_on, double sched_alt_k_rate_y, double sched_alt_ki_y,
                 double sched_alt_kp_y, double sched_heading_ki_y, double sched_heading_kp_y,
                 double sched_speed_ki_y, double sched_speed_kp_y, double *out_ap_hdg_sat,
                 double *out_ap_theta_out, double *out_ap_thr_out);

#endif /* CLAW_FCL_AP_H */
