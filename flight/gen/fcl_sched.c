/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR에서, 값은 파라미터 이미지에서 온다).
 * 그래프    : fcl
 * 구조 지문 : bc5d7dc7d4ee4c60
 * 엔진      : claw 0.2.0
 * sched — 기능축 분할, 17개 블록
 */
#include "fcl_sched.h"

#include "claw_rt.h"

void fcl_sched_step(const fcl_params_t *prm, fcl_state_t *sta,
                    double mach, double *out_sched_alt_k_rate, double *out_sched_alt_ki,
                    double *out_sched_alt_kp, double *out_sched_heading_ki,
                    double *out_sched_heading_kp, double *out_sched_pitch_k_rate,
                    double *out_sched_pitch_ki, double *out_sched_pitch_kp,
                    double *out_sched_roll_k_rate, double *out_sched_roll_ki,
                    double *out_sched_roll_kp, double *out_sched_speed_ki,
                    double *out_sched_speed_kp, double *out_sched_yaw_k_rate,
                    double *out_sched_yaw_ki, double *out_sched_yaw_kp)
{
    /* sched_f_mach — CommandFilter */
    if (!sta->sched_f_mach_seeded) { sta->sched_f_mach_x = mach; sta->sched_f_mach_seeded = 1; }
    const double sched_f_mach_d = mach - sta->sched_f_mach_x;
    sta->sched_f_mach_x = sta->sched_f_mach_x + prm->sched_f_mach_one_minus_p * sched_f_mach_d;
    const double sched_f_mach_y = sta->sched_f_mach_x;

    /* sched_alt_k_rate — LookupBlock */
    const double sched_alt_k_rate_y = claw_lookup1d(prm->sched_alt_k_rate_bp,
                                                    prm->sched_alt_k_rate_val,
                                                    prm->sched_alt_k_rate_n, sched_f_mach_y);

    /* sched_alt_ki — LookupBlock */
    const double sched_alt_ki_y = claw_lookup1d(prm->sched_alt_ki_bp, prm->sched_alt_ki_val,
                                                prm->sched_alt_ki_n, sched_f_mach_y);

    /* sched_alt_kp — LookupBlock */
    const double sched_alt_kp_y = claw_lookup1d(prm->sched_alt_kp_bp, prm->sched_alt_kp_val,
                                                prm->sched_alt_kp_n, sched_f_mach_y);

    /* sched_heading_ki — LookupBlock */
    const double sched_heading_ki_y = claw_lookup1d(prm->sched_heading_ki_bp,
                                                    prm->sched_heading_ki_val,
                                                    prm->sched_heading_ki_n, sched_f_mach_y);

    /* sched_heading_kp — LookupBlock */
    const double sched_heading_kp_y = claw_lookup1d(prm->sched_heading_kp_bp,
                                                    prm->sched_heading_kp_val,
                                                    prm->sched_heading_kp_n, sched_f_mach_y);

    /* sched_pitch_k_rate — LookupBlock */
    const double sched_pitch_k_rate_y = claw_lookup1d(prm->sched_pitch_k_rate_bp,
                                                      prm->sched_pitch_k_rate_val,
                                                      prm->sched_pitch_k_rate_n, sched_f_mach_y);

    /* sched_pitch_ki — LookupBlock */
    const double sched_pitch_ki_y = claw_lookup1d(prm->sched_pitch_ki_bp, prm->sched_pitch_ki_val,
                                                  prm->sched_pitch_ki_n, sched_f_mach_y);

    /* sched_pitch_kp — LookupBlock */
    const double sched_pitch_kp_y = claw_lookup1d(prm->sched_pitch_kp_bp, prm->sched_pitch_kp_val,
                                                  prm->sched_pitch_kp_n, sched_f_mach_y);

    /* sched_roll_k_rate — LookupBlock */
    const double sched_roll_k_rate_y = claw_lookup1d(prm->sched_roll_k_rate_bp,
                                                     prm->sched_roll_k_rate_val,
                                                     prm->sched_roll_k_rate_n, sched_f_mach_y);

    /* sched_roll_ki — LookupBlock */
    const double sched_roll_ki_y = claw_lookup1d(prm->sched_roll_ki_bp, prm->sched_roll_ki_val,
                                                 prm->sched_roll_ki_n, sched_f_mach_y);

    /* sched_roll_kp — LookupBlock */
    const double sched_roll_kp_y = claw_lookup1d(prm->sched_roll_kp_bp, prm->sched_roll_kp_val,
                                                 prm->sched_roll_kp_n, sched_f_mach_y);

    /* sched_speed_ki — LookupBlock */
    const double sched_speed_ki_y = claw_lookup1d(prm->sched_speed_ki_bp, prm->sched_speed_ki_val,
                                                  prm->sched_speed_ki_n, sched_f_mach_y);

    /* sched_speed_kp — LookupBlock */
    const double sched_speed_kp_y = claw_lookup1d(prm->sched_speed_kp_bp, prm->sched_speed_kp_val,
                                                  prm->sched_speed_kp_n, sched_f_mach_y);

    /* sched_yaw_k_rate — LookupBlock */
    const double sched_yaw_k_rate_y = claw_lookup1d(prm->sched_yaw_k_rate_bp,
                                                    prm->sched_yaw_k_rate_val,
                                                    prm->sched_yaw_k_rate_n, sched_f_mach_y);

    /* sched_yaw_ki — LookupBlock */
    const double sched_yaw_ki_y = claw_lookup1d(prm->sched_yaw_ki_bp, prm->sched_yaw_ki_val,
                                                prm->sched_yaw_ki_n, sched_f_mach_y);

    /* sched_yaw_kp — LookupBlock */
    const double sched_yaw_kp_y = claw_lookup1d(prm->sched_yaw_kp_bp, prm->sched_yaw_kp_val,
                                                prm->sched_yaw_kp_n, sched_f_mach_y);

    *out_sched_alt_k_rate = sched_alt_k_rate_y;
    *out_sched_alt_ki = sched_alt_ki_y;
    *out_sched_alt_kp = sched_alt_kp_y;
    *out_sched_heading_ki = sched_heading_ki_y;
    *out_sched_heading_kp = sched_heading_kp_y;
    *out_sched_pitch_k_rate = sched_pitch_k_rate_y;
    *out_sched_pitch_ki = sched_pitch_ki_y;
    *out_sched_pitch_kp = sched_pitch_kp_y;
    *out_sched_roll_k_rate = sched_roll_k_rate_y;
    *out_sched_roll_ki = sched_roll_ki_y;
    *out_sched_roll_kp = sched_roll_kp_y;
    *out_sched_speed_ki = sched_speed_ki_y;
    *out_sched_speed_kp = sched_speed_kp_y;
    *out_sched_yaw_k_rate = sched_yaw_k_rate_y;
    *out_sched_yaw_ki = sched_yaw_ki_y;
    *out_sched_yaw_kp = sched_yaw_kp_y;
}
