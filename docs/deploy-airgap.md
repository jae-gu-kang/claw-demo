# 폐쇄망 반입·운영

일반망에서 개발하고 사내 폐쇄망으로 옮기는 절차. USB 반입이 불가하고 사내
망이동 시스템만 쓸 수 있는 환경을 전제한다.

## 왜 이렇게 나눴나

반입은 승인이 붙는 느린 이벤트다. 반입 후 설치가 실패하면 그 왕복이 통째로 다시
걸린다. 그래서 최적화 대상은 설치 편의가 아니라 **반입 횟수와 실패 확률**이다.

두 가지가 크기와 변경 빈도 모두 반대다.

| | 크기 | 변경 빈도 |
|---|---|---|
| 코드 (`claw-code.bundle`, 전체 git 이력) | **~3 MB** (2026-09-02 실측 2.75) | 매일 |
| 의존성 (`wheelhouse/`) | **수십~수백 MB** | 거의 없음 |

그래서 **한 덩어리로 묶지 않는다.** 의존성은 한 번 반입하고, 이후에는 코드만
1 MB 미만으로 반복해 보낸다. 이 분리가 안전하려면 "의존성이 정말 안 바뀌었나"를
판정할 수단이 필요한데 그게 `requirements.lock`이고, 그 파일의 diff가 곧 판정이다.

## 반입 전 IT에 확인할 것

1. **망이동 시스템 1회 전송 크기 제한.** wheelhouse가 여기 걸리면 분할하거나
   의존성을 줄여야 한다(아래 "크기 줄이기" 참조).
2. **허용 파일 형식.** `.whl`(zip)·`.bundle`(바이너리) 통과 여부. 압축을 풀어
   검사하거나 재압축하면서 파일이 바뀌는지 — 그래서 `MANIFEST.sha256`이 있다.
3. **대상 머신 Python 버전.** 3.10 미만이면 파이썬 자체도 반입 대상이 된다.
   개발 환경과 같은 3.13으로 맞출 수 있으면 가장 안전하다.
4. **대상 아키텍처.** x86_64를 가정한다. ARM이면 휠을 다시 받아야 한다.
5. **`python3-venv` 설치 여부.** 데비안·우분투 계열에서 이게 없으면 venv 생성이
   `ensurepip` 단계에서 실패한다.

## 일반망에서 — 꾸러미 만들기

**대상과 같은 플랫폼(Linux x86_64)에서 수행한다.** 휠은 플랫폼별 바이너리라
macOS에서 만들면 대상에서 안 돈다. 이 리포는 Codespaces가 이미 구성돼 있으므로
거기서 하면 된다(`.devcontainer/`). 어긋나면 `bundle.sh`가 거부한다.

```bash
scripts/lock.sh        # requirements.lock 생성 — 의존성이 바뀐 뒤에만
git add requirements.lock && git commit -m "의존성 고정 갱신"
scripts/bundle.sh      # dist/ 생성
scripts/rehearse.sh    # 폐쇄망인 척 설치해서 증명 — 보내기 전 필수
```

**락파일 커밋은 선택이 아니다.** `bundle.sh`는 미커밋 변경이 있으면 거부하는데,
이는 곧 락파일이 항상 커밋되어 `claw-code.bundle`에 실려 감을 뜻한다. far side의
`setup.sh`가 그 락을 `-c` 제약으로 걸므로, 이 불변조건이 깨지면 대상에 도착한
락과 wheelhouse가 어긋날 수 있다.

`rehearse.sh`가 하는 일: 체크섬 검증 → 번들에서 clone → `--no-index` 설치 →
테스트 4종 → 서버 기동 → **웹소켓 101 업그레이드 확인**. `--no-index`가 걸려
있으므로 설치가 네트워크를 쓰면 그 자리에서 실패한다. 즉 통과했다면 폐쇄망에서도
같은 경로로 설치된다.

산출물은 이렇다.

```
dist/
  claw-code.bundle     main 브랜치 이력 (실험 브랜치는 안 담는다 — 승인 surface)
  wheelhouse/          휠 (setuptools·wheel·pip 포함)
  requirements.lock
  COMMIT               반입한 커밋 해시 — far side에서 대조용
  MANIFEST.sha256
  README-airgap.txt    폐쇄망 쪽 절차 요약 (파일명이 ASCII인 이유는 아래)
```

`--code-only`는 `dist-code/`에 쓴다. 같은 곳에 쓰면 아직 업로드 중일지 모르는
wheelhouse를 지워 버리기 때문이다.

파일명을 ASCII로 둔 이유: 망이동 시스템이 비ASCII 파일명을 음역하거나 인코딩을
바꾸면 far side의 첫 단계인 `sha256sum -c`가 실패하고, 담당자는 "전송이 꾸러미를
손상시켰다"는 합리적이지만 틀린 결론에 이른다.

## 폐쇄망에서 — 최초 설치

```bash
sha256sum -c MANIFEST.sha256      # 망이동 중 손상 확인
git clone claw-code.bundle claw-demo
cd claw-demo
scripts/setup.sh --offline ../wheelhouse
scripts/run.sh
```

`--offline`은 pip에 `--no-index --find-links`를 붙일 뿐, 설치 절차 자체는 일반망과
**완전히 같은 코드 경로**를 탄다. 폐쇄망 전용 설치 스크립트를 따로 두면 절차가
갈라져 "일반망에서만 되는" 상태가 다시 생긴다.

## 폐쇄망에서 — 코드만 갱신

`requirements.lock`이 안 바뀌었으면 의존성을 다시 보낼 필요가 없다.

```bash
# 일반망
scripts/bundle.sh --code-only     # dist-code/, ~3 MB

# 폐쇄망
cd claw-demo
git fetch /경로/claw-code.bundle main
git reset --hard "$(cat /경로/COMMIT)"
git rev-parse HEAD                             # COMMIT과 같은지 확인
scripts/setup.sh --offline /경로/wheelhouse    # 대개 아무것도 안 깔린다

# 서비스로 돌린다면 — 빼먹으면 /api/health가 옛 커밋을 계속 답한다.
# sed는 **그 줄이 이미 있을 때만** 걸린다: 없으면 조용히 아무것도 안 하고 0으로 끝나므로
# 먼저 확인한다 (이 줄은 나중에 생겼다 — 그 전에 설치한 유닛에는 없다)
UNIT=/etc/systemd/system/claw.service
grep -q '^Environment=CLAW_GIT_COMMIT=' "$UNIT" \
  || echo "유닛에 그 줄이 없다 — 아래 '운영 → systemd' 예시를 먼저 반영할 것"
sudo sed -i "s|^Environment=CLAW_GIT_COMMIT=.*|Environment=CLAW_GIT_COMMIT=$(cat /경로/COMMIT)|" "$UNIT"
sudo systemctl daemon-reload && sudo systemctl restart claw
```

**`CLAW_GIT_COMMIT` 갱신을 빼먹지 말 것.** 코드만 reset하고 유닛을 그대로 두면
`/api/health`가 이전 커밋을 자신 있게 답하고, 아래 '운영'의 대조가 **매번 오탐으로**
울린다. 몇 번 울리면 사람이 그 대조를 믿지 않게 되고, 그러면 이 필드는 없느니만 못하다.

**`git pull`을 쓰면 안 된다.** 일반망에서 커밋을 고쳐 쓴 적이 있으면(amend·rebase —
이 리포는 동시 세션 amend 경합 이력이 있다) far side의 `main`과 번들의 `main`은
갈라진 이력이다. `pull`은 그걸 **머지**하고, 서로 다른 파일만 건드렸다면 충돌 없이
자동으로 합쳐진다. 결과는 "없앤 커밋의 코드 + 새 코드"가 섞인, 아무도 리허설한 적
없는 트리다. far side에는 테스트를 돌릴 절차가 없으니 아무도 모른다.
`reset --hard`는 그 장비의 로컬 변경을 버리는데, 배포 장비이므로 그게 맞다.

### "찾을 수 없다" 오류의 원인은 둘이다

`setup.sh --offline`이 `Could not find a version that satisfies...`를 내면:

1. **이 장비의 Python·플랫폼이 꾸러미와 다르다.** `setup.sh`가 락파일 머리의
   각인과 대조해 이 경우를 이름 대어 알려 준다. **재반입해도 똑같이 실패한다** —
   대상에 맞는 Python을 두거나, 대상과 같은 환경에서 꾸러미를 다시 만들어야 한다.
2. **정말 의존성이 바뀌었다.** 전체 꾸러미를 다시 만들어 반입한다.

1번을 2번으로 오진하면 수십 MB 재반입에 며칠을 쓰고 돌아와 같은 실패를 본다.
그래서 `setup.sh`가 설치 전에 먼저 판정한다.

## 운영

### 워커를 늘리지 말 것

```bash
scripts/run.sh                  # 본인만
HOST=0.0.0.0 scripts/run.sh     # 팀원 접속 — 인증은 옵트인이다, 아래 절 먼저 볼 것
```

**`uvicorn --workers 2` 이상은 조용히 깨진다.** `server/claw_server/jobs.py`의
JobManager가 작업을 프로세스 메모리에 들고 있어(큐·워커 풀 없음), 워커 A가 만든
작업을 워커 B가 못 찾는다. 진행률 조회가 404가 나는데 에러 로그는 안 남는다.
단일 프로세스가 이 앱의 전제다 — 무거운 연산은 numpy·scipy가 GIL을 놓아 주므로
스레드 몇 개로 멀티코어를 쓴다.

### 기동 디렉터리를 고정할 것

결과 저장 경로가 CWD 상대경로다(`$CLAW_SERVER_DATA`, 기본 `server_data`). 기동
위치가 달라지면 별도 `server_data/`가 생겨 이전 산출물이 결과 탭에서 사라진다.
`scripts/run.sh`가 항상 리포 루트로 이동하므로 그걸 쓰면 된다.

### systemd

`/etc/systemd/system/claw.service` — 갱신 절의 `sed`가 이 경로를 쓴다.

```ini
[Unit]
Description=CLAW 설계툴
After=network.target

[Service]
Type=exec
User=claw
WorkingDirectory=/opt/claw-demo
Environment=HOST=0.0.0.0
Environment=CLAW_GIT_COMMIT=<COMMIT 파일의 값>
ExecStart=/opt/claw-demo/scripts/run.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`WorkingDirectory`를 리포 루트로 두는 것이 중요하다(위 항목). 워커 수를 늘리는
옵션은 넣지 말 것.

`CLAW_GIT_COMMIT`은 **도는 것**이 무엇인지 답한다. `git rev-parse HEAD`는 워킹트리가
무엇인지 말할 뿐이라, 재시작을 빼먹었거나 venv 자동 복구가 실패한 채면 둘이 갈린다.
반입한 것과 서빙 중인 것을 직접 대조할 수 있게 `COMMIT` 파일의 값을 여기 넣는다:

```bash
URL=http://127.0.0.1:8000/api/health
curl -s "$URL"                                    # {"status":"ok", …, "commit":"…"}
# 양쪽을 **먼저 받아 비어 있는지 본다.** 그냥 비교하면 commit이 null이고 COMMIT
# 경로도 틀렸을 때 ""="" 가 참이라 "모름 vs 모름"을 "일치"라고 답한다(실측) —
# 바로 아래 문장이 금하는 그 위장이다. 결과도 말하게 한다(test만 쓰면 침묵한다)
got=$(curl -s "$URL" | grep -o '"commit":"[^"]*"' | cut -d'"' -f4)
want=$(cat /경로/COMMIT 2>/dev/null)
if   [ -z "$got"  ]; then echo "commit이 null — 유닛에 CLAW_GIT_COMMIT이 없거나 재시작 안 됨"
elif [ -z "$want" ]; then echo "COMMIT 파일을 못 읽음 — 경로 확인"
elif [ "$got" = "$want" ]; then echo "일치"
else echo "불일치: 도는 것 $got / 반입한 것 $want"
fi
```

안 넣으면 `commit`이 `null`이다 — "모른다"이지 "일치한다"가 아니다. 폐쇄망에는
Render 대시보드 같은 대안이 없으므로 이 대조가 유일한 확인 통로다.

**한계도 알고 쓸 것.** Render의 `RENDER_GIT_COMMIT`은 플랫폼이 **관측**해 주입하지만
`CLAW_GIT_COMMIT`은 사람이 **주장**하는 값이다. `git reset`이 실패했는데 유닛만 갱신하고
재시작하면 `/api/health`는 돌지 않는 커밋을 자신 있게 답한다. 위 갱신 절차에서
`git rev-parse HEAD`와 `COMMIT` 대조를 먼저 통과시키는 것이 그래서 필요하다 —
두 확인은 서로 다른 것을 보며(트리 / 도는 프로세스) 어느 하나로 대체되지 않는다.

**wheelhouse를 지우지 말 것.** `run.sh`는 venv가 깨져 있으면(호스트 파이썬 업그레이드
등) 자동 복구를 시도한다. `setup.sh --offline`이 wheelhouse 경로를
`.venv/.claw-offline-wheelhouse`에 남겨 두므로 복구도 오프라인으로 이뤄지고, 경로가
사라졌으면 **네트워크로 나가지 않고 그 사실을 말하며 죽는다**. 이 표식이 없었다면
`Restart=on-failure` 아래서 PyPI 재시도 루프가 됐을 자리다. 반입한 wheelhouse는
지우지 말고 고정된 경로에 두는 것이 좋다.

### 인증은 옵트인이다

**기본은 무인증**이고 CORS는 전면 허용이다(`app.py`). `HOST=0.0.0.0`으로 노출하면
접근 가능한 누구나 결과를 읽고 쓰고 연산 작업을 실행할 수 있다 — 위 '워커를 늘리지
말 것'의 `HOST=0.0.0.0 scripts/run.sh`가 그 상태다.

`CLAW_ACCESS_PASSWORD`를 주면 **공용 비밀번호 하나짜리 Basic Auth**가 켜진다
(`auth.py` — 공개 데모가 쓰는 방식, 아이디는 무엇이든 무시하고 비밀번호만 본다).
따로 만들 필요가 없다. `/api/health`만 면제인데, 배포 플랫폼 헬스체크가 자격 없이
오기 때문이고 위 커밋 대조 절차도 그 면제 위에 선다.

**비밀번호를 유닛 파일에 인라인으로 넣지 말 것.** `/etc/systemd/system/*.service`는
통상 0644라 그 장비의 모든 사용자가 읽는다. 위 systemd 예시의 `Environment=`는
`CLAW_GIT_COMMIT`(커밋 해시 — 비밀이 아니다)에만 쓰고, 비밀번호는 파일로 뺀다:

```ini
# claw.service
EnvironmentFile=/etc/claw.env
```

```bash
# /etc/claw.env — 0600, claw 소유
sudo install -o claw -g claw -m 600 /dev/null /etc/claw.env
sudo -e /etc/claw.env    # CLAW_ACCESS_PASSWORD=... 한 줄
```

`echo ... | sudo tee`로 쓰지 않는 이유는 그러면 비밀번호가 셸 히스토리에 남기
때문이다. `sudo -e`는 편집기를 거치고 원본의 소유·권한을 보존한다.

CORS는 여전히 전면 허용이라 인증을 켜도 그대로다 — 자격이 실린 요청은 출처를
가리지 않는다. 단독 사용자 로컬 서버 전제의 [기본값]이므로(02 §4), 그것까지
좁혀야 하면 별도 결정이 필요하다.

붙일 것이 더 필요하면 리버스 프록시(nginx·Caddy)보다 앱 자체에 붙이는 쪽을 권한다.
프록시를 쓰면 그 바이너리와 설정까지 별도 반입 대상이 되어 승인 surface가 넓어진다 —
지금 인증이 앱 안에 있는 이유도 그것이다.

## 크기 줄이기 (필요할 때만)

의존성의 상당 부분이 **쓰지 않는 matplotlib 계열**이다(설치 기준 matplotlib
32 MB + fontTools 18 MB + Pillow 14 MB). 우리 코드는 matplotlib을 한 줄도
임포트하지 않지만, `control`이 임포트 시점에 즉시 적재하므로(94개 모듈) 그냥
빼면 `engine/claw/analysis/margins.py`가 죽는다.

없애려면 `control` 자체를 걷어내야 하는데, 쓰는 API는 `ss`·`tf`·`pade`·`margin`
넷뿐이라 scipy로 대체가 불가능하지는 않다. 다만 **안정성 마진은 정확성이 중요한
경로**라 가볍게 건드릴 곳이 아니다. 망이동 시스템의 크기 제한을 먼저 확인하고,
정말 걸릴 때만 별도 작업으로 잡을 것.

## 문제 해결

| 증상 | 원인 |
|---|---|
| `Could not find a version...` | 위 "원인은 둘이다" 참조 — 먼저 Python·플랫폼 불일치를 의심할 것 |
| `이 꾸러미는 다른 환경에서...` | 대상 Python이 꾸러미와 다름. 재반입은 소용없다 |
| `/`가 404, API만 동작 | 비-editable 설치. `setup.sh`를 쓰거나 `CLAW_WEB_DIR` 지정 |
| 진행률이 갱신되다 말고 느림 | 웹소켓이 폴백으로 degrade. `websockets` 미설치 — `rehearse.sh`가 잡는다 |
| 결과 탭이 비어 있음 | 기동 디렉터리가 달라 `server_data/`가 새로 생김 |
| `No module named pip` | `python3-venv` 미설치. `setup.sh`가 깨진 venv를 지우고 재생성한다 |
| 진행률 조회가 404 | uvicorn 워커가 2개 이상 |
| `wheelhouse를 찾을 수 없습니다` | venv가 깨졌는데 반입한 wheelhouse가 원래 경로에 없음 (아래) |
