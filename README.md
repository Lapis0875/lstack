# lstack

Lapis0875의 에이전트 스킬 스택. omp에서 쓰던 스킬셋을 Codex 등 다른 환경(원격 PC 포함)에서 동일하게 재현하기 위한 저장소다.

- `skills/` — 직접 작성한 스킬 (이 저장소에 포함)
- `codex/` — Codex 전용 보조 자산 (hook 등). 스킬과 달리 `npx skills add`로 설치되지 않는다
- `profiles/` — 외부 스킬용 개인 설정 (예: `diagram-design` 스타일 프로필). 스킬 본문은 포함하지 않는다
- 아래 **외부 스킬** 표 — 서드파티 스킬의 출처와 설치 명령 (본문은 각 원저장소에서 받는다)

## 설치

### 1. 이 저장소의 스킬

```bash
npx skills add Lapis0875/lstack
```

또는 수동 설치 (Codex는 `~/.agents/skills`, Claude Code는 `~/.claude/skills`를 읽는다):

```bash
git clone https://github.com/Lapis0875/lstack.git
ln -s "$PWD/lstack/skills/"* ~/.agents/skills/
```

`plan-loop`의 Codex hook(계획 단계 읽기 전용 강제, 미완료 작업이 있으면 멈춤 차단)은 선택 사항이다. 체크아웃한 저장소에서 실행한다:

```bash
python3 codex/plan-loop/install.py          # 변경 예정 내용만 출력
python3 codex/plan-loop/install.py --apply  # ~/.codex/hooks.json 백업 후 핸들러 추가
```

### 2. 외부 스킬

```bash
npx skills add mattpocock/skills --skill grilling
npx skills add cathrynlavery/diagram-design
npx skills add epoko77-ai/im-not-ai --skill humanize-korean
npx skills add jakubkrehel/make-interfaces-feel-better
npx skills add Nutlope/hallmark
npx skills add wheresryan22/anatomy
npx skills add nextlevelbuilder/ui-ux-pro-max-skill
npx skills add Jakeschincariol/replica-skill
npx skills add lucasmarkes/hairline
npx skills add benjitaylor/skills --skill stageshow
```

### 3. 외부 스킬 설정 (`profiles/`)

`diagram-design` 스타일 프로필은 `~/.diagram-design/profiles/`에 두면 스킬 업데이트와 무관하게 유지된다. 프로젝트에서 쓰려면 프로젝트 루트에 `.diagram-design` 파일(`profile: <slug>` 한 줄)을 만든다.

```bash
mkdir -p ~/.diagram-design/profiles
cp lstack/profiles/diagram-design/*.md ~/.diagram-design/profiles/
echo "profile: ax-study" > <project-root>/.diagram-design   # 또는 nypc
```

| 프로필 | 스킨 | 출처 |
|---|---|---|
| `ax-study` | Paper & Ink: 따뜻한 종이색, 차콜 잉크, 크림슨 강조 1색. Noto Serif KR / Noto Sans KR / DM Mono | AX Study 발표 자료 `DESIGN.md` 토큰 |
| `nypc` | NYPC 사이트 팔레트: CTA 빨강 강조, CTA 파랑 링크 | https://www.nypc.co.kr |

## 포함 스킬 (`skills/`)

| 스킬 | 용도 | 의존 |
|---|---|---|
| `make-it-like-korean` | 한국어 실무 문서·UI 문구의 번역투·AI 관용구 제거, 원문 문체 유지 | — |
| `idea-validation` | 프로젝트·캡스톤 아이디어 검증: grill 질문, 시장·경쟁 조사, MVP 범위, 레드팀 | `grilling` |
| `hackathon-plan` | 문제가 정해진 해커톤에서 30분 안에 API 계약·필수 인수 시나리오(`TEST-PLAN.md`)·워커 브리프를 작성. 설계 단계에서 요구사항별 사전조건·실행 절차·기대 결과를 고정하고 Implementer→Tester→Reviewer가 같은 기준으로 구현·실행·검토. `hackathon-be-spring`·`hackathon-fe-vite` 보일러플레이트 전제 | — |
| `openai-dev-team` | OpenAI 모델만 쓰는 에이전트 개발 팀: Orchestrator(GPT-6 Astra, 대체 Sol high; architect 역할로 구현 전 필수 인수 시나리오 작성)·Implementer(GPT-6.1 Terra, 대체 Sol medium; 테스트 코드 작성)·Reviewer(GPT-6.1 Sol high)·Tester(GPT-6 Luna medium; 시나리오별 실행 증거 기록) | — |
| `plan-loop` | omp의 plan mode·todo·goal 루프를 옮긴 계획→실행 하네스. `plan` 모드는 읽기 전용 조사 후 `plan/<slug>.md`를 쓰고 승인을 기다리며, References 칸은 저장소의 Context7 참조 팩(`docs/refs/`)에서 버전이 맞는 문서를 고정한다. `run` 모드는 작업별 검증·증거 기록과 최종 스모크까지 이어서 실행. Codex hook 선택 설치(`codex/plan-loop/`) | — |

## 외부 스킬

| 스킬 | 용도 | 출처 | 라이선스 |
|---|---|---|---|
| `grilling` | 계획·결정을 라운드 단위 질문으로 스트레스 테스트 | [mattpocock/skills](https://github.com/mattpocock/skills) → `skills/productivity/grilling` | 원저장소 참조 |
| `diagram-design` | 아키텍처·플로우·ERD·차트 등 다이어그램을 HTML/SVG/PNG로 생성 | [cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design) | MIT |
| `humanize-korean` | 긴 한국어 산문의 AI 티 제거, 변경률 측정·정량 게이트 포함 | [epoko77-ai/im-not-ai](https://github.com/epoko77-ai/im-not-ai) → `codex/skills/humanize-korean` | 원저장소 참조 |
| `make-interfaces-feel-better` | 애니메이션·타이포그래피·아이콘·hover 등 UI 디테일 개선 | [jakubkrehel/make-interfaces-feel-better](https://github.com/jakubkrehel/make-interfaces-feel-better) | MIT |
| `hallmark` | Anti-AI-slop 디자인: 새 페이지/앱 빌드, `audit`, `redesign`, URL·스크린샷에서 디자인 DNA 추출(`study`) | [Nutlope/hallmark](https://github.com/Nutlope/hallmark) · https://usehallmark.com | MIT |
| `anatomy` | 기계·시스템을 설명하는 상세 인터랙티브 아이소메트릭 SVG 일러스트 생성 (선택적 WebGL·3D 효과), 문서·랜딩·인터랙티브 설명용 | [wheresryan22/anatomy](https://github.com/wheresryan22/anatomy) | MIT |
| `ui-ux-pro-max` | 웹·모바일·데스크톱 UI/UX 설계 인텔리전스: 제품·플랫폼별 UX 가이드, 접근성, 반응형, 타이포·컬러, 스택별 구현 권고 | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | MIT |
| `replica-*` (11종) | 앱 클론 파이프라인: `recon`(공개 정보로 화면·플로우·데이터 모델 리콘) → `architect` → `design` → `build` → `backend` → `test` → `diff`(원본 대비 패리티 점수) → `entrepreneur`(실제 리뷰 기반 개선점) → `brand`(리브랜딩·잔재 스윕) → `launch` → `deploy`. 기능·UX만 클린룸으로 재구현, 코드·에셋·카피 복제 금지. 도구는 Python 3.8+ 표준 라이브러리만 사용 | [Jakeschincariol/replica-skill](https://github.com/Jakeschincariol/replica-skill) | MIT |
| `hairline-create` | 아이디어 하나로 포인터에 반응하는 아이소메트릭 라인 피겨를 의존성 없는 단일 HTML로 생성. `@lucasmarkes/hairline` 엔진 위에서 10가지 규칙 검증 + 브라우저 체크 | [lucasmarkes/hairline](https://github.com/lucasmarkes/hairline) → `skills/hairline-create` · https://hairline.lucasmarkes.com | MIT |
| `hairline-adopt` | 기존 SVG(아이콘·로고·일러스트)를 읽어 비례·부품을 유지한 Hairline 피겨로 재구성하고 포인터 제스처를 제안 | [lucasmarkes/hairline](https://github.com/lucasmarkes/hairline) → `skills/hairline-adopt` | MIT |
| `stageshow` | 실제 제품처럼 보이는 faux UI(앱·브라우저 창, 폰, 대시보드, 벤토 카드)와 커서 워크스루 애니메이션을 React·CSS로 제작. 랜딩 히어로·기능 카드·문서용. `kit/`(React 18+, 애니메이션 런타임 의존 없음)과 `examples/` 포함. omp `ui-designer`가 자동 로드 | [benjitaylor/skills](https://github.com/benjitaylor/skills) → `stageshow` | MIT |

## 디자인 레퍼런스

omp `ui-designer` 에이전트 정의의 "Design references" 섹션을 그대로 옮긴 것. 작업 순서는 레이아웃/플로우 → 토큰 → 컴포넌트 → 모션이며, 브리프·브랜드 가이드·기존 `DESIGN.md`·프로젝트 디자인 시스템이 항상 레퍼런스보다 우선한다. 제품 유형과 무드에 맞는 사이트를 2~3개만 고른다.

열 의미: **Page** = 전체 페이지/플로우, **Comp** = 컴포넌트/섹션, **Brand** = 브랜드 시스템·아이덴티티·에셋, **Anti-slop** = 에이전트에 AI 티 나는 결과물을 막는 구체적 규칙·토큰·감사 제공.

출처: https://www.threads.com/@escape.salary/post/DeJPtzAE-2E, https://subsequent-paw-3ac.notion.site/AI-17-3ecced0d5b0280fc91f2f09252dd50bb (Ellie Co. Studio), Instagram 게시물 DdwvHWVG5z9, DdbxUiqk-MZ, DeQ5WKekcqs, DePQQZrjPJW, DdveM-dDrFx, Dd35hA1k8s8, Ddqj0svm6yq, DePBMFZiGkO, Ddc429ck7PO, DdgwETfDMOT (`https://www.instagram.com/p/<id>/`).

### 전체 페이지·플로우
| Site | URL | Page | Comp | Brand | Anti-slop | Tags |
|---|---|---|---|---|---|---|
| Mobbin | https://mobbin.com | ✓ | ✓ | | | shipped app/web screens, end-to-end flows, UI patterns |
| Refero | https://refero.design | ✓ | | | | web/iOS screens and flows searchable by purpose |
| Minimal Gallery | https://minimal.gallery | ✓ | | | | minimal, premium; whitespace and type rhythm |
| Land-book | https://land-book.com | ✓ | ✓ | | | landings; sections, mobile, OG images |
| One Page Love | https://onepagelove.com | ✓ | ✓ | | | single-page sites; section examples |
| Awwwards | https://www.awwwards.com | ✓ | | | | jury-picked art direction, interaction, motion; check usability separately |
| Godly | https://godly.design | ✓ | | | | cutting-edge sites; screenshot as layout target |
| Curated | https://curated.design | ✓ | | | | live sites by industry and style |
| Site of Sites | https://siteofsites.co | ✓ | | | | ~600 sites; industry/style/platform filters |
| Dark Design | https://dark.design | ✓ | | | | dark UI by industry |
| Dark Mode Design | https://darkmodedesign.com | ✓ | | | | dark UI accents and type sizes |
| 3D Websites | https://3dwebsites.design | ✓ | | | | 3D web |
| Internet Gems | https://ilovecreatives.com/internet-gems | ✓ | | ✓ | | websites, emails, 3D |
| Pafolios | https://pafolios.com | ✓ | | | | portfolios, case studies |

### 컴포넌트·모션
| Site | URL | Page | Comp | Brand | Anti-slop | Tags |
|---|---|---|---|---|---|---|
| shadcn/ui | https://ui.shadcn.com | | ✓ | | | React/Tailwind primitives copied as owned source |
| Component Gallery | https://component.gallery | | ✓ | | | anatomy, naming, states across design systems; any stack |
| 21st.dev | https://21st.dev | | ✓ | | | 12,000+ React/shadcn blocks, templates, themes |
| Craftwork | https://craftwork.design | ✓ | ✓ | | | website gallery, UI kits, assets |
| Three UI | https://threeui.com | ✓ | ✓ | | | Three.js landings, heroes, shaders |
| The Design Stack | https://thedesignstack.co.in | | ✓ | | | Figma components, interaction prompts |
| Unlumen UI | https://ui.unlumen.com | | ✓ | | | motion components |
| Balsa | https://balsa-ui.com | | ✓ | | | design system → agent-usable component registry |
| App Motion | https://appmotion.design | | ✓ | | | mobile app motion patterns |
| Aceternity UI | https://ui.aceternity.com | | ✓ | | | motion; bold heroes, background effects |
| Magic UI | https://magicui.design | | ✓ | | | motion; SaaS landing details (ticker, marquee, globe) |
| Motion Primitives | https://motion-primitives.com | | ✓ | | | motion; restrained product-UI polish |
| transitions.dev | https://transitions.dev | | ✓ | | ✓ | motion; copy-paste transitions plus agent skill |
| Anime.js | https://animejs.com | | | | | motion library; framework-agnostic timelines, SVG |
| Springs Studio | https://springs.studio | | | | | motion tokens (easings) previewed on real UI |
| Animos | https://animos.app | | | | | motion; design showcase/launch video export |

### 브랜드 시스템·타이포·에셋
| Site | URL | Page | Comp | Brand | Anti-slop | Tags |
|---|---|---|---|---|---|---|
| Refero Styles | https://styles.refero.design | | | ✓ | ✓ | 2,000+ real products' color/type/spacing; DESIGN.md download |
| DESIGNmd | https://designmd.ai | | | | ✓ | community DESIGN.md systems when no brand exists |
| getdesign.md / Awesome DESIGN.md | https://getdesign.md, https://github.com/VoltAgent/awesome-design-md | ✓ | | ✓ | ✓ | big-brand DESIGN.md token files |
| deck.gallery | https://deck.gallery | | | ✓ | | real pitch decks, brand guideline decks |
| Meshfont | https://meshfont.com | | | ✓ | | type; custom font in browser |
| Tegaki | https://gkurt.com/tegaki | | | | | type, motion; stroke-by-stroke handwriting animation |
| Endless Tools | https://endlesstools.io | | | ✓ | | 3D assets, brand visuals |
| Morflax Studio | https://studio.morflax.com | | | ✓ | | 3D mockups, motion assets |
| Creatoom | https://creatoom.com | | | ✓ | | packaging and device mockups |
| Iconly Pro | https://iconly.pro | | | | | icons (flat, 3D, animated) |

### Anti-AI-slop 규칙·에이전트 도구
| Site | URL | Page | Comp | Brand | Anti-slop | Tags |
|---|---|---|---|---|---|---|
| Taste Skill | https://tasteskill.dev | | | | ✓ | 역할은 `hallmark`로 대체 |
| Design Skills | https://designskills.dev | | | | ✓ | 230+ 스타일별 스킬 카탈로그 |
| Hallmark | https://usehallmark.com | | | | ✓ | `hallmark` 스킬: build, audit, redesign, study |
| Anti Slop | https://github.com/miqdadbadjuber/anti-slop | | | | ✓ | 역할은 `hallmark`로 대체 |
| Vercel Web Interface Guidelines | https://vercel.com/design/guidelines | | | | ✓ | 접근성·폼·모션·타이포 규칙 (MIT, https://github.com/vercel-labs/web-interface-guidelines) |
| Playwright CLI | https://github.com/microsoft/playwright-cli | | | | | agent browser QA |
| agent-browser | https://github.com/vercel-labs/agent-browser | | | | | agent browser QA |
| A/B Test | https://abtest.design | | | | | UX data; app A/B test results (Mobbin) |

### 사용 규칙
- 페이지: 앱/웹 제품은 Mobbin·Refero 플로우부터. 첫 화면이 아니라 플로우 전체를 비교하고, 데스크톱·모바일 전체 페이지 스크린샷에서 섹션 순서·그리드·최대 폭·여백·타입 스케일·이미지 처리·nav/footer를 추출해 레이아웃 목표로 삼는다.
- 토큰: 새 비주얼 방향은 2~3개 후보를 제시한다. 선택된 DESIGN.md는 프로젝트 루트 `DESIGN.md`로 저장(기존 파일은 허가 없이 덮어쓰지 않음)하고 컴포넌트 리터럴이 아니라 토큰 레이어에 매핑한다.
- 컴포넌트: 프로젝트 컴포넌트 재사용 우선. 구조·상태가 불분명하면 `https://component.gallery/components/<name>/`. React+Tailwind면 shadcn/ui(`npx shadcn@latest add <component>`, 기존 프로젝트는 `--dry-run` 먼저), 마케팅 블록은 21st.dev. 다른 스택은 구조·상태만 이식하고 React/Tailwind를 추가하지 않는다.
- 모션: 기존 애니메이션 라이브러리가 있으면 그것만 쓴다. 과감한 히어로 → Aceternity(`npx shadcn@latest add @aceternity/<component>`), SaaS 디테일 → Magic UI(`@magicui/<component>`), 절제된 제품 폴리시 → Motion Primitives(`npx motion-primitives@latest add <component>`), 비-React/커스텀 타임라인 → Anime.js. 뷰당 시그니처 효과 하나, `transform`/`opacity`만 애니메이션, `prefers-reduced-motion` 존중.
- 구조·리듬·토큰만 빌린다. 콘텐츠·로고·브랜드 에셋·이미지·소스를 그대로 복사하지 않으며, 폰트·아이콘·목업·3D 에셋은 다운로드 전 라이선스를 확인한다.

## 의도적으로 제외한 것

- `figma-*` 14종 — Codex에서는 공식 Figma 플러그인(`openai-curated/figma`)이 동일 스킬을 제공한다.
- omp 전용 서브에이전트(`ui-designer`, `slide-designer`)에 의존하는 스킬 — 다른 환경에서 그대로 동작하지 않아 제외.

## 라이선스

`skills/` 아래 직접 작성한 스킬과 이 README는 [MIT](LICENSE). 외부 스킬은 각 원저장소의 라이선스를 따른다.
