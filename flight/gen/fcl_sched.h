/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR에서, 값은 파라미터 이미지에서 온다).
 * 그래프    : fcl
 * 구조 지문 : bc5d7dc7d4ee4c60
 * 엔진      : claw 0.2.0
 * sched — 기능축 분할, 17개 블록
 */
#ifndef CLAW_FCL_SCHED_H
#define CLAW_FCL_SCHED_H

#include "fcl_types.h"

/* fcl_step이 선언 순서대로 호출한다. 파라미터·상태 구조체는 fcl 전체와
 * 공유하므로 리셋·범프리스 웜스타트는 진입점 쪽 계약 그대로다. */
void fcl_sched_step(const fcl_params_t *prm, fcl_state_t *sta,
                    double mach, double *out_sched_alt_k_rate, double *out_sched_alt_ki,
                    double *out_sched_alt_kp, double *out_sched_heading_ki,
                    double *out_sched_heading_kp, double *out_sched_pitch_k_rate,
                    double *out_sched_pitch_ki, double *out_sched_pitch_kp,
                    double *out_sched_roll_k_rate, double *out_sched_roll_ki,
                    double *out_sched_roll_kp, double *out_sched_speed_ki,
                    double *out_sched_speed_kp, double *out_sched_yaw_k_rate,
                    double *out_sched_yaw_ki, double *out_sched_yaw_kp);

#endif /* CLAW_FCL_SCHED_H */
