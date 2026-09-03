# CLAW — 비행제어·유도법칙 설계툴

MATLAB 없이 고정익 항공기의 제어법칙을 설계·해석·검증하고, 그 결과를 탑재
소프트웨어용 C 코드로 내보내는 도구. 트림 → 선형화·안정성 마진 → 게인 설계 →
폐루프 시뮬레이션 → 코드 생성까지 한 흐름으로 이어진다.

파이썬 엔진 + FastAPI 백엔드 + 빌드 없는 웹 UI로 구성된 모노레포다.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://github.com/codespaces/new?repo=1311729012&ref=main)

## 빠른 시작

### 공개 데모 (Render)

설치 없이 바로 보려면 데모 서버로 — **<https://claw-demo.onrender.com>**.
브라우저가 아이디·비밀번호를 물으면 **아이디는 아무거나**, 비밀번호는
공유받은 것을 넣는다.

무료 인스턴스라 감안할 것:

- 15분 동안 아무도 안 쓰면 잠든다 — **첫 접속이 1분쯤 걸리면** 깨우는 중이다.
- 결과는 휘발성이다. 잠들거나 재배포되면 `server_data/`가 초기화되고, 깨어
  있는 동안에도 최근 20건만 남는다(`CLAW_RESULT_LIMIT`). 남겨야 할 결과라면
  로컬로 돌릴 것.
- 메모리 512MB — 데모 시뮬은 돌지만 대형 배치·마진 맵은 로컬이나
  Codespaces에서 돌리는 편이 낫다.

배포 구성은 리포 루트의 `render.yaml` 하나다. main에 push하면 자동 재배포된다.

**어느 커밋이 떠 있는지**는 `/api/health`가 답한다 — Basic Auth 면제 경로라 자격
없이 확인할 수 있다:

```bash
curl -s https://claw-demo.onrender.com/api/health
# {"status":"ok","version":"0.1.0","engine":"0.1.0","commit":"bb39616…","jobs":0}
```

`commit`은 Render가 배포마다 주는 `RENDER_GIT_COMMIT`이다. Render가 아닌 배포는
`CLAW_GIT_COMMIT`으로 직접 넣으면 되고(그쪽이 우선), 둘 다 없으면 `null` —
로컬 실행이 그렇다. 모른다를 빈 문자열이나 `"unknown"`으로 위장하지 않는다.

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

> **서버에는 기본 인증이 없다.** 단독 사용자 로컬 서버를 전제로 만들어졌고 CORS도
> 전면 허용이다. `HOST=0.0.0.0`으로 노출하면 결과 저장소 읽기·쓰기와 연산 작업
> 실행이 접근 가능한 모두에게 열린다. 신뢰된 네트워크에서만 쓸 것.
> 공개 URL로 내놓아야 한다면 `CLAW_ACCESS_PASSWORD=비밀번호`를 설정 — 공용
> 비밀번호 하나짜리 Basic Auth가 켜진다(공개 데모가 이 방식이다).

### Codespaces

위 배지를 누르면 컨테이너가 뜨고 의존성이 자동 설치된다. 설치가 끝나면
**서버가 자동으로 기동**되므로(`postStartCommand` → `scripts/autostart.sh`)
8000 포트 포워딩 알림이 뜨고 그 링크가 웹 UI다. 직접 띄울 일은 없다.

자동 기동은 컨테이너가 **켜질 때마다** 걸린다. Codespace는 30분 무활동이면
자동 정지하면서 서버 프로세스도 함께 죽는데, 다시 열면 알아서 되살아난다 —
저장해 둔 포워딩 주소가 며칠 뒤에도 그대로 열리는 이유다.

안 떠 있으면 로그가 `/tmp/claw-server.log` 에 있고, 손으로는 `scripts/run.sh`.

> **배지가 안 열린다면** 사내 정책이 `codespaces.new` 도메인을 막고 있을 수 있다.
> 그럴 땐 저장소 화면에서 직접 만들면 된다 — 초록색 **Code** 버튼 → **Codespaces**
> 탭 → **Create codespace on main**. `github.com`만 열리면 되므로 도메인 차단을
> 타지 않는다. (배지 링크도 `github.com/codespaces/new` 를 가리키도록 해 뒀다)

알림을 놓쳤으면 하단 **PORTS** 패널의 8000번 행에서 열 수 있다. 주소를 직접
만들려면 `echo "https://$CODESPACE_NAME-8000.$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN"`.
터미널에 찍히는 `http://127.0.0.1:8000/` 은 컨테이너 안쪽 주소라 눌러도 안 열린다.
포워딩이 잡히지 않으면 `HOST=0.0.0.0 scripts/run.sh` 로 다시 띄운다.

포워딩된 포트는 기본 private이라 본인만 접근할 수 있다. 남에게 보여주려면
Ports 패널에서 해당 포트를 Public으로 바꾸면 되는데, 위의 인증 부재 경고가
그대로 적용된다 — 링크를 아는 사람은 누구나 조작할 수 있다.

> Codespaces 기본 머신은 2코어다. 트림 배치·마진 맵·몬테카를로처럼 CPU 바운드
> 수치 작업은 로컬 개발 머신보다 느릴 수 있다.

### 남에게 보여줄 때

**줄 것은 이 저장소 주소 하나면 된다.** 서버를 따로 세울 필요가 없다 — 상대가
배지를 누르거나 클론하면 엔진·서버·웹이 그 사람 환경에서 함께 뜬다. 별도
데이터베이스도 쓰지 않는다(결과는 `server_data/`에 JSON 파일로 쌓인다).

- **설치 없이 지금 당장** — 위의 공개 데모 URL + 비밀번호. 단, 데모 서버는
  하나를 다 같이 쓰므로 결과가 섞이고 휘발된다.
- **파이썬 환경이 없거나 설치가 번거로운 상대** — Codespaces 배지, 또는 저장소
  화면의 **Code → Codespaces → Create codespace on main**(사내망에서 배지가
  막히는 경우가 있다 — 위 참조). 다만 그 컨테이너는 **상대 GitHub 계정의 무료
  한도**를 쓴다(월 120 core-hour = 2코어 기준 60시간). 둘러보는 데는 충분하고,
  다 보면 codespace를 지우면 된다.
- **직접 돌려볼 상대** — 클론 후 `scripts/run.sh`. Python 3.10+ 만 있으면 된다.

어느 쪽이든 상대는 자기 인스턴스를 쓰므로 서로의 결과가 섞이지 않는다.

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

## 처음 열었다면

설정할 것이 없다. 기본 형상과 데모 미션이 이미 들어 있으므로 바로 돌려보면 된다.

1. **시뮬레이션** 탭에서 **[시뮬 실행]** 을 누른다. 입력을 채울 필요 없다 —
   실행 조건이 기본값으로 차 있고, 시작 트림점은 서버가 알아서 잡는다.
   (상승 → 선회 항법 → 디센트 → 임무수행, 180초 미션)
2. 끝나면 같은 화면에서 재생 슬라이더와 궤적 4면(입체·평면·측면·정면), 그 아래
   시계열이 나온다.
3. **타면 사용** 탭 — 그 시뮬에서 조종면을 얼마나 썼는지, 포화가 있었는지.
4. **Autocode** 탭 — 지금 설계 형상 그대로의 **탑재 C**. 들어가면 통합 열람본이
   기본이고, 파일별로도 볼 수 있다.

**결과** 탭은 시뮬을 한 번 돌리기 전까지 비어 있는 것이 정상이다. 산출물은
`server_data/`에 쌓이고 저장소에는 포함되지 않는다.

## 작업 흐름

웹 UI 탭이 설계 단계에 대응한다.

| 탭 | 내용 |
|---|---|
| 블록도 | 최상위 블록도 → 블록 클릭 시 서브시스템 내부 구조·설계 노트 |
| 엔벨로프 | 제어법칙 설계 엔벨로프 — 필요값 입력으로 구조(V-n)·공력(α–Mach)·추진(스로틀 소요)·운용 선도를 각각 그리고 M-h 평면에 합성, 트림 스캔으로 제어 가능 영역 판정 (뒤 단계의 격자 범위·α 여유 기준) |
| 트림 | 케이스 매트릭스를 배치로 돌려 평형점 산출·수렴 판정 |
| 게인 | 스케줄 자리 선택 + 게인 편집 → 시뮬·탑재 C로 주입 |
| 마진 맵 | 케이스 격자별 선형화 → PM/GM 히트맵·고유치 맵·감쇠비 (설계 게인 검증) |
| 자동 설계 | 트림 격자 자동화 → 게인 자동 튜닝 → 다항 스케줄 적합 → 보간 실효 게인 마진 검증 → 원인별 처방(검증점 추가/승격/에스컬레이션) 이터레이션 — 기본은 승인 게이트, 확정 게인은 게인·시뮬·Autocode로 주입 |
| 시뮬레이션 | 미션·웨이포인트 편집 → 폐루프 시뮬 → 재생·궤적 4면 |
| 타면 사용 | 타각 히스토그램·누적 초과·타각–타율 밀도 + 작동기 능력 상자 |
| Autocode | 현재 형상의 탑재 C 생성·열람 (통합/모듈별) |
| 영향성 | 파라미터 하나가 제어법칙 IR과 설계 지표에 어디까지 번지는지 |
| 결과 | 저장된 산출물 목록과 계보 지문 |

코드 생성의 정본은 `flight/generate.py`다 — 설계 결과를 IR로 고정한 뒤
기능축(SCAS·오토파일럿·리미터·믹서·스케줄)으로 나눠 C 소스를 `flight/gen/`으로
내보내고, `flight/tests/test_parity.py`가 생성 C와 파이썬 IR의 수치 일치를
검증한다. **Autocode 탭은 같은 생성기를 서버(`POST /api/codegen/flight`) 경유로
불러 브라우저에서 보여 준다** — 웹이 C를 조립하는 것이 아니라서, 같은 형상이면
응답이 커밋된 `flight/gen/`과 바이트 단위로 같다(서버 테스트가 대조).

## 구조

| 디렉터리 | 내용 |
|---|---|
| `engine/` | 도메인 엔진 — 블록·공력·EOM·트림·선형화·해석·시뮬. 순수 파이썬 |
| `server/` | FastAPI REST + 웹소켓 진행률. 엔진 API만 호출하고 도메인 로직 없음 |
| `web/` | 바닐라 ES 모듈, 빌드 없음. 외부 의존은 3D 월드용 vendored three.js **1건뿐**(`js/vendor/`, 02 §4 예외). 서버가 정적 서빙 |
| `flight/` | 탑재 SW용 C 코드 생성기와 생성물, 파이썬↔C 패리티 테스트 |
| `docs/` | 설계 확정 문서 (제어법칙·구현·모듈) |
| `data/` | 예제·검증 데이터 (F-16 공개 공력테이블 등 — 반입 예정) |
| `scripts/` | 설치·기동 스크립트 + 폐쇄망 반입 꾸러미 생성·리허설 |

일부 디렉터리(`server/`, `web/`, `data/`)에는 자체 README가 있다.

## 테스트

```bash
.venv/bin/python -m pytest engine    # 엔진
.venv/bin/python -m pytest server    # 서버
.venv/bin/python -m pytest flight    # 코드젠·패리티
.venv/bin/python -m pytest models    # 모델 생성 스크립트 유틸 (블렌더 불요)
(cd web && node --test "js/**/*.test.js")        # 웹 (node 내장 러너, npm 의존 0)
(cd web/world && node --test "src/**/*.test.ts")  # 가상환경 탭 (별도 스위트 — 위 글로브가 못 닿는다)
```

## 알려진 제약

- **결과 저장 경로가 CWD 상대경로다.** `$CLAW_SERVER_DATA`(기본 `server_data`)를
  기동 디렉터리 기준으로 해석하므로, 다른 위치에서 서버를 띄우면 별도
  `server_data/`가 생기고 이전 산출물이 결과 탭에 보이지 않는다. `scripts/run.sh`는
  이를 피하려고 항상 리포 루트로 이동한 뒤 기동한다.
- **editable 설치가 전제다.** 웹 UI 정적 파일 경로를 `__file__` 기준으로 찾기
  때문에, `-e` 없이 site-packages에 설치하면 `/`가 404가 되고 API만 동작한다.
  그 경우 `CLAW_WEB_DIR`로 `web/` 경로를 직접 지정해야 한다.
- **원격 접속엔 `--host 0.0.0.0`이 필요하다.** 기본은 127.0.0.1 바인딩이다.
  Codespaces에서도 포워딩이 안 잡히면 이걸로 다시 띄운다.
- **uvicorn 워커를 늘리면 안 된다.** 작업 관리자가 프로세스 메모리에 있어
  (`server/claw_server/jobs.py`) `--workers 2` 이상이면 워커 A가 만든 작업을
  B가 못 찾아 진행률 조회가 조용히 404가 된다. 단일 프로세스가 전제다.
- **`flight` 패리티 테스트 2건은 C 컴파일러를 요구한다.** `cc`/`gcc`/`clang`이
  없으면 자동으로 skip된다. 웹 UI·엔진·서버 구동에는 컴파일러가 필요 없다.
- **시뮬 재생은 다운샘플 뷰다.** 모드 밴드 경계가 최대 `stride×dt` 이동할 수
  있다. 수치 판정의 정본은 항상 서버에 저장된 전 해상도 원본이다.
- **폐쇄망 반입은 별도 절차다.** 위 설치 절차는 모두 PyPI 접속을 전제한다.
  오프라인 설치는 `scripts/bundle.sh`로 꾸러미를 만들고 `scripts/setup.sh
  --offline`으로 설치한다 — 절차와 주의사항은 [docs/deploy-airgap.md](docs/deploy-airgap.md).

## 문서

- `docs/fcs-context-01-control-law.md` — 제어법칙 확정 사항
- `docs/fcs-context-02-implementation.md` — 구현 확정 사항
- `docs/fcs-context-03-modules.md` — 모듈 구성
- `docs/conventions.md` — 코드 규약
- `docs/deploy-airgap.md` — 폐쇄망 반입·운영 절차
