/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : scas_pitch
 * 지문    : 63a64a26cf27ba01
 * 엔진    : claw 0.1.0
 */
#ifndef CLAW_SCAS_PITCH_H
#define CLAW_SCAS_PITCH_H

#include "scas_pitch_types.h"

/* 빌드 요구 — 설계 시뮬과의 비트 일치는 아래 조건에서만 성립한다:
 *   · 부동소수 축약(FMA) 금지   예) -ffp-contract=off
 *   · 빠른 수학 최적화 금지     예) -ffast-math 를 쓰지 않는다
 * 측정: contract=fast로 빌드하면 곱셈-덧셈이 FMA로 합쳐져 중간 반올림이
 * 사라지고, 같은 입력에서 최대 2.8e-16 어긋난다 (clang 14, -O2).
 * 타깃 컴파일러·최적화 옵션 차이는 별도 확인(PIL)이 필요하다. */

/* 이 주기로 이산 계수가 구워져 있다 — 주기를 바꾸려면 재생성해야 한다.
 * 이 값만 고치면 필터 계수가 조용히 틀린다. */
#define SCAS_PITCH_DT 0.01

extern const scas_pitch_params_t scas_pitch_params;

/* 상태를 초기값으로 되돌린다. 이산 계수는 생성 시점에 구워졌으므로
 * 런타임 초기화는 이것뿐이다 (별도 init 없음). */
void scas_pitch_reset(scas_pitch_state_t *s);

double scas_pitch_step(const scas_pitch_params_t *p, scas_pitch_state_t *s,
                       double att_err, double rate, double kp, double ki, double k_rate);

#endif /* CLAW_SCAS_PITCH_H */
