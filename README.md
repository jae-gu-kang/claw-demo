# CLAW — 비행제어·유도법칙 설계툴

MATLAB 없이 고정익 항공기의 제어법칙을 설계·해석·검증하고, 그 결과를 탑재
소프트웨어용 C 코드로 내보내는 도구. 트림 → 선형화·안정성 마진 → 게인 설계 →
폐루프 시뮬레이션 → 코드 생성까지 한 흐름으로 이어진다.

파이썬 엔진 + FastAPI 백엔드 + 빌드 없는 웹 UI로 구성된 모노레포다.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/jae-gu-kang/claw-demo)

## 빠른 시작

### 로컬

Python 3.10+ 만 있으면 된다.

```bash
git clone https://github.com/jae-gu-kang/claw-demo.git
cd claw-demo
scripts/run.sh
```

브라우저에서 <http://127.0.0.1:8000/>

`run.sh`는 처음 실행될 때 `.venv`를 만들고 의존성을 설치한 뒤 서버를 띄운다
(numpy·scipy를 받느라 첫 회는 몇 분 걸린다). 이후 실행은 바로 기동한다.

```bash
PORT=9000 scripts/run.sh       # 포트 변경
HOST=0.0.0.0 scripts/run.sh    # 원격 VM·Docker에서 외부 접속 허용
scripts/run.sh --reload        # 나머지 인자는 uvicorn으로 전달
```

설치만 따로 하려면 `scripts/setup.sh`.

> **서버에는 인증이 없다.** 단독 사용자 로컬 서버를 전제로 만들어졌고 CORS도
> 전면 허용이다. `HOST=0.0.0.0`으로 노출하면 결과 저장소 읽기·쓰기와 연산 작업
> 실행이 접근 가능한 모두에게 열린다. 신뢰된 네트워크에서만 쓸 것.

### Codespaces

위 배지를 누르면 컨테이너가 뜨고 의존성이 자동 설치된다. 터미널에서
`scripts/run.sh` 를 실행하면 8000 포트 포워딩 알림이 뜨고, 그 링크가 웹 UI다.

포워딩된 포트는 기본 private이라 본인만 접근할 수 있다. 남에게 보여주려면
Ports 패널에서 해당 포트를 Public으로 바꾸면 되는데, 위의 인증 부재 경고가
그대로 적용된다 — 링크를 아는 사람은 누구나 조작할 수 있다.

> Codespaces 기본 머신은 2코어다. 트림 배치·마진 맵·몬테카를로처럼 CPU 바운드
> 수치 작업은 로컬 개발 머신보다 느릴 수 있다.

### 수동 설치

스크립트를 쓰지 않는 경우 **설치 순서가 중요하다.**

```bash
pip install -e engine          # 반드시 먼저
pip install -e "server[dev]"
uvicorn --factory claw_server:create_app --port 8000   # 리포 루트에서
```

`claw-engine`은 `server/pyproject.toml`에 의도적으로 미기재다 — 동명 PyPI
패키지가 잘못 설치되는 것을 막기 위함이라, engine을 먼저 깔지 않으면
`claw_server`가 import 단계에서 실패한다.

## 작업 흐름

웹 UI 탭이 설계 단계에 대응한다.

| 탭 | 내용 |
|---|---|
| 구조도 | 최상위 블록도 → 블록 클릭 시 서브시스템 내부 구조·설계 노트 |
| 트림 | 케이스 매트릭스를 배치로 돌려 평형점 산출·수렴 판정 |
| 마진 맵 | 케이스 격자별 선형화 → PM/GM 히트맵·고유치 맵·감쇠비 |
| 엔벨로프 | V-n 선도 |
| 게인 | 스케줄 게인 테이블 편집 → 시뮬로 주입 |
| 시뮬레이션 | 미션·웨이포인트 편집 → 폐루프 시뮬 → 재생·3면도 |
| 결과 | 저장된 산출물 목록과 계보 지문 |
| 영향성 | 파라미터 하나가 제어법칙 IR과 설계 지표에 어디까지 번지는지 |

코드 생성은 `flight/generate.py`가 담당한다 — 설계 결과를 IR로 고정한 뒤
기능축(SCAS·오토파일럿·리미터·믹서·스케줄)으로 나눠 C 소스를 내보내고,
`flight/tests/test_parity.py`가 생성 C와 파이썬 IR의 수치 일치를 검증한다.

## 구조

| 디렉터리 | 내용 |
|---|---|
| `engine/` | 도메인 엔진 — 블록·공력·EOM·트림·선형화·해석·시뮬. 순수 파이썬 |
| `server/` | FastAPI REST + 웹소켓 진행률. 엔진 API만 호출하고 도메인 로직 없음 |
| `web/` | 바닐라 ES 모듈, 빌드 없음, 외부 의존 0. 서버가 정적 서빙 |
| `flight/` | 탑재 SW용 C 코드 생성기와 생성물, 파이썬↔C 패리티 테스트 |
| `docs/` | 설계 확정 문서 (제어법칙·구현·모듈) |
| `data/` | 예제·검증 데이터 (F-16 공개 공력테이블 등 — 반입 예정) |
| `scripts/` | 설치·기동 스크립트 |

일부 디렉터리(`server/`, `web/`, `data/`)에는 자체 README가 있다.

## 테스트

```bash
.venv/bin/python -m pytest engine    # 엔진
.venv/bin/python -m pytest server    # 서버
.venv/bin/python -m pytest flight    # 코드젠·패리티
cd web && node --test "js/**/*.test.js"   # 웹 (node 내장 러너, npm 의존 0)
```

## 알려진 제약

- **결과 저장 경로가 CWD 상대경로다.** `$CLAW_SERVER_DATA`(기본 `server_data`)를
  기동 디렉터리 기준으로 해석하므로, 다른 위치에서 서버를 띄우면 별도
  `server_data/`가 생기고 이전 산출물이 결과 탭에 보이지 않는다. `scripts/run.sh`는
  이를 피하려고 항상 리포 루트로 이동한 뒤 기동한다.
- **editable 설치가 전제다.** 웹 UI 정적 파일 경로를 `__file__` 기준으로 찾기
  때문에, `-e` 없이 site-packages에 설치하면 `/`가 404가 되고 API만 동작한다.
  그 경우 `CLAW_WEB_DIR`로 `web/` 경로를 직접 지정해야 한다.
- **원격 접속엔 `--host 0.0.0.0`이 필요하다.** 기본은 uvicorn 기본값인
  127.0.0.1 바인딩이다. Codespaces는 포워딩 에이전트가 컨테이너 안에서 돌아
  기본값 그대로도 동작한다.
- **`flight` 패리티 테스트 2건은 C 컴파일러를 요구한다.** `cc`/`gcc`/`clang`이
  없으면 자동으로 skip된다. 웹 UI·엔진·서버 구동에는 컴파일러가 필요 없다.
- **시뮬 재생은 다운샘플 뷰다.** 모드 밴드 경계가 최대 `stride×dt` 이동할 수
  있다. 수치 판정의 정본은 항상 서버에 저장된 전 해상도 원본이다.
- **폐쇄망 반입은 별도 준비가 필요하다.** 위 절차는 모두 PyPI 접속을 전제한다.
  오프라인 설치에는 `pip download`로 타겟 플랫폼·파이썬 버전에 맞는 휠을 미리
  받아 두고 `pip install --no-index --find-links=...` 로 설치해야 한다.

## 문서

- `docs/fcs-context-01-control-law.md` — 제어법칙 확정 사항
- `docs/fcs-context-02-implementation.md` — 구현 확정 사항
- `docs/fcs-context-03-modules.md` — 모듈 구성
- `docs/conventions.md` — 코드 규약
