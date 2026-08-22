/* CLAW 대조 하네스 — 생성 코드를 표준입력 시퀀스로 돌려 결과를 표준출력에 낸다.
 *
 * 이 파일은 **손으로 쓴다**. 생성기가 진입점 시그니처를 잘못 내면 여기서 컴파일이
 * 깨지므로, 생성물끼리만 아귀가 맞는 채로 대조가 통과하는 일을 막아 준다.
 *
 * 입력: 한 줄에 att_err rate kp ki k_rate (그래프가 안 쓰는 게인은 읽고 버린다)
 * 출력: 한 줄에 축 명령 하나, %.17g — 배정밀도가 왕복하므로 비트 일치를 검사할 수 있다
 */

#include <stdio.h>

#if defined(HARNESS_SCAS_PITCH)
#include "scas_pitch.h"
typedef scas_pitch_state_t state_t;
#define RESET scas_pitch_reset
#define STEP(s, a, r, kp, ki, kr) \
    scas_pitch_step(&scas_pitch_params, (s), (a), (r), (kp), (ki), (kr))

#elif defined(HARNESS_SCAS_YAW)
#include "scas_yaw.h"
typedef scas_yaw_state_t state_t;
#define RESET scas_yaw_reset
/* 요축은 게인이 상수 파라미터라 포트가 없다 — 읽은 게인은 쓰지 않는다 */
#define STEP(s, a, r, kp, ki, kr) \
    scas_yaw_step(&scas_yaw_params, (s), (a), (r))

#else
#error "그래프 선택 매크로가 필요하다 (-DHARNESS_SCAS_PITCH 등)"
#endif

int main(void)
{
    state_t s;
    double att_err, rate, kp, ki, k_rate;

    RESET(&s);
    while (scanf("%lf %lf %lf %lf %lf", &att_err, &rate, &kp, &ki, &k_rate) == 5) {
        printf("%.17g\n", STEP(&s, att_err, rate, kp, ki, k_rate));
    }
    return 0;
}
