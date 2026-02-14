# Provider & Bus 시스템 분석

## 1. LLM Provider 시스템

> 파일: `nanobot/providers/`

### 1.1 개요

Nanobot은 **LiteLLM**을 사용하여 다양한 LLM 서비스를 통일된 인터페이스로 사용합니다.

```
┌─────────────────────────────────────────────────┐
│                LiteLLMProvider                   │
│  (통일된 인터페이스)                               │
└─────────────────────────────────────────────────┘
         │           │           │           │
         ↓           ↓           ↓           ↓
    ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
    │OpenRouter│ │Anthropic│ │ OpenAI │  │ Gemini │
    └────────┘  └────────┘  └────────┘  └────────┘
```

### 1.2 Base Provider (`base.py`)

```python
# nanobot/providers/base.py

from dataclasses import dataclass

@dataclass
class ToolCallRequest:
    """도구 호출 요청 데이터."""
    id: str
    name: str
    arguments: dict

@dataclass
class LLMResponse:
    """LLM 응답 데이터."""
    content: str | None
    tool_calls: list[ToolCallRequest] = None
    finish_reason: str = "stop"
    usage: dict = None
    
    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(ABC):
    """LLM 프로바이더 추상 클래스."""
    
    def __init__(self, api_key: str | None, api_base: str | None):
        self.api_key = api_key
        self.api_base = api_base
    
    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        pass
    
    @abstractmethod
    def get_default_model(self) -> str:
        pass
```

### 1.3 LiteLLM Provider (`litellm_provider.py`)

```python
# nanobot/providers/litellm_provider.py

class LiteLLMProvider(LLMProvider):
    """다중 프로바이더 지원을 위한 LiteLLM 기반 프로바이더."""
    
    def __init__(
        self, 
        api_key: str | None = None, 
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5"
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        
        # 프로바이더 자동 감지
        self.is_openrouter = (
            (api_key and api_key.startswith("sk-or-")) or
            (api_base and "openrouter" in api_base)
        )
        self.is_vllm = bool(api_base) and not self.is_openrouter
        
        # 환경 변수 설정 (프로바이더별)
        if api_key:
            if self.is_openrouter:
                os.environ["OPENROUTER_API_KEY"] = api_key
            elif "anthropic" in default_model:
                os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
            elif "gemini" in default_model.lower():
                os.environ.setdefault("GEMINI_API_KEY", api_key)
            # ... 기타 프로바이더
```

### 1.4 Chat 메서드 상세

```python
async def chat(
    self,
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> LLMResponse:
    model = model or self.default_model
    
    # 모델 접두사 자동 추가
    if self.is_openrouter and not model.startswith("openrouter/"):
        model = f"openrouter/{model}"
    
    if self.is_vllm:
        model = f"hosted_vllm/{model}"
    
    if "gemini" in model.lower() and not model.startswith("gemini/"):
        model = f"gemini/{model}"
    
    # LiteLLM 호출
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    
    try:
        response = await acompletion(**kwargs)
        return self._parse_response(response)
    except Exception as e:
        return LLMResponse(
            content=f"Error calling LLM: {str(e)}",
            finish_reason="error",
        )
```

### 1.5 지원 프로바이더

| 프로바이더 | 모델 접두사 | 환경 변수 |
|-----------|------------|----------|
| OpenRouter | `openrouter/` | `OPENROUTER_API_KEY` |
| Anthropic | `anthropic/` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai/`, `gpt-` | `OPENAI_API_KEY` |
| Gemini | `gemini/` | `GEMINI_API_KEY` |
| Groq | `groq/` | `GROQ_API_KEY` |
| vLLM (로컬) | `hosted_vllm/` | `OPENAI_API_KEY` (더미) |

---

## 2. Message Bus 시스템

> 파일: `nanobot/bus/`

### 2.1 개요

Message Bus는 **채널(Telegram, WhatsApp 등)**과 **에이전트**를 **분리(Decoupling)**하여 비동기 통신을 가능하게 합니다.

```
[Telegram] ──┐                  ┌── [Telegram]
             │   ┌──────────┐   │
[WhatsApp] ──┼──→│ MessageBus │──┼── [WhatsApp]
             │   │ (Queue)    │  │
[CLI]      ──┘   └──────────┘   └── [CLI]
                     ↑  ↓
                ┌──────────┐
                │ AgentLoop │
                └──────────┘
```

### 2.2 이벤트 모델 (`events.py`)

```python
# nanobot/bus/events.py

from dataclasses import dataclass

@dataclass
class InboundMessage:
    """채널 → 에이전트로 들어오는 메시지."""
    channel: str          # "telegram", "whatsapp", "cli"
    sender_id: str        # 발신자 ID
    chat_id: str          # 채팅방 ID
    content: str          # 메시지 내용
    media: list[str] | None = None  # 첨부 파일 경로
    
    @property
    def session_key(self) -> str:
        """세션 키 생성 (채널:채팅ID)."""
        return f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """에이전트 → 채널로 나가는 메시지."""
    channel: str          # 대상 채널
    chat_id: str          # 대상 채팅방
    content: str          # 응답 내용
    reply_to: str | None = None  # 회신 대상 메시지 ID
```

### 2.3 MessageBus (`queue.py`)

```python
# nanobot/bus/queue.py

class MessageBus:
    """비동기 메시지 라우팅 버스."""
    
    def __init__(self):
        self._inbound: asyncio.Queue = asyncio.Queue()
        self._outbound: asyncio.Queue = asyncio.Queue()
        self._outbound_callbacks: dict[str, Callable] = {}
    
    # ========== Inbound (채널 → 에이전트) ==========
    
    async def publish_inbound(self, msg: InboundMessage) -> None:
        """인바운드 큐에 메시지 추가."""
        await self._inbound.put(msg)
    
    async def consume_inbound(self) -> InboundMessage:
        """인바운드 큐에서 메시지 가져오기 (블로킹)."""
        return await self._inbound.get()
    
    # ========== Outbound (에이전트 → 채널) ==========
    
    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """아웃바운드 큐에 메시지 추가."""
        await self._outbound.put(msg)
    
    def subscribe_outbound(self, channel: str, callback: Callable) -> None:
        """특정 채널의 아웃바운드 콜백 등록."""
        self._outbound_callbacks[channel] = callback
    
    async def dispatch_outbound(self) -> None:
        """아웃바운드 큐 메시지를 적절한 채널로 전달."""
        while True:
            msg = await self._outbound.get()
            callback = self._outbound_callbacks.get(msg.channel)
            if callback:
                await callback(msg)
```

### 2.4 전체 메시지 흐름

```
1. 사용자가 Telegram에서 메시지 전송
        ↓
2. TelegramChannel이 InboundMessage 생성
        ↓
3. bus.publish_inbound(msg)
        ↓
4. AgentLoop가 bus.consume_inbound() 호출
        ↓
5. AgentLoop가 _process_message() 실행
        ↓
6. LLM 호출 + 도구 실행
        ↓
7. AgentLoop가 OutboundMessage 생성
        ↓
8. bus.publish_outbound(response)
        ↓
9. dispatch_outbound()가 콜백 실행
        ↓
10. TelegramChannel이 사용자에게 응답 전송
```

---

## 3. 설정 시스템

> 파일: `nanobot/config/`

### 3.1 스키마 (`schema.py`)

Pydantic을 사용한 타입-안전 설정:

```python
from pydantic import BaseModel

class ProviderConfig(BaseModel):
    api_key: str | None = None
    api_base: str | None = None

class ProvidersConfig(BaseModel):
    openrouter: ProviderConfig = ProviderConfig()
    anthropic: ProviderConfig = ProviderConfig()
    openai: ProviderConfig = ProviderConfig()
    gemini: ProviderConfig = ProviderConfig()
    groq: ProviderConfig = ProviderConfig()
    vllm: ProviderConfig = ProviderConfig()

class AgentDefaults(BaseModel):
    model: str = "anthropic/claude-opus-4-5"
    max_tool_iterations: int = 20

class Config(BaseModel):
    providers: ProvidersConfig = ProvidersConfig()
    agents: AgentsConfig = AgentsConfig()
    channels: ChannelsConfig = ChannelsConfig()
    tools: ToolsConfig = ToolsConfig()
```

### 3.2 설정 파일 위치

```
~/.nanobot/
├── config.json     # 메인 설정
├── bridge/         # WhatsApp 브릿지
└── data/           # 런타임 데이터
    └── cron/
        └── jobs.json
```

### 3.3 설정 예시 (`~/.nanobot/config.json`)

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "123456:ABC...",
      "allowFrom": ["123456789"]
    }
  },
  "tools": {
    "web": {
      "search": {
        "apiKey": "BSA-xxx"
      }
    }
  }
}
```

---

## 4. 확장 포인트

### 4.1 새 프로바이더 추가

1. `LLMProvider` 상속하여 새 클래스 작성
2. `chat()` 메서드 구현
3. `cli/commands.py`에서 프로바이더 선택 로직 수정

### 4.2 새 채널 추가

1. `channels/base.py`의 `Channel` 상속
2. `on_message()` 콜백 구현
3. `ChannelManager`에 등록
