"""M8 최상위 — 모드 실행기 + 경로추종 → GuidanceCommand (M7 소비).

step(nav)마다: 경로추종 갱신 → 모드 전환 평가 → 활성 모드의 명령 구성.
NavOutput만 소비 (03 §4 계약). 모드 전환 순간의 명령 점프는 오토파일럿
명령필터(M7, 01 §3.2)가 완충 — 별도 페이딩은 백로그 (M2 Fader).
nav.valid=False → 전환·경로 갱신 동결, 마지막 명령 유지 [기본값] (첫 유효
이전엔 전 축 비활성 — M7의 웜스타트 홀드와 합쳐져 안전).
"""

from dataclasses import replace

from claw.common.contracts import GuidanceCommand
from claw.guidance.modes import ModeSequencer


class Guidance:
    def __init__(self, modes, path=None, initial=None):
        self.seq = ModeSequencer(modes, initial=initial)
        self.path = path
        if path is None:
            if any(m.heading == "path" for m in modes):
                raise ValueError('heading="path" 모드가 있으나 경로추종기가 없음')
            if any(m.exit_when[0] == "path_done" for m in modes):
                # path 없으면 path_done이 영원히 False — 조용한 미이탈 모드 방지
                raise ValueError('exit_when=("path_done",) 모드가 있으나 경로추종기가 없음')

    def init(self, dt: float) -> "Guidance":
        self.dt = dt
        if self.path is not None:
            self.path.init(dt)
        self.reset()
        return self

    def reset(self) -> None:
        self.seq.reset()
        if self.path is not None:
            self.path.reset()
        self._last_cmd = None

    def step(self, nav) -> GuidanceCommand:
        if not nav.valid:
            if self._last_cmd is not None:
                return replace(self._last_cmd)
            return GuidanceCommand(mode=self.seq.mode)  # 전 축 비활성
        path_hdg, path_done = (
            self.path.step(nav) if self.path is not None else (None, False)
        )
        mode = self.seq.step(nav, nav.t, path_done)
        heading = path_hdg if mode.heading == "path" else mode.heading
        cmd = GuidanceCommand(
            speed=0.0 if mode.speed is None else float(mode.speed),
            alt=0.0 if mode.alt is None else float(mode.alt),
            heading=0.0 if heading is None else float(heading),
            speed_on=mode.speed is not None,
            alt_on=mode.alt is not None,
            heading_on=heading is not None,
            mode=mode.name,
        )
        self._last_cmd = cmd
        return cmd
