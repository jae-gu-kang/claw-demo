/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : a1a24ddcaf2e9fe3
 * 엔진    : claw 0.2.0
 * ap — 기능축 분할, 26개 블록
 */
#include "fcl_ap.h"

#include <math.h>
#include "claw_rt.h"

void fcl_ap_step(const fcl_params_t *prm, fcl_state_t *sta,
                 double psi, double V, double h, double hdot, double cmd_speed, double cmd_alt,
                 double cmd_heading, double cmd_pitch, double cmd_hdot, double speed_on,
                 double alt_on, double heading_on, double pitch_on, double hdot_on,
                 double *out_ap_hdg_sat, double *out_ap_theta_out, double *out_ap_spd_sat)
{
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
        const double ap_hdg_pid_raw = prm->ap_hdg_pid_kp * ap_hdg_err_y + sta->ap_hdg_pid_i;
        ap_hdg_pid_y = claw_clip(ap_hdg_pid_raw, prm->ap_hdg_pid_out_lo, prm->ap_hdg_pid_out_hi);
        double ap_hdg_pid_inc = FCL_DT * prm->ap_hdg_pid_ki * ap_hdg_err_y;
        if ((ap_hdg_pid_raw > prm->ap_hdg_pid_out_hi && ap_hdg_pid_inc > 0.0) || (ap_hdg_pid_raw < prm->ap_hdg_pid_out_lo && ap_hdg_pid_inc < 0.0)) {
            ap_hdg_pid_inc = 0.0;
        }
        sta->ap_hdg_pid_i = claw_clip(sta->ap_hdg_pid_i + ap_hdg_pid_inc, prm->ap_hdg_pid_out_lo,
                                      prm->ap_hdg_pid_out_hi);

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
    const double ap_alt_pid_raw = prm->ap_alt_pid_kp * ap_alt_err_y + sta->ap_alt_pid_i;
    const double ap_alt_pid_y = claw_clip(ap_alt_pid_raw, prm->ap_alt_pid_out_lo,
                                          prm->ap_alt_pid_out_hi);
    double ap_alt_pid_inc = FCL_DT * prm->ap_alt_pid_ki * ap_alt_err_y;
    if ((ap_alt_pid_raw > prm->ap_alt_pid_out_hi && ap_alt_pid_inc > 0.0) || (ap_alt_pid_raw < prm->ap_alt_pid_out_lo && ap_alt_pid_inc < 0.0)) {
        ap_alt_pid_inc = 0.0;
    }
    sta->ap_alt_pid_i = claw_clip(sta->ap_alt_pid_i + ap_alt_pid_inc, prm->ap_alt_pid_out_lo,
                                  prm->ap_alt_pid_out_hi);

    /* ap_alt_sum — Sum */
    const double ap_alt_sum_y = ap_alt_pid_y + ap_alt_damp_y;

    /* ap_alt_sat — Saturation */
    const double ap_alt_sat_y = claw_clip(ap_alt_sum_y, prm->ap_alt_sat_lo, prm->ap_alt_sat_hi);

    /* ── hdot_on 영역 (2개 노드) ── */
    double ap_fvs_y = 0.0;
    double ap_vs_err_y = 0.0;
    if (hdot_on != 0.0) {
        /* ap_fvs — CommandFilter */
        if (!sta->ap_fvs_seeded) { sta->ap_fvs_x = hdot; sta->ap_fvs_seeded = 1; }
        const double ap_fvs_d = cmd_hdot - sta->ap_fvs_x;
        sta->ap_fvs_x = sta->ap_fvs_x + prm->ap_fvs_one_minus_p * ap_fvs_d;
        ap_fvs_y = sta->ap_fvs_x;

        /* ap_vs_err — Sum */
        ap_vs_err_y = ap_fvs_y - hdot;
    } else {
        /* 비활성 — 상태만 정리한다 (실행하지 않는다) */
        sta->ap_fvs_x = hdot;
        sta->ap_fvs_seeded = 1;
    }

    /* ap_vs_pid — PID */
    /* 미분항 없음 (kd = 0) — e_prev 상태·나눗셈 제거됨 */
    const double ap_vs_pid_raw = prm->ap_vs_pid_kp * ap_vs_err_y + sta->ap_vs_pid_i;
    const double ap_vs_pid_y = claw_clip(ap_vs_pid_raw, prm->ap_vs_pid_out_lo,
                                         prm->ap_vs_pid_out_hi);
    double ap_vs_pid_inc = FCL_DT * prm->ap_vs_pid_ki * ap_vs_err_y;
    if ((ap_vs_pid_raw > prm->ap_vs_pid_out_hi && ap_vs_pid_inc > 0.0) || (ap_vs_pid_raw < prm->ap_vs_pid_out_lo && ap_vs_pid_inc < 0.0)) {
        ap_vs_pid_inc = 0.0;
    }
    sta->ap_vs_pid_i = claw_clip(sta->ap_vs_pid_i + ap_vs_pid_inc, prm->ap_vs_pid_out_lo,
                                 prm->ap_vs_pid_out_hi);

    /* ap_vs_sat — Saturation */
    const double ap_vs_sat_y = claw_clip(ap_vs_pid_y, prm->ap_vs_sat_lo, prm->ap_vs_sat_hi);

    /* ap_pitch_sat — Saturation */
    const double ap_pitch_sat_y = claw_clip(cmd_pitch, prm->ap_pitch_sat_lo,
                                            prm->ap_pitch_sat_hi);

    /* ap_theta_vs — Switch */
    const double ap_theta_vs_y = ((hdot_on) >= prm->ap_theta_vs_threshold ? (ap_vs_sat_y) : (ap_alt_sat_y));

    /* ap_theta_src — Switch */
    const double ap_theta_src_y = ((pitch_on) >= prm->ap_theta_src_threshold ? (ap_pitch_sat_y) : (ap_theta_vs_y));

    /* ap_ff_p_raw — sec_minus_1 */
    const double ap_ff_p_raw_y = 1.0 / cos(ap_hdg_sat_y) - 1.0;

    /* ap_ff_p — Gain */
    const double ap_ff_p_y = prm->ap_ff_p_k * ap_ff_p_raw_y;

    /* ap_theta_ff — Sum */
    const double ap_theta_ff_y = ap_theta_src_y + ap_ff_p_y;

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
    const double ap_spd_pid_raw = prm->ap_spd_pid_kp * ap_spd_err_y + sta->ap_spd_pid_i;
    const double ap_spd_pid_y = claw_clip(ap_spd_pid_raw, prm->ap_spd_pid_out_lo,
                                          prm->ap_spd_pid_out_hi);
    double ap_spd_pid_inc = FCL_DT * prm->ap_spd_pid_ki * ap_spd_err_y;
    if ((ap_spd_pid_raw > prm->ap_spd_pid_out_hi && ap_spd_pid_inc > 0.0) || (ap_spd_pid_raw < prm->ap_spd_pid_out_lo && ap_spd_pid_inc < 0.0)) {
        ap_spd_pid_inc = 0.0;
    }
    sta->ap_spd_pid_i = claw_clip(sta->ap_spd_pid_i + ap_spd_pid_inc, prm->ap_spd_pid_out_lo,
                                  prm->ap_spd_pid_out_hi);

    /* ap_spd_sat — Saturation */
    const double ap_spd_sat_y = claw_clip(ap_spd_pid_y, prm->ap_spd_sat_lo, prm->ap_spd_sat_hi);

    *out_ap_hdg_sat = ap_hdg_sat_y;
    *out_ap_theta_out = ap_theta_out_y;
    *out_ap_spd_sat = ap_spd_sat_y;
}
