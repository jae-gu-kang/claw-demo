/* CLAW 생성 코드 — 손으로 고치지 말 것 (알고리즘, MATLAB _step 대응). */
#include "scas_pitch.h"

static double claw_clip(double x, double lo, double hi)
{
    const double y = (x < lo) ? lo : x;
    return (y > hi) ? hi : y;
}

void scas_pitch_reset(scas_pitch_state_t *s)
{
    s->pid_i = 0.0;
}

double scas_pitch_step(const scas_pitch_params_t *p, scas_pitch_state_t *s,
                       double att_err, double rate, double kp, double ki, double k_rate)
{
    /* pid — PID */
    /* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */
    const double pid_y = claw_clip(kp * att_err + s->pid_i, p->pid_out_lo, p->pid_out_hi);
    s->pid_i = claw_clip(s->pid_i + SCAS_PITCH_DT * ki * att_err, p->pid_out_lo, p->pid_out_hi);

    /* damp — Product */
    const double damp_y = k_rate * rate;

    /* sum — Sum */
    const double sum_y = pid_y + damp_y;

    /* sat — Saturation */
    const double sat_y = claw_clip(sum_y, p->sat_lo, p->sat_hi);

    return sat_y;
}
