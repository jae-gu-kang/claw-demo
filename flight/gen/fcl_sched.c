/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : 3e032f9003b7cc9f
 * 엔진    : claw 0.2.0
 * sched — 기능축 분할, 7개 블록
 */
#include "fcl_sched.h"

#include "claw_rt.h"

void fcl_sched_step(const fcl_params_t *prm, fcl_state_t *sta,
                    double mach, double *out_sched_pitch_k_rate, double *out_sched_pitch_ki,
                    double *out_sched_pitch_kp, double *out_sched_roll_k_rate,
                    double *out_sched_roll_ki, double *out_sched_roll_kp)
{
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

    *out_sched_pitch_k_rate = sched_pitch_k_rate_y;
    *out_sched_pitch_ki = sched_pitch_ki_y;
    *out_sched_pitch_kp = sched_pitch_kp_y;
    *out_sched_roll_k_rate = sched_roll_k_rate_y;
    *out_sched_roll_ki = sched_roll_ki_y;
    *out_sched_roll_kp = sched_roll_kp_y;
}
