/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : a1a24ddcaf2e9fe3
 * 엔진    : claw 0.2.0
 * mix — 기능축 분할, 10개 블록
 */
#include "fcl_mix.h"

#include "claw_rt.h"

void fcl_mix_step(const fcl_params_t *prm, fcl_state_t *sta,
                  double ap_spd_sat_y, double scas_pitch_sat_y, double scas_roll_sat_y,
                  double scas_yaw_sat_y, double *out_mix_elevon_l, double *out_mix_elevon_r,
                  double *out_mix_rudder, double *out_mix_thr_l, double *out_mix_thr_r)
{
    (void)sta;  /* 상태가 없다 */
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

    *out_mix_elevon_l = mix_elevon_l_y;
    *out_mix_elevon_r = mix_elevon_r_y;
    *out_mix_rudder = mix_rudder_y;
    *out_mix_thr_l = mix_thr_l_y;
    *out_mix_thr_r = mix_thr_r_y;
}
