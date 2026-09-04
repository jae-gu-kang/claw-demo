/* CLAW 대조 하네스 — 생성 코드를 표준입력 시퀀스로 돌려 결과를 표준출력에 낸다.
 *
 * 이 파일은 **손으로 쓴다**. 생성기가 진입점 시그니처나 상태 필드 이름을 잘못 내면
 * 여기서 컴파일이 깨지므로, 생성물끼리만 아귀가 맞는 채로 대조가 통과하는 일을 막는다.
 *
 * 출력은 %.17g — 배정밀도가 왕복하므로 비트 일치를 검사할 수 있다.
 */

#include <stdio.h>

#if defined(HARNESS_FCL)
#include "fcl.h"

/* 첫 줄: 트림 웜스타트 (de0 th0 thr0). 생성 코드에 별도 웜스타트 API는 없고
 * 리셋 후 상태 필드를 직접 쓰는 것이 계약이다 (fcl.h 주석) — 그 계약을 여기서 쓴다. */
int main(void)
{
    fcl_state_t s;
    fcl_out_t out;
    double de0, th0, thr0;
    double nav_valid, theta, phi, psi, p, q, r, V, alpha, beta, h, hdot, mach;
    double cmd_speed, cmd_alt, cmd_heading, cmd_pitch, cmd_hdot;
    double speed_on, alt_on, heading_on, pitch_on, hdot_on;

    if (scanf("%lf %lf %lf", &de0, &th0, &thr0) != 3) { return 1; }
    fcl_reset(&s);
    s.scas_pitch_pid_i = de0;   /* law.py:71  scas.pitch.reset(de0) */
    s.ap_alt_pid_i = th0;       /* autopilot.py:134  _alt.reset(theta) */
    s.ap_spd_pid_i = thr0;      /* autopilot.py:132  _spd.reset(throttle) */
    s.hold.elevon_l = de0;      /* law.py:77  _hold = mixer.step(de0, 0, 0, thr0) */
    s.hold.elevon_r = de0;
    s.hold.rudder = 0.0;
    s.hold.throttle_l = thr0;
    s.hold.throttle_r = thr0;

    while (scanf("%lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf"
                 " %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf",
                 &nav_valid, &theta, &phi, &psi, &p, &q, &r, &V, &alpha, &beta,
                 &h, &hdot, &mach, &cmd_speed, &cmd_alt, &cmd_heading,
                 &cmd_pitch, &cmd_hdot,
                 &speed_on, &alt_on, &heading_on, &pitch_on, &hdot_on) == 23) {
        fcl_step(&fcl_params, &s, &out,
                 nav_valid, theta, phi, psi, p, q, r, V, alpha, beta, h, hdot, mach,
                 cmd_speed, cmd_alt, cmd_heading, cmd_pitch, cmd_hdot,
                 speed_on, alt_on, heading_on, pitch_on, hdot_on);
        printf("%.17g %.17g %.17g %.17g %.17g %.17g %.17g\n",
               out.elevon_l, out.elevon_r, out.rudder, out.throttle_l, out.throttle_r,
               out.limiter_active, out.alpha_margin);
    }
    return 0;
}

#elif defined(HARNESS_FCL_MIX)
#include "fcl.h"      /* fcl_reset·fcl_params — 파티션 헤더는 타입만 준다 */
#include "fcl_mix.h"

/* 믹서만 떼어 돌린다 — 차동추력 배분(mix_diff_k)을 **켠 채로** 대조하기 위해서다.
 *
 * 이 기체는 단발이라 mix_diff_k = 0이고, 그러면 배분식이 항상 ±0.0이라 좌우 스로틀이
 * 같은 값으로 무너진다. 그 상태에서는 배분의 부호를 뒤집거나 좌우 출력을 맞바꿔도
 * 비트 일치가 그대로 통과한다(리뷰에서 변이 주입으로 재현). 쌍발 형상을 다시 물리는
 * 순간 그 결함이 탑재 코드에 그대로 실린다.
 *
 * 계수는 컴파일 상수가 아니라 파라미터 필드라, 재생성 없이 사본에 써 넣으면 된다.
 * 첫 줄이 mix_diff_k, 이후 각 줄이 (thr de da dr). */
int main(void)
{
    fcl_params_t prm = fcl_params;   /* 사본 — 원본은 const */
    fcl_state_t s;
    double thr, de, da, dr;
    double el, er, rud, tl, tr;

    if (scanf("%lf", &prm.mix_diff_k) != 1) { return 1; }
    fcl_reset(&s);
    while (scanf("%lf %lf %lf %lf", &thr, &de, &da, &dr) == 4) {
        fcl_mix_step(&prm, &s, thr, de, da, dr, &el, &er, &rud, &tl, &tr);
        printf("%.17g %.17g %.17g %.17g %.17g\n", el, er, rud, tl, tr);
    }
    return 0;
}

#elif defined(HARNESS_SCAS_YAW)
#include "scas_yaw.h"

int main(void)
{
    scas_yaw_state_t s;
    double att_err, rate;

    scas_yaw_reset(&s);
    while (scanf("%lf %lf", &att_err, &rate) == 2) {
        printf("%.17g\n", scas_yaw_step(&scas_yaw_params, &s, att_err, rate));
    }
    return 0;
}

#else
#error "그래프 선택 매크로가 필요하다 (-DHARNESS_FCL / -DHARNESS_FCL_MIX / -DHARNESS_SCAS_YAW)"
#endif
