/* CLAW 생성 코드 — 손으로 고치지 말 것 (알고리즘, MATLAB _step 대응). */
#include "fcl.h"

#include "fcl_sched.h"
#include "fcl_ap.h"
#include "fcl_lim.h"
#include "fcl_scas.h"
#include "fcl_mix.h"

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

    /* ── sched — 7개 블록 ── */
    double sched_pitch_k_rate_y;
    double sched_pitch_ki_y;
    double sched_pitch_kp_y;
    double sched_roll_k_rate_y;
    double sched_roll_ki_y;
    double sched_roll_kp_y;
    fcl_sched_step(prm, sta, mach, &sched_pitch_k_rate_y, &sched_pitch_ki_y, &sched_pitch_kp_y,
                   &sched_roll_k_rate_y, &sched_roll_ki_y, &sched_roll_kp_y);

    /* ── ap — 19개 블록 ── */
    double ap_hdg_sat_y;
    double ap_theta_out_y;
    double ap_spd_sat_y;
    fcl_ap_step(prm, sta, psi, V, h, hdot, cmd_speed, cmd_alt, cmd_heading, speed_on, alt_on,
                heading_on, &ap_hdg_sat_y, &ap_theta_out_y, &ap_spd_sat_y);

    /* ── lim — 6개 블록 ── */
    double lim_a_margin_y;
    double lim_theta_lim_y;
    double lim_active_y;
    fcl_lim_step(prm, sta, theta, alpha, mach, ap_theta_out_y, &lim_a_margin_y, &lim_theta_lim_y,
                 &lim_active_y);

    /* ── scas — 17개 블록 ── */
    double scas_pitch_sat_y;
    double scas_roll_sat_y;
    double scas_yaw_sat_y;
    fcl_scas_step(prm, sta, theta, phi, p, q, r, beta, sched_pitch_k_rate_y, sched_pitch_ki_y,
                  sched_pitch_kp_y, sched_roll_k_rate_y, sched_roll_ki_y, sched_roll_kp_y,
                  ap_hdg_sat_y, lim_theta_lim_y, &scas_pitch_sat_y, &scas_roll_sat_y,
                  &scas_yaw_sat_y);

    /* ── mix — 10개 블록 ── */
    double mix_elevon_l_y;
    double mix_elevon_r_y;
    double mix_rudder_y;
    double mix_thr_l_y;
    double mix_thr_r_y;
    fcl_mix_step(prm, sta, ap_spd_sat_y, scas_pitch_sat_y, scas_roll_sat_y, scas_yaw_sat_y,
                 &mix_elevon_l_y, &mix_elevon_r_y, &mix_rudder_y, &mix_thr_l_y, &mix_thr_r_y);

    out->elevon_l = mix_elevon_l_y;
    out->elevon_r = mix_elevon_r_y;
    out->rudder = mix_rudder_y;
    out->throttle_l = mix_thr_l_y;
    out->throttle_r = mix_thr_r_y;
    out->limiter_active = lim_active_y;
    out->alpha_margin = lim_a_margin_y;
    sta->hold = *out;
}
