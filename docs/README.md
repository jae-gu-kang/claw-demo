# 문서 지도

이 저장소의 설계 정본은 아래 파일들이다. **결정은 한 곳에만 적는다** — 같은 수치·규칙이
두 문서에 있으면 한쪽은 반드시 낡는다(02 §5.5 「중복 정의 금지」의 산문판).

## 어느 주제가 어느 파일에 있나

| 파일 | 담당 | 무엇을 고칠 때 여는가 |
|---|---|---|
| [`fcs-context-01-control-law.md`](fcs-context-01-control-law.md) | **도메인·설계 결정** | 기체·플랜트, 제어법칙 아키텍처, 비행 모드, 게인 스케줄 방침, 설계 엔벨로프, 트림·선형화·마진 해석 |
| [`fcs-context-02-implementation.md`](fcs-context-02-implementation.md) | **툴 구현 결정** | 스코프, MATLAB 대체 매핑, 블록 라이브러리, 데이터 인터페이스, 파라미터 관리 계층, 사용자 워크플로우 |
| [`fcs-context-03-modules.md`](fcs-context-03-modules.md) | **모듈 분할** | 모듈 경계·의존·인터페이스 계약, 저장소 구조, 개발 Phase |
| [`fcs-context-04-criteria.md`](fcs-context-04-criteria.md) | **평가·판정 기준** | 합격선·목표선, 부족량·심각도, 카드·판정·하드 게이트, 진단 규칙, 처방, 미달 원장 |
| [`fcs-context-05-autodesign.md`](fcs-context-05-autodesign.md) | **자동 설계 루프** | 트림 격자 자동화, 게인 자동 튜닝, 다항 적합, 스케줄 인지 검증, 원인 분류, 이터레이션 |
| [`fcs-context-06-webui.md`](fcs-context-06-webui.md) | **웹 UI** | 탭 구성·배치 규약, 화면별 구성, 영향성·감도 화면 |
| [`conventions.md`](conventions.md) | **코드 규약** | 좌표계·단위·부호·명명 |
| [`deploy-airgap.md`](deploy-airgap.md) | **폐쇄망 반입·운영** | 설치·갱신·운영 절차 |
| [`CHANGELOG.md`](CHANGELOG.md) | **변경 이력** | 저장소 단일 카운터 (색인이지 정본이 아니다) |

04·05·06은 **주제 축**이라 01/02/03의 도메인·구현·모듈 축을 가로지른다. 판정선 하나를
바꾸려고 네 문서를 열던 것을 없애기 위해 그렇게 갈랐다 — 그 주제는 그 파일 하나가 정본이다.

## 저장소의 다른 문서

설계 정본은 위 표가 전부다. 아래는 **그 디렉터리 안에서만 쓰는 사실**을 담은 README이며,
정본과 겹치는 내용을 두지 않는다 — 겹치면 한쪽이 반드시 낡는다(위 「결정은 한 곳에만」).

| 파일 | 담당 |
|---|---|
| [`../README.md`](../README.md) | 저장소 첫 화면 — 빠른 시작(데모·로컬·Codespaces), 탭 개요, 테스트, 알려진 제약 |
| [`../server/README.md`](../server/README.md) | M13 설치·기동·API 개요 (02 §8 워크플로우 단계 대응) |
| [`../web/README.md`](../web/README.md) | M14 디렉터리 구조·탭 배치 규약·표시 한계 |
| [`../data/README.md`](../data/README.md) | 예제·검증 데이터, 측지 고정점, 지형 팩 재생성 |
| [`../models/README.md`](../models/README.md) | 3D 모델 공통 규약(커밋 대상·블렌더 numpy) — 모델별 상세는 각 하위 README |

## 상태 표기

| 표기 | 뜻 |
|---|---|
| **[확정]** | 결정 완료. 뒤집으려면 근거와 함께 이력에 남긴다 |
| **[기본값]** | 잠정 채택. 실데이터·실기체 확보 시 교체 대상 |
| **[TBD]** | 미결. 각 문서 말미의 백로그 표에 결정 시점과 함께 등재 |
| **[설계 유의]** | 결정이 아니라 설계 시 주의할 물리적 사실 |
| **[한계]** | 현재 구현이 못 하는 것. 판정 불가를 통과로 위장하지 않기 위해 명시 |
| **[백로그]** | 하기로 했으나 착수 전 |

## 규약 — 문서를 고칠 때

**1. 절 번호를 함부로 바꾸지 않는다.** 소스 코드 주석이 문서 절 번호를 **524곳** 인용한다
(`01 §4.2`·`02 §5.5`·`02 §8` 등). 절을 옮기거나 번호를 바꾸면 그 인용들을 같이 고쳐야 한다.
특히 `web/js/lib/blocks.test.js`는 02 §8을 **리터럴 제목으로 파싱**하므로 그 절의 제목
문자열은 테스트가 지킨다.

**2. 참조에는 항상 문서 번호를 붙인다.** `02 §1 · 02 §2.2`라 쓰고, 둘째부터 번호를
생략한 `02§1·§2.2` 꼴로 쓰지 않는다 — 사람은 읽어도 검사기가 못 푼다. <!-- refcheck:ignore -->

**3. [개정]은 원문을 고친 뒤 그 사실만 남긴다.** 철회된 [확정] 문장을 살려 두지 않는다.
위에서부터 읽는 사람이 틀린 문장을 먼저 만나기 때문이다. 어떤 결정이 왜 뒤집혔는지의
서사는 `CHANGELOG.md`가 갖는다.

**4. 수치는 코드가 정본이다.** 문서는 그 수치가 **왜 그 값인지**를 적고, 값 자체는
코드의 어느 상수가 정본인지 가리킨다. 문서에 값을 적었다면 코드가 바뀔 때 같이 바뀌어야
한다는 뜻이므로, 자주 바뀌는 값은 적지 말고 가리킨다.

**5. 본문은 표시폭 96열에서 접는다** (한글 = 2열). 표·코드블록·헤딩은 예외다. 폭이 문서마다
다르면 한 낱말만 고쳐도 diff가 문단 통째로 떠서 무엇이 바뀌었는지가 안 보인다.

## 검사기

문서·코드의 모든 `NN §X.Y` 참조가 실재하는 절을 가리키는지 확인한다. **두 수 모두 0이
정상**이고, 아니면 exit 1이라 훅·CI에 그대로 걸 수 있다.

- **끊김** — 가리키는 절이 없다
- **번호 없음** — 어느 문서인지 못 푼다. 규약 2 위반이다 — 연쇄 표기의 둘째,
  코드의 맨 `§5.5`. <!-- refcheck:ignore -->
  이쪽을 세지 않으면 「끊김 0건」이 검사하지 **않은** 참조에까지 안전을 뜻하게 된다

```bash
python3 - <<'EOF'
import re, glob, sys
head, docs = {}, {}
for p in sorted(glob.glob("docs/fcs-context-*.md")) + ["docs/conventions.md"]:
    d = "cv" if p.endswith("conventions.md") else re.search(r"-(\d\d)-", p).group(1)
    docs[p] = d
    for line in open(p, encoding="utf-8"):
        m = re.match(r"^#{2,4}\s+(\d+(?:\.\d+)*)\.?\s+", line)
        if m: head[(d, m.group(1))] = 1
PRE = {"구현 문서":"02", "모듈 문서":"03", "도메인 문서":"01", "conventions.md":"cv",
       "conventions":"cv", "규약":"cv", "01":"01", "02":"02", "03":"03", "04":"04",
       "05":"05", "06":"06"}
CHAIN = re.compile(r"§\s?\d+(?:\.\d+)*\s*[·,]\s*$")   # 규약 2 위반: 둘째부터 번호 생략
bad, vague = [], []
src = [*glob.glob("docs/*.md"), *glob.glob("engine/**/*.py", recursive=True),
       *glob.glob("server/**/*.py", recursive=True),
       *glob.glob("web/js/**/*.js", recursive=True), "README.md", "web/README.md"]
for p in src:
    if "node_modules" in p or ".venv" in p: continue
    own = docs.get(p)
    for n, line in enumerate(open(p, encoding="utf-8", errors="ignore"), 1):
        if "refcheck:ignore" in line: continue        # 반례를 적는 줄
        for m in re.finditer(r"§\s?(\d+(?:\.\d+)*)", line):
            ctx = line[:m.start()][-20:]
            d = next((v for k, v in PRE.items() if re.search(re.escape(k) + r"\s*$", ctx)), None)
            if d is None and (own is None or CHAIN.search(ctx)):
                vague.append(f"{p}:{n}  §{m.group(1)}")
            elif (d or own, m.group(1)) not in head:
                bad.append(f"{p}:{n}  →  {d or own} §{m.group(1)}")
print("\n".join(bad) or "끊긴 참조 없음")
print("\n".join(vague) or "문서 번호 없는 참조 없음")
print(f"— 끊김 {len(bad)}건 · 번호 없음 {len(vague)}건 (규약 2)")
sys.exit(1 if bad or vague else 0)
EOF
```
