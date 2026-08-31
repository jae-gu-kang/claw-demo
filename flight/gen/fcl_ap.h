/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : b03d13b65eae3f57
 * 엔진    : claw 0.1.0
 * ap — 기능축 분할, 26개 블록
 */
#ifndef CLAW_FCL_AP_H
#define CLAW_FCL_AP_H

#include "fcl_types.h"

/* fcl_step이 선언 순서대로 호출한다. 파라미터·상태 구조체는 fcl 전체와
 * 공유하므로 리셋·범프리스 웜스타트는 진입점 쪽 계약 그대로다. */
void fcl_ap_step(const fcl_params_t *prm, fcl_state_t *sta,
                 double psi, double V, double h, double hdot, double cmd_speed, double cmd_alt,
                 double cmd_heading, double cmd_pitch, double cmd_hdot, double speed_on,
                 double alt_on, double heading_on, double pitch_on, double hdot_on,
                 double *out_ap_hdg_sat, double *out_ap_theta_out, double *out_ap_spd_sat);

#endif /* CLAW_FCL_AP_H */
