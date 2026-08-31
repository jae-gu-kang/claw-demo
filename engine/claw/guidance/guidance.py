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
            if any(m.alt == "path" for m in modes):
                raise ValueError('alt="path" 모드가 있으나 경로추종기가 없음')
            if any(m.exit_when[0] == "path_done" for m in modes):
                # path 없으면 path_done이 영원히 False — 조용한 미이탈 모드 방지
                raise ValueError('exit_when=("path_done",) 모드가 있으나 경로추종기가 없음')
        elif any(m.alt == "path" for m in modes) and not getattr(path, "has_alt", False):
            # 고도 없는 웨이포인트 열에서 alt="path"를 허용하면 고도 축이 조용히
            # 꺼진 채(alt_on=False) 날거나, None을 0으로 읽어 해면을 명령한다 —
            # 둘 다 요청한 것과 다르므로 구성 시점에 시끄럽게 거부한다
            raise ValueError('alt="path" 모드가 있으나 웨이포인트에 고도가 없음')

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
        path_hdg, path_alt, path_done = (
            self.path.step(nav) if self.path is not None else (None, None, False)
        )
        mode = self.seq.step(nav, nav.t, path_done)
        # 모드 테이블이 축마다 **출처를 고른다** — heading과 alt가 같은 규약이다.
        # 경로가 이기느니 모드가 이기느니 하는 우선순위를 따로 두지 않는 이유가 이것
        heading = path_hdg if mode.heading == "path" else mode.heading
        alt = path_alt if mode.alt == "path" else mode.alt
        if mode.alt == "path" and alt is None:
            # 구성 시점 가드(__init__)는 그때의 has_alt를 본 스냅샷이다 — 구성 뒤
            # set_waypoints로 고도 없는 열을 넣으면 그 가드를 뒤에서 뚫고 여기로 온다.
            # 조용히 두면 alt_on=False로 **고도 축이 꺼진 채** 날아 가드가 막으려던
            # 결과가 그대로 난다. 지금 리포에서 구성 후 set_waypoints를 부르는 곳은
            # 테스트뿐이지만, 조용한 축 해제는 이 리포가 금하는 위장이다
            # ValueError가 아니라 RuntimeError — 서버 _build가 ValueError를 422(사용자
            # 입력 오류)로 매핑한다. 이건 사용자가 보낸 값의 문제가 아니라 구성 뒤
            # 경로가 바뀐 **엔진 계약 위반**이라 사용자 탓으로 표시되면 안 된다
            raise RuntimeError(
                f'모드 {mode.name!r}가 alt="path"인데 경로가 고도를 내지 않는다 '
                "— 구성 후 고도 없는 웨이포인트로 교체됐는지 확인"
            )
        cmd = GuidanceCommand(
            speed=0.0 if mode.speed is None else float(mode.speed),
            alt=0.0 if alt is None else float(alt),
            heading=0.0 if heading is None else float(heading),
            speed_on=mode.speed is not None,
            alt_on=alt is not None,
            heading_on=heading is not None,
            mode=mode.name,
        )
        self._last_cmd = cmd
        return cmd
