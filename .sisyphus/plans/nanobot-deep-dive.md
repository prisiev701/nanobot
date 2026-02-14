# Nanobot 핵심 코드 분석 계획서

## TL;DR

> **목표**: Nanobot의 핵심 아키텍처를 완전히 이해하고, 새로운 도구/기능을 추가할 수 있는 수준까지 도달
> 
> **산출물**:
> - 아키텍처 분석 문서 (이 파일의 하위 섹션)
> - 핵심 코드 주석 해설
> - 실습 가이드 (새 도구 추가)
> 
> **예상 소요**: 1-2시간 (읽기 + 실습)

---

## 1. 프로젝트 개요

### 1.1 Nanobot이란?

Nanobot은 **~4,000줄**의 초경량 개인 AI 어시스턴트입니다. Clawdbot(430k+ 줄)의 99% 축소판으로, 핵심 기능만 담고 있어 연구/학습에 최적화되어 있습니다.

### 1.2 기술 스택

| 영역 | 기술 |
|------|------|
| **언어** | Python 3.11+ |
| **CLI** | Typer |
| **LLM** | LiteLLM (OpenRouter, Anthropic, OpenAI, Gemini 지원) |
| **설정** | Pydantic |
| **로깅** | Loguru |
| **채널** | Telegram (python-telegram-bot), WhatsApp (Node.js Bridge) |

### 1.3 디렉토리 구조

```
nanobot/
├── agent/          # 핵심 에이전트 로직
│   ├── loop.py     # 메인 처리 루프 (OODA)
│   ├── context.py  # 프롬프트 빌더
│   ├── memory.py   # 지속성 메모리
│   ├── skills.py   # 스킬 로더
│   ├── subagent.py # 백그라운드 태스크
│   └── tools/      # 도구 시스템
├── bus/            # 비동기 메시지 버스
├── channels/       # Telegram, WhatsApp 통합
├── config/         # 설정 스키마 및 로더
├── providers/      # LLM 프로바이더 추상화
├── session/        # 대화 세션 관리
├── skills/         # 번들 스킬 (SKILL.md 형식)
├── cron/           # 스케줄 작업
└── cli/            # CLI 명령어
```

---

## 2. 학습 로드맵

### Phase 1: 기초 이해 (Entry Point → Agent Loop)

| 순서 | 파일 | 학습 목표 |
|------|------|----------|
| 1 | `cli/commands.py` | CLI 진입점, Typer 데코레이터 |
| 2 | `agent/loop.py` | 핵심 OODA 루프 이해 |
| 3 | `agent/context.py` | 프롬프트 구성 방식 |

### Phase 2: 도구 시스템 (Tool System)

| 순서 | 파일 | 학습 목표 |
|------|------|----------|
| 4 | `agent/tools/base.py` | Tool 추상 클래스 |
| 5 | `agent/tools/registry.py` | 도구 등록/실행 패턴 |
| 6 | `agent/tools/filesystem.py` | 실제 도구 구현 예시 |

### Phase 3: 통합 시스템 (Integration)

| 순서 | 파일 | 학습 목표 |
|------|------|----------|
| 7 | `providers/litellm_provider.py` | LLM 추상화 |
| 8 | `bus/queue.py` | 비동기 메시지 라우팅 |
| 9 | `channels/telegram.py` | 채널 통합 예시 |

### Phase 4: 확장 실습

| 순서 | 실습 | 목표 |
|------|------|------|
| 10 | 새 Tool 추가 | `DiceRollTool` 구현 |
| 11 | 새 Skill 추가 | `calculator` 스킬 작성 |

---

## 3. 핵심 아키텍처 분석

### 3.1 전체 데이터 흐름

```
[사용자] 
    ↓ (Telegram/WhatsApp/CLI)
[Channel] 
    ↓ InboundMessage
[MessageBus] ←→ [AgentLoop]
    ↓                ↓
[ContextBuilder] + [ToolRegistry]
    ↓                ↓
[LiteLLMProvider] → [LLM API]
    ↓
[OutboundMessage]
    ↓
[Channel] → [사용자]
```

### 3.2 핵심 컴포넌트 관계

```
AgentLoop (오케스트레이터)
    ├── MessageBus (입출력)
    ├── ContextBuilder (프롬프트)
    │       ├── MemoryStore (장기 기억)
    │       └── SkillsLoader (스킬)
    ├── ToolRegistry (도구)
    │       ├── ReadFileTool
    │       ├── WriteFileTool
    │       ├── ExecTool
    │       ├── WebSearchTool
    │       └── SpawnTool
    ├── SessionManager (대화 이력)
    ├── SubagentManager (백그라운드)
    └── LLMProvider (AI 호출)
```

---

## 4. 상세 코드 분석

> 각 섹션은 별도 노트패드 파일로 작성됩니다.
> - `.sisyphus/notepads/nanobot-deep-dive/01-agent-loop.md`
> - `.sisyphus/notepads/nanobot-deep-dive/02-tool-system.md`
> - `.sisyphus/notepads/nanobot-deep-dive/03-provider-bus.md`
> - `.sisyphus/notepads/nanobot-deep-dive/04-extension-guide.md`

---

## 5. 성공 기준

- [ ] AgentLoop의 `_process_message` 흐름을 설명할 수 있다
- [ ] Tool 추상 클래스의 필수 메서드를 나열할 수 있다
- [ ] 새로운 Tool을 추가하는 절차를 수행할 수 있다
- [ ] LiteLLMProvider가 지원하는 모델을 설정할 수 있다
- [ ] Skill을 작성하여 에이전트에 로드할 수 있다
