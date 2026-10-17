# models — 3D 모델

가상환경(`#world`)이 쓰는 기체·발사관 모델. 각 모델의 형상·리깅·노드 이름은 그
디렉터리의 README가 정본이고, **모델들에 공통인 것만 여기 있다.**

```
models/
  blender_numpy.py        블렌더 내장 numpy 보정 (아래)
  test_blender_numpy.py   그 테스트 — `pytest models`
  detail_kit.py           표면 디테일 도구 — 곡면에 앉는 판·스텐실·이음선·볼트, 둥근 상자 (shahed·발사관이 쓴다)
  test_detail_kit.py      그 순수 기하 테스트
  shahed-136/             델타익 무인기 (기본형 · EO/IR형)
  banshee/                쌍발 제트 표적기 Banshee Jet 80+ — 원본 조립 모델을 같은 규약으로 구움
  launcher/               캐니스터 발사관
```

기체 모델은 **같은 규약**(로컬 +X 우현·+Y 위·+Z 후방, 엘레본 `rotation.x = δ`, 러더 `rotation.y = −δr`)으로
굽고, 가진 타면이 다르면 루트 extras `claw_drive_nodes`로 **자기 구동 노드를 선언**한다 — 규약 설명은
`banshee/README.md`, 화면 쪽 판단은 `web/world/src/core/surfaces.ts driveNodesFor`. 어느 모델을 그릴지는
프로파일 문서의 표시 모델(02 §5.6)이 정한다 — 이 폴더는 자산이고 기체 데이터가 아니다.

## 무엇을 커밋하나

`.glb` · `generate_*.py`(와 그것이 부르는 원본 스크립트) · `README.md` · 테스트만 커밋한다. **`.blend`와
`preview.png`·참고 렌더(`banshee/A*.png`)·원본 스크립트의 직접 산출(`Banshee_Jet80_Assembly.*`)은 커밋하지
않는다** — `data/geo/*.bin`이 세운 "재생성 가능하면 커밋하지 않는다"와 같은 사유다.

`scripts/bundle.sh`는 `HEAD main`의 **전체 이력**을 담고 `HEAD == main`을 강제하므로,
한 번 main에 올라간 바이너리는 이후 **모든 반입에 영구히** 실린다. 실측:

| | 원본 | gzip |
|---|---|---|
| `preview.png` ×2 | 2,346 KB | **2,347 KB** — PNG는 이미 deflate라 안 줄어든다 |
| `.blend` ×2 | 1,205 KB | 209 KB |
| `.glb` ×2 | 193 KB | 45 KB |

런타임이 쓰는 것은 `.glb` 뿐이고, 나머지 둘은 각 모델의 재생성 명령이 다시 만든다.
실제로 이 둘을 이력에서 뺐을 때 반입 꾸러미가 **4.65 MB → 2.19 MB**가 됐다.

## 내장 numpy가 못 뜨는 블렌더

glTF 내보내기는 numpy를 쓰는데, 블렌더가 번들한 numpy는 **블렌더를 빌드한 머신의
macOS SDK에 묶여** 있다. 그보다 낮은 OS에서 돌리면 dlopen이 실패한다 (실측: Blender
5.2.1 / macOS 13.2.1 → `Symbol not found: _cblas_caxpy$NEWLAPACK`,
`built for macOS 26.0 which is newer than running OS`).

**이 실패는 늦게, 조용히 온다** — numpy는 내보내기가 실제로 정점을 쓸 때 처음 불리므로
`.blend`는 멀쩡히 저장되고 GLB만 안 나온다. 애드온 모듈 자체는 import되기 때문에
"애드온이 로드되니 괜찮겠지"로 넘어가기 쉽다.

`blender_numpy.py`가 이것을 보정한다 — 리포 venv에 **같은 파이썬 마이너 버전**용
numpy가 있으면 `sys.path` 맨 앞에 꽂는다. 생성 스크립트가 시작할 때 자동으로 불리므로
따로 할 일은 없고, 갈아끼웠으면 그 사실을 `[numpy]` 줄로 알린다. `PYTHONPATH`로는
안 된다(블렌더가 자기 경로를 앞에 둔다). 다른 경로는 `CLAW_BLENDER_NUMPY`로 지정한다.

전체 사유와 복구 절차는 `blender_numpy.py`의 독스트링이 정본이다.
