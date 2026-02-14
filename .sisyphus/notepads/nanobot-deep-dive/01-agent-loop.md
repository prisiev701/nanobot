# Agent Loop 상세 분석

> 파일: `nanobot/agent/loop.py`

## 1. 개요

`AgentLoop`는 Nanobot의 **핵심 엔진**입니다. 군사 전략에서 사용하는 OODA 루프(Observe-Orient-Decide-Act)를 구현하여 메시지를 받고, 생각하고, 행동하고, 응답하는 사이클을 반복합니다.

## 2. 클래스 구조

```python
class AgentLoop:
    """
    에이전트 루프는 핵심 처리 엔진입니다.
    
    1. 버스에서 메시지를 수신
    2. 이력, 메모리, 스킬로 컨텍스트 구축
    3. LLM 호출
    4. 도구 호출 실행
    5. 응답 전송
    """
```

### 2.1 초기화 (`__init__`)

```python
def __init__(
    self,
    bus: MessageBus,           # 비동기 메시지 버스
    provider: LLMProvider,     # LLM 프로바이더 (LiteLLM)
    workspace: Path,           # 작업 공간 경로
    model: str | None = None,  # 사용할 모델 (기본값: provider 설정)
    max_iterations: int = 20,  # 도구 호출 최대 반복 횟수
    brave_api_key: str | None = None  # 웹 검색 API 키
):
```

**핵심 컴포넌트 초기화:**

```python
self.context = ContextBuilder(workspace)   # 프롬프트 빌더
self.sessions = SessionManager(workspace)  # 세션 관리자
self.tools = ToolRegistry()                # 도구 레지스트리
self.subagents = SubagentManager(...)      # 서브에이전트 관리자
```

### 2.2 도구 등록 (`_register_default_tools`)

```python
def _register_default_tools(self) -> None:
    """기본 도구 세트를 등록합니다."""
    # 파일 도구
    self.tools.register(ReadFileTool())
    self.tools.register(WriteFileTool())
    self.tools.register(EditFileTool())
    self.tools.register(ListDirTool())
    
    # 쉘 도구
    self.tools.register(ExecTool(working_dir=str(self.workspace)))
    
    # 웹 도구
    self.tools.register(WebSearchTool(api_key=self.brave_api_key))
    self.tools.register(WebFetchTool())
    
    # 메시지 도구
    self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
    
    # 스폰 도구 (서브에이전트)
    self.tools.register(SpawnTool(manager=self.subagents))
```

## 3. 메인 루프 (`run`)

```python
async def run(self) -> None:
    """에이전트 루프를 실행하여 버스에서 메시지를 처리합니다."""
    self._running = True
    logger.info("Agent loop started")
    
    while self._running:  # 무한 루프
        try:
            # 1. 인바운드 큐에서 메시지 대기 (최대 1초)
            msg = await asyncio.wait_for(
                self.bus.consume_inbound(),
                timeout=1.0
            )
            
            # 2. 메시지 처리
            try:
                response = await self._process_message(msg)
                if response:
                    await self.bus.publish_outbound(response)
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                # 에러 응답 전송
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"Sorry, I encountered an error: {str(e)}"
                ))
        except asyncio.TimeoutError:
            continue  # 타임아웃 시 다음 루프로
```

### 핵심 포인트:
- `while self._running`: 에이전트가 종료될 때까지 무한 반복
- `asyncio.wait_for(..., timeout=1.0)`: 1초마다 타임아웃으로 종료 시그널 확인
- 에러 발생 시에도 사용자에게 친절한 에러 메시지 전송

## 4. 메시지 처리 (`_process_message`)

이것이 실제 "생각"이 일어나는 핵심 메서드입니다.

```python
async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
    # 1. 세션 가져오기/생성
    session = self.sessions.get_or_create(msg.session_key)
    
    # 2. 도구 컨텍스트 업데이트 (채널/채팅 정보)
    message_tool = self.tools.get("message")
    if isinstance(message_tool, MessageTool):
        message_tool.set_context(msg.channel, msg.chat_id)
    
    # 3. 초기 메시지 목록 구성
    messages = self.context.build_messages(
        history=session.get_history(),
        current_message=msg.content,
        media=msg.media if msg.media else None,
    )
    
    # 4. 에이전트 루프 (도구 호출 반복)
    iteration = 0
    final_content = None
    
    while iteration < self.max_iterations:  # 최대 20회
        iteration += 1
        
        # LLM 호출
        response = await self.provider.chat(
            messages=messages,
            tools=self.tools.get_definitions(),
            model=self.model
        )
        
        # 도구 호출이 있으면 실행
        if response.has_tool_calls:
            # 어시스턴트 메시지 추가 (도구 호출 포함)
            messages = self.context.add_assistant_message(
                messages, response.content, tool_call_dicts
            )
            
            # 각 도구 실행
            for tool_call in response.tool_calls:
                result = await self.tools.execute(
                    tool_call.name, 
                    tool_call.arguments
                )
                messages = self.context.add_tool_result(
                    messages, tool_call.id, tool_call.name, result
                )
        else:
            # 도구 호출 없음 → 최종 응답
            final_content = response.content
            break
    
    # 5. 세션에 저장
    session.add_message("user", msg.content)
    session.add_message("assistant", final_content)
    self.sessions.save(session)
    
    # 6. 응답 반환
    return OutboundMessage(
        channel=msg.channel,
        chat_id=msg.chat_id,
        content=final_content
    )
```

### 핵심 흐름 다이어그램:

```
사용자 메시지 도착
       ↓
[ContextBuilder] → 시스템 프롬프트 + 이력 + 현재 메시지
       ↓
[LLM 호출] ← tools 스키마 전달
       ↓
  ┌─────────────────────────────────┐
  │ response.has_tool_calls == True?│
  └─────────────────────────────────┘
       │ Yes              │ No
       ↓                  ↓
[도구 실행]          [최종 응답]
       ↓                  ↓
  결과 추가           세션 저장
       ↓                  ↓
  다시 LLM 호출      OutboundMessage
```

## 5. 시스템 메시지 처리 (`_process_system_message`)

서브에이전트가 완료되면 `system` 채널을 통해 결과를 보고합니다.

```python
async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
    # chat_id 형식: "원본채널:원본채팅ID"
    if ":" in msg.chat_id:
        parts = msg.chat_id.split(":", 1)
        origin_channel = parts[0]
        origin_chat_id = parts[1]
    
    # 원본 세션 컨텍스트로 처리
    session_key = f"{origin_channel}:{origin_chat_id}"
    # ... 나머지는 _process_message와 유사
```

## 6. 직접 처리 (`process_direct`)

CLI에서 직접 호출할 때 사용하는 헬퍼 메서드입니다.

```python
async def process_direct(self, content: str, session_key: str = "cli:direct") -> str:
    """CLI 사용을 위해 메시지를 직접 처리합니다."""
    msg = InboundMessage(
        channel="cli",
        sender_id="user",
        chat_id="direct",
        content=content
    )
    
    response = await self._process_message(msg)
    return response.content if response else ""
```

## 7. 핵심 개념 요약

| 개념 | 설명 |
|------|------|
| **OODA 루프** | Observe(메시지 수신) → Orient(컨텍스트 구축) → Decide(LLM 호출) → Act(도구 실행/응답) |
| **반복 실행** | 도구 호출이 있으면 최대 20회까지 LLM-도구 사이클 반복 |
| **세션 관리** | 대화 이력을 세션 단위로 저장하여 연속성 유지 |
| **비동기 처리** | `async/await`로 블로킹 없이 여러 메시지 동시 처리 가능 |

## 8. 확장 포인트

새로운 기능을 추가하려면:

1. **새 도구 추가**: `_register_default_tools()`에 `self.tools.register(MyTool())` 추가
2. **도구 호출 횟수 변경**: `max_iterations` 파라미터 조정
3. **전처리/후처리**: `_process_message()` 시작/끝에 로직 추가
