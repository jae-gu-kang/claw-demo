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

**1. 절 번호를 함부로 바꾸지 않는다.** 소스 코드 주석이 문서 절 번호를 **500곳 넘게** 인용한다
(`01 §4.2`·`02 §5.5`·`02 §8` 등). 절을 옮기거나 번호를 바꾸면 그 인용들을 같이 고쳐야 한다.
특히 `web/js/lib/blocks.test.js`는 02 §8을 **리터럴 제목으로 파싱**하므로 그 절의 제목
문자열은 테스트가 지킨다. 절을 통째로 **옮긴** 경우는 규약 6이 절차를 정한다 — 번호를
지우는 것이 답이 아니다.

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

**6. 절을 통째로 옮겼으면 제목에 `[이관 → NN]`을 남긴다.** 본문은 지우되 **번호는 살려
둔다** — 그 자리에 새 내용을 쓰면 옛 인용이 엉뚱한 것을 가리키기 때문이다. 이 표기가 없으면
검사기에게 그 절은 여전히 실재하는 절이라, **끊긴 참조(시끄러운 실패)가 조용히 틀린 참조로
바뀐다** (v0.75가 실제로 그랬다 — `01 §5`를 가리키던 화면 칩이 "정본은 04"만 있는 절로 <!-- refcheck:ignore -->
안내하고 있었다). 표기가 있으면 검사기가 그 절을 가리키는 참조를 **끊긴 참조와 같이
거부하고 새 목적지를 알려 준다**. 아무도 안 가리키게 돼도 **지우지 않는다** — 지우는 순간
번호가 재사용 가능해지고, 그러면 저장소 밖에 남은 옛 인용(커밋 메시지·메모)이 엉뚱한 곳을
가리킨다. 묘비 여섯 줄의 값이 그것보다 싸다. 하위 번호(`01 §5.1`)도 함께 얼어 검사기가 <!-- refcheck:ignore -->
막는다 — 번호가 얼었다는 것은 그 아래도 얼었다는 뜻이다.

**표기가 어긋나면 검사기가 그것부터 실패로 낸다** — 제목에 「이관」이 있는데 `[이관 → NN]`으로
안 읽히면 그 절은 다시 평범한 절이 되고 규약 6이 통째로 무력해지기 때문이다. 조용히
넘어가는 것이 이 규약이 없애려는 병 그 자체다. 판정은 **대괄호 안의 「이관」**만 보므로
`### 5.2 데이터 이관 절차` 같은 보통 낱말은 걸리지 않는다 — 헤딩에는 탈출구를 두지
않는다. 묘비를 조용히 끄는 스위치가 되기 때문이다. 목적지가 없는 문서면 그것도 실패다.

**`<!-- refcheck:ignore -->`는 반례와 묘비 자기언급에만 쓴다.** 그 줄의 **모든** `§`가 함께
꺼지므로, 살아 있는 참조를 같은 줄에 두지 않는다. 검사기를 조용히 시키려고 쓰기 시작하면
가드가 아니라 장식이 된다.

## 검사기

문서·코드의 모든 `NN §X.Y` 참조가 실재하는 절을 가리키는지 확인한다. **두 수 모두 0이
정상**이고, 아니면 exit 1이라 훅·CI에 그대로 걸 수 있다.

- **끊김** — 가리키는 절이 없다
- **번호 없음** — 어느 문서인지 못 푼다. 규약 2 위반이다 — 연쇄 표기의 둘째,
  코드의 맨 `§5.5`. <!-- refcheck:ignore -->
  이쪽을 세지 않으면 「끊김 0건」이 검사하지 **않은** 참조에까지 안전을 뜻하게 된다
- **이관된 절** — 규약 6의 `[이관 → NN]` 묘비를 가리킨다. 절은 실재하지만 내용은
  거기 없다 — 새 목적지를 함께 낸다
- **묘비 이상** — 제목에 「이관」이 있는데 표기로 안 읽힌다. 가드 자신이 고장 난 것이라
  가장 먼저 낸다
- **문맥과 어긋난 해석** — 앞 문맥이 다른 문서를 말하는데 **읽는 쪽 문서**로 풀린다.
  네 건의 결함이 전부 이 자리에서 났다 — 형태를 늘려 잡는 대신 *불일치 자체*를 잡는다

파일명(`fcs-context-01-….md`)도 문서 번호로 읽고, 규약 5의 줄바꿈이 번호와 `§`를 갈라놓은
경우 앞 줄 꼬리를 이어 푼다 — 규약 2를 어긴 자리를 **틀리게 푸는 대신** 바르게 푼다.

훑는 범위는 `docs` · `engine` · `server` · `flight` · `scripts` · `models` · `web/js` ·
`web/world/src`와 각 README·`web/index.html`이다. **범위 밖은 「0건」의 뜻을 줄인다** —
이 문서가 검사하지 않은 참조까지 안전하다고 읽히면 안 된다. `web/world`의 `계획 §N` ·
`GPU Gems 1 §1`은 이 저장소 문서가 아니라 건너뛴다(건너뛴 수를 함께 낸다). <!-- refcheck:ignore -->

```bash
python3 - <<'EOF'
import re, glob, sys
TOMB = re.compile(r"\[\s*이관\s*(?:→|->)\s*([^\]]*?)\s*\]")
TOMBISH = re.compile(r"\[[^\]]*이관")            # 묘비를 쓰려다 어긋난 자리 (보통 낱말은 안 걸린다)
head, moved, docs, sick = {}, {}, {}, []
for p in sorted(glob.glob("docs/fcs-context-*.md")) + ["docs/conventions.md"]:
    d = "cv" if p.endswith("conventions.md") else re.search(r"-(\d\d)-", p).group(1)
    docs[p] = d
    for n, line in enumerate(open(p, encoding="utf-8"), 1):
        m = re.match(r"^#{2,4}\s+(\d+(?:\.\d+)*)\.?\s+(.*)", line)
        if not m: continue
        head[(d, m.group(1))] = 1
        t = TOMB.search(m.group(2))                       # 묘비 — 규약 6
        if t and t.group(1): moved[(d, m.group(1))] = t.group(1)
        elif TOMBISH.search(m.group(2)):
            sick.append(f"{p}:{n}  제목의 「이관」이 `[이관 → NN]`으로 안 읽힌다: {line.strip()}")
KNOWN = {d for _, d in docs.items()}
for (d, n), to in moved.items():
    if to.split()[0] not in KNOWN:
        sick.append(f"docs: {d} §{n} 의 이관 목적지 「{to}」는 없는 문서다")
# 문서 지시자 — 끝에서 가장 가까운 것이 이긴다. **파일명도 문서 번호다**(사람만 읽던 것).
# named group 필수: 위치 번호로 매기면 대안 하나만 끼워도 조용히 밀린다
DOCTOK = re.compile(r"(?:fcs-context-(?P<num>0[1-6])-[a-z0-9-]*\.md"
                    r"|(?P<impl>구현 문서)|(?P<mod>모듈 문서)|(?P<dom>도메인 문서)"
                    r"|(?P<cv>conventions(?:\.md)?|규약)"
                    r"|(?<![0-9A-Za-z.])(?P<bare>0[1-6]))\s*[)\]`»】]*\s*$")
NAMED = {"impl": "02", "mod": "03", "dom": "01", "cv": "cv"}
FOREIGN = re.compile(r"(계획|GPU Gems \d+)\s*$")   # 이 저장소 문서가 아닌 §
STRONG = re.compile(r"fcs-context-(0[1-6])-|(?<![0-9A-Za-z.])(0[1-6])(?![0-9])")
CHAIN = re.compile(r"§\s?\d+(?:\.\d+)*\s*[·,]\s*$")   # 규약 2 위반: 둘째부터 번호 생략
def doc_of(ctx):
    m = DOCTOK.search(ctx)
    if not m: return None
    return m["num"] or m["bare"] or next(v for k, v in NAMED.items() if m[k])
def tomb(d, sec):                                     # 묘비 자신과 그 하위 번호
    return next((((dd, n), v) for (dd, n), v in moved.items()
                 if dd == d and (sec == n or sec.startswith(n + "."))), None)
bad, vague, gone, odd, seen = [], [], [], [], set()
src = [*glob.glob("docs/*.md"), *glob.glob("engine/**/*.py", recursive=True),
       *glob.glob("server/**/*.py", recursive=True), *glob.glob("flight/**/*.py", recursive=True),
       *glob.glob("scripts/**/*.py", recursive=True), *glob.glob("models/**/*.py", recursive=True),
       *glob.glob("models/**/*.md", recursive=True), *glob.glob("web/js/**/*.js", recursive=True),
       *glob.glob("web/world/src/**/*.ts", recursive=True),
       "README.md", "web/README.md", "server/README.md", "web/index.html"]
for p in src:
    if "node_modules" in p or ".venv" in p: continue
    own, prev = docs.get(p), ""
    for n, line in enumerate(open(p, encoding="utf-8", errors="ignore"), 1):
        if "refcheck:ignore" in line: prev = line.rstrip(); continue
        for m in re.finditer(r"§\s?(\d+(?:\.\d+)*)", line):
            # 규약 5의 줄바꿈이 번호와 §를 갈라놓는다 — 앞 줄 꼬리를 이어 푼다
            ctx = (prev + " " + line[:m.start()] if not line[:m.start()].strip()
                   else line[:m.start()])[-64:]
            if FOREIGN.search(ctx): continue
            d, sec = doc_of(ctx), m.group(1)
            if d is None and (own is None or CHAIN.search(ctx)):
                vague.append(f"{p}:{n}  §{sec}"); continue
            if d is None and STRONG.search(ctx):   # own으로 되돌아가는데 앞에 다른 문서가 있다
                odd.append(f"{p}:{n}  §{sec} — 앞 문맥이 다른 문서를 말하는데 {own}로 풀린다")
            d = d or own
            t = tomb(d, sec)
            if t: gone.append(f"{p}:{n}  {d} §{sec} 는 이관됐다 → {t[1]}"); seen.add(t[0])
            elif (d, sec) not in head: bad.append(f"{p}:{n}  →  {d} §{sec}")
        prev = line.rstrip()
for name, rows in [("묘비 표기 이상", sick), ("끊긴 참조", bad), ("문서 번호 없는 참조", vague),
                   ("이관된 절을 가리키는 참조", gone), ("문맥과 어긋난 해석", odd)]:
    print("\n".join(rows) or f"{name} 없음")
for k, to in sorted(moved.items()):
    if k not in seen: print(f"i {k[0]} §{k[1]} [이관 → {to}] 가리키는 참조 없음 (번호는 계속 예약)")
print(f"— 묘비 {len(sick)} · 끊김 {len(bad)} · 번호 없음 {len(vague)} · 이관됨 {len(gone)} · 어긋남 {len(odd)}")
sys.exit(1 if sick or bad or vague or gone or odd else 0)
EOF
```
