/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : b03d13b65eae3f57
 * 엔진    : claw 0.1.0
 * mix — 기능축 분할, 10개 블록
 */
#ifndef CLAW_FCL_MIX_H
#define CLAW_FCL_MIX_H

#include "fcl_types.h"

/* fcl_step이 선언 순서대로 호출한다. 파라미터·상태 구조체는 fcl 전체와
 * 공유하므로 리셋·범프리스 웜스타트는 진입점 쪽 계약 그대로다. */
void fcl_mix_step(const fcl_params_t *prm, fcl_state_t *sta,
                  double ap_spd_sat_y, double scas_pitch_sat_y, double scas_roll_sat_y,
                  double scas_yaw_sat_y, double *out_mix_elevon_l, double *out_mix_elevon_r,
                  double *out_mix_rudder, double *out_mix_thr_l, double *out_mix_thr_r);

#endif /* CLAW_FCL_MIX_H */
