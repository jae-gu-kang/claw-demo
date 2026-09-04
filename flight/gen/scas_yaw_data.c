/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : scas_yaw
 * 지문    : 2ae2d9d4dbd690e7
 * 엔진    : claw 0.2.0
 * 파라미터 데이터 (MATLAB _data.c 대응)
 */

#include "scas_yaw.h"

const scas_yaw_params_t scas_yaw_params = {
    .wo_p           = 0.9950124791926823,   /* exp(-dt/tau), tau=2.0 s — SCAS_YAW_DT로 구움 */
    .wo_one_minus_p = 0.00498752080731768,  /* 1 − p */
    .damp_k         = 0.8,                  /* 게인 */
    .pid_kp         = 0.5,                  /* 비례 게인 */
    .pid_ki         = 0.0,                  /* 적분 게인 */
    .pid_out_lo     = -0.35,                /* 출력·적분기 클램프 하한 (안티와인드업) */
    .pid_out_hi     = 0.35,                 /* 출력·적분기 클램프 상한 (안티와인드업) */
    .sat_lo         = -0.35,                /* 하한 */
    .sat_hi         = 0.35,                 /* 상한 */
};
