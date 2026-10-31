# lstack

Lapis0875의 에이전트 스킬 스택. omp에서 쓰던 스킬셋을 Codex 등 다른 환경(원격 PC 포함)에서 동일하게 재현하기 위한 저장소다.

- `skills/` — 직접 작성한 스킬 (이 저장소에 포함)
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

### 2. 외부 스킬

```bash
npx skills add mattpocock/skills --skill grilling
npx skills add cathrynlavery/diagram-design
npx skills add epoko77-ai/im-not-ai --skill humanize-korean
npx skills add jakubkrehel/make-interfaces-feel-better
```

## 포함 스킬 (`skills/`)

| 스킬 | 용도 | 의존 |
|---|---|---|
| `make-it-like-korean` | 한국어 실무 문서·UI 문구의 번역투·AI 관용구 제거, 원문 문체 유지 | — |
| `idea-validation` | 프로젝트·캡스톤 아이디어 검증: grill 질문, 시장·경쟁 조사, MVP 범위, 레드팀 | `grilling` |

## 외부 스킬

| 스킬 | 용도 | 출처 | 라이선스 |
|---|---|---|---|
| `grilling` | 계획·결정을 라운드 단위 질문으로 스트레스 테스트 | [mattpocock/skills](https://github.com/mattpocock/skills) → `skills/productivity/grilling` | 원저장소 참조 |
| `diagram-design` | 아키텍처·플로우·ERD·차트 등 다이어그램을 HTML/SVG/PNG로 생성 | [cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design) | MIT |
| `humanize-korean` | 긴 한국어 산문의 AI 티 제거, 변경률 측정·정량 게이트 포함 | [epoko77-ai/im-not-ai](https://github.com/epoko77-ai/im-not-ai) → `codex/skills/humanize-korean` | 원저장소 참조 |
| `make-interfaces-feel-better` | 애니메이션·타이포그래피·아이콘·hover 등 UI 디테일 개선 | [jakubkrehel/make-interfaces-feel-better](https://github.com/jakubkrehel/make-interfaces-feel-better) | MIT |

## 의도적으로 제외한 것

- `figma-*` 14종 — Codex에서는 공식 Figma 플러그인(`openai-curated/figma`)이 동일 스킬을 제공한다.
- omp 전용 서브에이전트(`ui-designer`, `slide-designer`)에 의존하는 스킬 — 다른 환경에서 그대로 동작하지 않아 제외.
