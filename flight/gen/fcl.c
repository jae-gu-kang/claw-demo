/* CLAW 생성 코드 — 손으로 고치지 말 것 (알고리즘, MATLAB _step 대응). */
#include "fcl.h"

#include <math.h>

#define CLAW_PI 3.141592653589793

static double claw_clip(double x, double lo, double hi)
{
    const double y = (x < lo) ? lo : x;
    return (y > hi) ? hi : y;
}

/* (-π, π] 래핑 — Python `%`는 나머지가 제수 부호를 따르므로 fmod 뒤 보정한다 */
static double claw_wrap_pi(double a)
{
    double r = fmod(-a + CLAW_PI, 2.0 * CLAW_PI);
    if (r < 0.0) { r += 2.0 * CLAW_PI; }
    return -(r - CLAW_PI);
}

/* 1D 다중선형 보간, 외삽 clip — tables/table.py:54 interp()와 같은 구간 선택 */
static double claw_lookup1d(const double *bp, const double *val, int n, double x)
{
    int i = 0;
    while (i < n - 2 && x >= bp[i + 1]) { i++; }
    const double t = claw_clip((x - bp[i]) / (bp[i + 1] - bp[i]), 0.0, 1.0);
    return (1.0 - t) * val[i] + t * val[i + 1];
}

void fcl_reset(fcl_state_t *sta)
{
    sta->sched_f_mach_x = 0.0;
    sta->sched_f_mach_seeded = 0;
    sta->ap_fpsi_x = 0.0;
    sta->ap_fpsi_seeded = 0;
    sta->ap_hdg_pid_i = 0.0;
    sta->ap_fh_x = 0.0;
    sta->ap_fh_seeded = 0;
    sta->ap_alt_pid_i = 0.0;
    sta->ap_fv_x = 0.0;
    sta->ap_fv_seeded = 0;
    sta->ap_spd_pid_i = 0.0;
    sta->scas_pitch_pid_i = 0.0;
    sta->scas_roll_pid_i = 0.0;
    sta->scas_yaw_wo_x = 0.0;
    sta->scas_yaw_pid_i = 0.0;
    sta->hold.elevon_l = 0.0;
    sta->hold.elevon_r = 0.0;
    sta->hold.rudder = 0.0;
    sta->hold.throttle_l = 0.0;
    sta->hold.throttle_r = 0.0;
    sta->hold.limiter_active = 0.0;
    sta->hold.alpha_margin = 0.0;
}

void fcl_step(const fcl_params_t *prm, fcl_state_t *sta, fcl_out_t *out,
              double nav_valid, double theta, double phi, double psi, double p, double q,
              double r, double V, double alpha, double beta, double h, double hdot, double mach,
              double cmd_speed, double cmd_alt, double cmd_heading, double speed_on,
              double alt_on, double heading_on)
{
    if (nav_valid == 0.0) {  /* 직전 출력 유지, 상태 동결 */
        *out = sta->hold;
        return;
    }

    /* sched_f_mach — CommandFilter */
    if (!sta->sched_f_mach_seeded) { sta->sched_f_mach_x = mach; sta->sched_f_mach_seeded = 1; }
    const double sched_f_mach_d = mach - sta->sched_f_mach_x;
    sta->sched_f_mach_x = sta->sched_f_mach_x + prm->sched_f_mach_one_minus_p * sched_f_mach_d;
    const double sched_f_mach_y = sta->sched_f_mach_x;

    /* sched_pitch_k_rate — LookupBlock */
    const double sched_pitch_k_rate_y = claw_lookup1d(prm->sched_pitch_k_rate_bp,
                                                      prm->sched_pitch_k_rate_val, 17,
                                                      sched_f_mach_y);

    /* sched_pitch_ki — LookupBlock */
    const double sched_pitch_ki_y = claw_lookup1d(prm->sched_pitch_ki_bp, prm->sched_pitch_ki_val,
                                                  17, sched_f_mach_y);

    /* sched_pitch_kp — LookupBlock */
    const double sched_pitch_kp_y = claw_lookup1d(prm->sched_pitch_kp_bp, prm->sched_pitch_kp_val,
                                                  17, sched_f_mach_y);

    /* sched_roll_k_rate — LookupBlock */
    const double sched_roll_k_rate_y = claw_lookup1d(prm->sched_roll_k_rate_bp,
                                                     prm->sched_roll_k_rate_val, 17,
                                                     sched_f_mach_y);

    /* sched_roll_ki — LookupBlock */
    const double sched_roll_ki_y = claw_lookup1d(prm->sched_roll_ki_bp, prm->sched_roll_ki_val,
                                                 17, sched_f_mach_y);

    /* sched_roll_kp — LookupBlock */
    const double sched_roll_kp_y = claw_lookup1d(prm->sched_roll_kp_bp, prm->sched_roll_kp_val,
                                                 17, sched_f_mach_y);

    /* ── heading_on 영역 (5개 노드) ── */
    double ap_fpsi_y = 0.0;
    double ap_psi_diff_y = 0.0;
    double ap_hdg_err_y = 0.0;
    double ap_hdg_pid_y = 0.0;
    double ap_hdg_sat_y = 0.0;
    if (heading_on != 0.0) {
        /* ap_fpsi — CommandFilter */
        if (!sta->ap_fpsi_seeded) { sta->ap_fpsi_x = psi; sta->ap_fpsi_seeded = 1; }
        const double ap_fpsi_d = claw_wrap_pi(cmd_heading - sta->ap_fpsi_x);
        sta->ap_fpsi_x = sta->ap_fpsi_x + prm->ap_fpsi_one_minus_p * ap_fpsi_d;
        sta->ap_fpsi_x = claw_wrap_pi(sta->ap_fpsi_x);
        ap_fpsi_y = sta->ap_fpsi_x;

        /* ap_psi_diff — Sum */
        ap_psi_diff_y = ap_fpsi_y - psi;

        /* ap_hdg_err — wrap_pi */
        ap_hdg_err_y = claw_wrap_pi(ap_psi_diff_y);

        /* ap_hdg_pid — PID */
        /* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */
        ap_hdg_pid_y = claw_clip(prm->ap_hdg_pid_kp * ap_hdg_err_y + sta->ap_hdg_pid_i,
                                 prm->ap_hdg_pid_out_lo, prm->ap_hdg_pid_out_hi);
        sta->ap_hdg_pid_i = claw_clip(sta->ap_hdg_pid_i + FCL_DT * prm->ap_hdg_pid_ki * ap_hdg_err_y,
                                      prm->ap_hdg_pid_out_lo, prm->ap_hdg_pid_out_hi);

        /* ap_hdg_sat — Saturation */
        ap_hdg_sat_y = claw_clip(ap_hdg_pid_y, prm->ap_hdg_sat_lo, prm->ap_hdg_sat_hi);
    } else {
        /* 비활성 — 상태만 정리한다 (실행하지 않는다) */
        sta->ap_fpsi_x = psi;
        sta->ap_fpsi_seeded = 1;
        sta->ap_hdg_pid_i = 0.0;
    }

    /* ── alt_on 영역 (3개 노드) ── */
    double ap_fh_y = 0.0;
    double ap_alt_err_y = 0.0;
    double ap_alt_damp_y = 0.0;
    if (alt_on != 0.0) {
        /* ap_fh — CommandFilter */
        if (!sta->ap_fh_seeded) { sta->ap_fh_x = h; sta->ap_fh_seeded = 1; }
        const double ap_fh_d = cmd_alt - sta->ap_fh_x;
        sta->ap_fh_x = sta->ap_fh_x + prm->ap_fh_one_minus_p * ap_fh_d;
        ap_fh_y = sta->ap_fh_x;

        /* ap_alt_err — Sum */
        ap_alt_err_y = ap_fh_y - h;

        /* ap_alt_damp — Gain */
        ap_alt_damp_y = prm->ap_alt_damp_k * hdot;
    } else {
        /* 비활성 — 상태만 정리한다 (실행하지 않는다) */
        sta->ap_fh_x = h;
        sta->ap_fh_seeded = 1;
    }

    /* ap_alt_pid — PID */
    /* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */
    const double ap_alt_pid_y = claw_clip(prm->ap_alt_pid_kp * ap_alt_err_y + sta->ap_alt_pid_i,
                                          prm->ap_alt_pid_out_lo, prm->ap_alt_pid_out_hi);
    sta->ap_alt_pid_i = claw_clip(sta->ap_alt_pid_i + FCL_DT * prm->ap_alt_pid_ki * ap_alt_err_y,
                                  prm->ap_alt_pid_out_lo, prm->ap_alt_pid_out_hi);

    /* ap_alt_sum — Sum */
    const double ap_alt_sum_y = ap_alt_pid_y + ap_alt_damp_y;

    /* ap_alt_sat — Saturation */
    const double ap_alt_sat_y = claw_clip(ap_alt_sum_y, prm->ap_alt_sat_lo, prm->ap_alt_sat_hi);

    /* ap_ff_p_raw — sec_minus_1 */
    const double ap_ff_p_raw_y = 1.0 / cos(ap_hdg_sat_y) - 1.0;

    /* ap_ff_p — Gain */
    const double ap_ff_p_y = prm->ap_ff_p_k * ap_ff_p_raw_y;

    /* ap_theta_ff — Sum */
    const double ap_theta_ff_y = ap_alt_sat_y + ap_ff_p_y;

    /* ap_theta_out — Saturation */
    const double ap_theta_out_y = claw_clip(ap_theta_ff_y, prm->ap_theta_out_lo,
                                            prm->ap_theta_out_hi);

    /* ── speed_on 영역 (2개 노드) ── */
    double ap_fv_y = 0.0;
    double ap_spd_err_y = 0.0;
    if (speed_on != 0.0) {
        /* ap_fv — CommandFilter */
        if (!sta->ap_fv_seeded) { sta->ap_fv_x = V; sta->ap_fv_seeded = 1; }
        const double ap_fv_d = cmd_speed - sta->ap_fv_x;
        sta->ap_fv_x = sta->ap_fv_x + prm->ap_fv_one_minus_p * ap_fv_d;
        ap_fv_y = sta->ap_fv_x;

        /* ap_spd_err — Sum */
        ap_spd_err_y = ap_fv_y - V;
    } else {
        /* 비활성 — 상태만 정리한다 (실행하지 않는다) */
        sta->ap_fv_x = V;
        sta->ap_fv_seeded = 1;
    }

    /* ap_spd_pid — PID */
    /* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */
    const double ap_spd_pid_y = claw_clip(prm->ap_spd_pid_kp * ap_spd_err_y + sta->ap_spd_pid_i,
                                          prm->ap_spd_pid_out_lo, prm->ap_spd_pid_out_hi);
    sta->ap_spd_pid_i = claw_clip(sta->ap_spd_pid_i + FCL_DT * prm->ap_spd_pid_ki * ap_spd_err_y,
                                  prm->ap_spd_pid_out_lo, prm->ap_spd_pid_out_hi);

    /* ap_spd_sat — Saturation */
    const double ap_spd_sat_y = claw_clip(ap_spd_pid_y, prm->ap_spd_sat_lo, prm->ap_spd_sat_hi);

    /* lim_stall — LookupBlock */
    const double lim_stall_y = claw_lookup1d(prm->lim_stall_bp, prm->lim_stall_val, 5, mach);

    /* lim_alpha_max — add_const */
    const double lim_alpha_max_y = lim_stall_y - 0.05;

    /* lim_a_margin — Sum */
    const double lim_a_margin_y = lim_alpha_max_y - alpha;

    /* lim_cap — Sum */
    const double lim_cap_y = theta + lim_a_margin_y;

    /* lim_theta_lim — min2 */
    const double lim_theta_lim_y = ((lim_cap_y) < (ap_theta_out_y) ? (lim_cap_y) : (ap_theta_out_y));

    /* lim_active — gt */
    const double lim_active_y = ((ap_theta_out_y) > (lim_cap_y) ? 1.0 : 0.0);

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

    /* mix_sum_l — Sum */
    const double mix_sum_l_y = scas_pitch_sat_y + scas_roll_sat_y;

    /* mix_elevon_l — Saturation */
    const double mix_elevon_l_y = claw_clip(mix_sum_l_y, prm->mix_elevon_l_lo,
                                            prm->mix_elevon_l_hi);

    /* mix_sum_r — Sum */
    const double mix_sum_r_y = scas_pitch_sat_y - scas_roll_sat_y;

    /* mix_elevon_r — Saturation */
    const double mix_elevon_r_y = claw_clip(mix_sum_r_y, prm->mix_elevon_r_lo,
                                            prm->mix_elevon_r_hi);

    /* mix_rudder — Saturation */
    const double mix_rudder_y = claw_clip(scas_yaw_sat_y, prm->mix_rudder_lo, prm->mix_rudder_hi);

    /* mix_diff — Gain */
    const double mix_diff_y = prm->mix_diff_k * mix_rudder_y;

    /* mix_thr_l_raw — Sum */
    const double mix_thr_l_raw_y = ap_spd_sat_y - mix_diff_y;

    /* mix_thr_l — Saturation */
    const double mix_thr_l_y = claw_clip(mix_thr_l_raw_y, prm->mix_thr_l_lo, prm->mix_thr_l_hi);

    /* mix_thr_r_raw — Sum */
    const double mix_thr_r_raw_y = ap_spd_sat_y + mix_diff_y;

    /* mix_thr_r — Saturation */
    const double mix_thr_r_y = claw_clip(mix_thr_r_raw_y, prm->mix_thr_r_lo, prm->mix_thr_r_hi);

    out->elevon_l = mix_elevon_l_y;
    out->elevon_r = mix_elevon_r_y;
    out->rudder = mix_rudder_y;
    out->throttle_l = mix_thr_l_y;
    out->throttle_r = mix_thr_r_y;
    out->limiter_active = lim_active_y;
    out->alpha_margin = lim_a_margin_y;
    sta->hold = *out;
}
