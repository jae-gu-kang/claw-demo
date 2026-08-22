/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : scas_pitch
 * 지문    : 63a64a26cf27ba01
 * 엔진    : claw 0.1.0
 * 파라미터 데이터 (MATLAB _data.c 대응)
 */

#include "scas_pitch.h"

const scas_pitch_params_t scas_pitch_params = {
    .pid_out_lo = -0.35,  /* 출력·적분기 클램프 하한 (안티와인드업) */
    .pid_out_hi = 0.35,   /* 출력·적분기 클램프 상한 (안티와인드업) */
    .sat_lo     = -0.35,  /* 하한 */
    .sat_hi     = 0.35,   /* 상한 */
};
