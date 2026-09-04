/* CLAW 생성 코드 — 손으로 고치지 말 것 (알고리즘, MATLAB _step 대응). */
#include "scas_yaw.h"

#include "claw_rt.h"

void scas_yaw_reset(scas_yaw_state_t *sta)
{
    sta->wo_x = 0.0;
    sta->pid_i = 0.0;
}

double scas_yaw_step(const scas_yaw_params_t *prm, scas_yaw_state_t *sta,
                     double att_err, double rate)
{
    /* wo — Washout */
    const double wo_y = rate - sta->wo_x;
    sta->wo_x = prm->wo_p * sta->wo_x + prm->wo_one_minus_p * rate;

    /* damp — Gain */
    const double damp_y = prm->damp_k * wo_y;

    /* pid — PID */
    /* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */
    const double pid_raw = prm->pid_kp * att_err + sta->pid_i;
    const double pid_y = claw_clip(pid_raw, prm->pid_out_lo, prm->pid_out_hi);
    double pid_inc = SCAS_YAW_DT * prm->pid_ki * att_err;
    const double pid_axis = pid_raw + damp_y;
    if ((pid_axis > prm->pid_out_hi && pid_inc > 0.0) || (pid_axis < prm->pid_out_lo && pid_inc < 0.0)) {
        pid_inc = 0.0;
    }
    sta->pid_i = claw_clip(sta->pid_i + pid_inc, prm->pid_out_lo, prm->pid_out_hi);

    /* sum — Sum */
    const double sum_y = pid_y + damp_y;

    /* sat — Saturation */
    const double sat_y = claw_clip(sum_y, prm->sat_lo, prm->sat_hi);

    return sat_y;
}
