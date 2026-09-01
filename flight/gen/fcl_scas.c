/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : ba6323a1825a7740
 * 엔진    : claw 0.1.0
 * scas — 기능축 분할, 17개 블록
 */
#include "fcl_scas.h"

#include "claw_rt.h"

void fcl_scas_step(const fcl_params_t *prm, fcl_state_t *sta,
                   double theta, double phi, double p, double q, double r, double beta,
                   double sched_pitch_k_rate_y, double sched_pitch_ki_y, double sched_pitch_kp_y,
                   double sched_roll_k_rate_y, double sched_roll_ki_y, double sched_roll_kp_y,
                   double ap_hdg_sat_y, double lim_theta_lim_y, double *out_scas_pitch_sat,
                   double *out_scas_roll_sat, double *out_scas_yaw_sat)
{
    /* scas_pitch_err — Sum */
    const double scas_pitch_err_y = lim_theta_lim_y - theta;

    /* scas_roll_diff — Sum */
    const double scas_roll_diff_y = ap_hdg_sat_y - phi;

    /* scas_roll_err — wrap_pi */
    const double scas_roll_err_y = claw_wrap_pi(scas_roll_diff_y);

    /* scas_yaw_err — Sum */
    const double scas_yaw_err_y = -beta;

    /* scas_pitch_pid — PID */
    /* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */
    const double scas_pitch_pid_y = claw_clip(sched_pitch_kp_y * scas_pitch_err_y + sta->scas_pitch_pid_i,
                                              prm->scas_pitch_pid_out_lo,
                                              prm->scas_pitch_pid_out_hi);
    sta->scas_pitch_pid_i = claw_clip(sta->scas_pitch_pid_i + FCL_DT * sched_pitch_ki_y * scas_pitch_err_y,
                                      prm->scas_pitch_pid_out_lo, prm->scas_pitch_pid_out_hi);

    /* scas_pitch_damp — Product */
    const double scas_pitch_damp_y = sched_pitch_k_rate_y * q;

    /* scas_pitch_sum — Sum */
    const double scas_pitch_sum_y = scas_pitch_pid_y + scas_pitch_damp_y;

    /* scas_pitch_sat — Saturation */
    const double scas_pitch_sat_y = claw_clip(scas_pitch_sum_y, prm->scas_pitch_sat_lo,
                                              prm->scas_pitch_sat_hi);

    /* scas_roll_pid — PID */
    /* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */
    const double scas_roll_pid_y = claw_clip(sched_roll_kp_y * scas_roll_err_y + sta->scas_roll_pid_i,
                                             prm->scas_roll_pid_out_lo,
                                             prm->scas_roll_pid_out_hi);
    sta->scas_roll_pid_i = claw_clip(sta->scas_roll_pid_i + FCL_DT * sched_roll_ki_y * scas_roll_err_y,
                                     prm->scas_roll_pid_out_lo, prm->scas_roll_pid_out_hi);

    /* scas_roll_damp — Product */
    const double scas_roll_damp_y = sched_roll_k_rate_y * p;

    /* scas_roll_sum — Sum */
    const double scas_roll_sum_y = scas_roll_pid_y + scas_roll_damp_y;

    /* scas_roll_sat — Saturation */
    const double scas_roll_sat_y = claw_clip(scas_roll_sum_y, prm->scas_roll_sat_lo,
                                             prm->scas_roll_sat_hi);

    /* scas_yaw_wo — Washout */
    const double scas_yaw_wo_y = r - sta->scas_yaw_wo_x;
    sta->scas_yaw_wo_x = prm->scas_yaw_wo_p * sta->scas_yaw_wo_x + prm->scas_yaw_wo_one_minus_p * r;

    /* scas_yaw_pid — PID */
    /* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */
    const double scas_yaw_pid_y = claw_clip(prm->scas_yaw_pid_kp * scas_yaw_err_y + sta->scas_yaw_pid_i,
                                            prm->scas_yaw_pid_out_lo, prm->scas_yaw_pid_out_hi);
    sta->scas_yaw_pid_i = claw_clip(sta->scas_yaw_pid_i + FCL_DT * prm->scas_yaw_pid_ki * scas_yaw_err_y,
                                    prm->scas_yaw_pid_out_lo, prm->scas_yaw_pid_out_hi);

    /* scas_yaw_damp — Gain */
    const double scas_yaw_damp_y = prm->scas_yaw_damp_k * scas_yaw_wo_y;

    /* scas_yaw_sum — Sum */
    const double scas_yaw_sum_y = scas_yaw_pid_y + scas_yaw_damp_y;

    /* scas_yaw_sat — Saturation */
    const double scas_yaw_sat_y = claw_clip(scas_yaw_sum_y, prm->scas_yaw_sat_lo,
                                            prm->scas_yaw_sat_hi);

    *out_scas_pitch_sat = scas_pitch_sat_y;
    *out_scas_roll_sat = scas_roll_sat_y;
    *out_scas_yaw_sat = scas_yaw_sat_y;
}
