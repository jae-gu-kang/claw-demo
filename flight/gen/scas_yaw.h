/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : scas_yaw
 * 지문    : a2aeb2c76d2cdf93
 * 엔진    : claw 0.2.0
 */
#ifndef CLAW_SCAS_YAW_H
#define CLAW_SCAS_YAW_H

#include "scas_yaw_types.h"

/* 빌드 요구 — 설계 시뮬과의 비트 일치는 아래 조건에서만 성립한다:
 *   · 부동소수 축약(FMA) 금지   예) -ffp-contract=off
 *   · 빠른 수학 최적화 금지     예) -ffast-math 를 쓰지 않는다
 * 측정: contract=fast로 빌드하면 곱셈-덧셈이 FMA로 합쳐져 중간 반올림이
 * 사라지고, 같은 입력에서 최대 2.8e-16 어긋난다 (clang 14, -O2).
 * 타깃 컴파일러·최적화 옵션 차이는 별도 확인(PIL)이 필요하다. */

extern const scas_yaw_params_t scas_yaw_params;

/* 상태를 초기값으로 되돌린다. 이산 계수는 생성 시점에 구워졌으므로
 * 런타임 초기화는 이것뿐이다 (별도 init 없음).
 * 트림 웜스타트·범프리스 전환은 리셋 후 상태 필드를 직접 대입한다. */
void scas_yaw_reset(scas_yaw_state_t *sta);

double scas_yaw_step(const scas_yaw_params_t *prm, scas_yaw_state_t *sta,
                     double att_err, double rate);

#endif /* CLAW_SCAS_YAW_H */
