# CLAUDE.md
Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

<!-- 판단 기준: 아래 "Trivial vs Non-trivial" 기준에 해당하면 질문 없이 바로 진행,
     그 외에는 원칙대로 가정을 명시하고 필요시 질문할 것. -->

## 0. Trivial vs Non-trivial (판단 기준)
Proceed without asking when ALL of the following are true:
- The change is easily reversible (git revert, small diff).
- There's only one reasonable interpretation of the request.
- The blast radius is limited to the file(s) explicitly mentioned.

If any of these fail, treat it as non-trivial and follow Section 1 (state assumptions / ask).

<!-- 예: "이 함수에 null 체크 추가해줘" → trivial, 바로 진행
     예: "이 모듈 구조 좀 정리해줘" → non-trivial, 해석이 여러 개일 수 있음 → 질문 -->

## 1. Think Before Coding
**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing (non-trivial tasks):
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First
**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes
**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

<!-- 단, 프로젝트에 prettier/black 등 자동 포매터가 강제되어 있다면
     그 포매터의 결과는 예외로 허용 (안 그러면 매 커밋마다 충돌). -->
Exception: if the project enforces an auto-formatter (prettier, black, etc.), formatter-driven changes to touched files are allowed even if they affect adjacent lines.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution
**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. Plan Tracking (plan.md)

프로젝트 루트의 `plan.md`는 전체 작업 진행 상황을 기록하는 단일 소스입니다.

**작업 시작 전:**
- `plan.md`를 먼저 읽고 현재 진행 상황과 다음 할 일을 파악할 것.
- 새로운 non-trivial 작업을 시작하면, Section 4의 계획을 `plan.md`에 추가할 것.

**작업 완료 후:**
- 완료된 항목은 체크 표시하고, 실제로 뭘 했는지 1-2줄로 기록할 것.
- 계획과 다르게 진행된 부분(막혀서 접근을 바꿨다든지)이 있으면 그 이유도 기록할 것.

**형식 예시:**
```markdown
## Back
- [x] GitHub API 연동 (레포 정보 fetch) - 2024-XX-XX
  - GET /repos/{owner}/{repo}, /git/trees 사용
- [ ] 코드 청킹 로직 (함수/클래스 단위)
- [ ] Chroma 벡터DB 연동

## Front
- [ ] 레포 링크 입력 UI
- [ ] 분석 결과 표시 화면
```

**주의:** plan.md는 작업 로그이지 명세서가 아닙니다. 장황한 설명 대신 핵심만 간결하게 기록할 것.

### 문서가 어디에 무엇을 담는가

루트의 마크다운 문서는 역할이 다릅니다. **섞으면 둘 다 읽기 나빠집니다.**

| 문서 | 담는 것 | 쓰는 시점 |
|---|---|---|
| `plan.md` | **시간순 작업 로그.** 무엇을 언제 왜 했나, 계획과 검증 | 작업 전(계획) · 작업 후(결과) |
| `TROUBLESHOOTING.md` | **증상별 색인.** 겪은 문제를 증상 → 원인 → 해결 한 줄로 | 함정을 만났을 때 한 줄 추가 |
| `트러블슈팅.md` | 코드 검색 개선(~2026-08-18)의 서술형 상세 기록. **동결** | 갱신하지 않음 |
| `플로우.md` | 시스템 동작 흐름 | 구조가 바뀔 때 |

새 함정을 겪으면 **양쪽에 쓴다** — plan.md 의 해당 작업 절에 경위를, TROUBLESHOOTING.md 에 한 줄을.
같은 내용을 두 곳에 길게 복사하지 말 것(한쪽은 경위, 한쪽은 색인).

## 6. Project Structure Rules

현재 백엔드 구조 (이 형태를 유지할 것):

```
Back/
├─ .env               # 환경변수. Back/ 루트 고정 (config.py의 load_dotenv 기준)
├─ requirements.txt
└─ app/
   ├─ main.py         # FastAPI 인스턴스 + 미들웨어 + include_router 만
   ├─ config.py       # 환경변수 로딩
   ├─ api/            # 라우터
   ├─ services/       # 비즈니스 로직 / 외부 API 연동
   ├─ schemas/        # 요청·응답 모델
   └─ templates/      # 백엔드가 직접 서빙하는 HTML (관리자 페이지 등)
```

새 파일을 만들 때 아래 규칙을 따를 것:

- API 엔드포인트 → `app/api/{기능명}.py` (`APIRouter`로 작성 후 main.py에서 include만 추가. main.py에 엔드포인트 직접 정의 금지)
- 비즈니스 로직/외부 API 연동 → `app/services/{기능명}.py`
- 요청/응답 데이터 모델 → `app/schemas/schemas.py` (기능이 많아지면 schemas/ 안에서 파일 분리)
- 벡터DB/청킹/임베딩 관련 로직 → `app/core/`
- 백엔드가 서빙하는 HTML → `app/templates/{기능명}.html` (의존성 없는 단독 파일. 사용자용 화면은 Front/에)
- 테스트 코드 → `tests/test_{대상파일명}.py`
- import는 `app.` 으로 시작하는 절대 경로 사용 (상대 import 금지)
- 새로운 종류의 파일이라 위 규칙에 안 맞으면, 임의로 만들지 말고 어디에 둘지 먼저 물어볼 것

## 7. 특정 저장소에 기대지 말 것

이 서비스는 **임의의 GitHub 저장소**를 받는다. `jjunyuongv/Air`·`jjunyuongv/marryday` 는
검색 품질을 재려고 넣어 둔 **테스트/검수 대상일 뿐이고 언제든 교체된다.**

- 프로덕션 코드(`app/` 전체)에 저장소 이름·소유자·URL 을 **쓰지 않는다.**
  분기·상수·기본값·예외 처리 어디에도 넣지 않는다
- 동작은 항상 인자로 받은 식별자로 한다 — `snapshot_id`, `(owner, name)`, `repo_id`.
  "이 저장소는 이러니까" 라는 판단이 코드에 들어가면 다른 저장소에서 틀린다
- 언어·규모에 따라 다르게 동작해야 한다면 **그 속성**으로 분기한다
  (예: `language == "css"`, 청크 수, 파일 크기). 저장소 이름으로 분기하지 않는다
- **주석도 마찬가지다.** 실측 근거를 남길 때 저장소 이름 대신 성격으로 적는다
  ("Java 저장소", "3D 에셋이 든 큰 저장소"). 어느 저장소에서 잰 수치인지는 plan.md 에 남긴다

저장소 이름을 적어도 되는 곳은 **`tests/`(평가셋·픽스처)와 `plan.md`(측정 기록)뿐이다.**
평가셋을 늘릴 때도 `tests/search_eval_dataset.py` 의 `EVAL_SETS` 에만 추가한다.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes — while trivial tasks proceed without unnecessary back-and-forth.