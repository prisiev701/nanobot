# Tool System 상세 분석

> 파일: `nanobot/agent/tools/`

## 1. 개요

Nanobot의 도구 시스템은 **플러그인 아키텍처**로 설계되어 있습니다. 모든 도구는 `Tool` 추상 클래스를 상속받아 구현되며, `ToolRegistry`를 통해 중앙 관리됩니다.

## 2. Tool 추상 클래스 (`base.py`)

모든 도구의 **설계 계약(Contract)**을 정의합니다.

```python
# nanobot/agent/tools/base.py

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """
    에이전트 도구의 추상 베이스 클래스.
    
    도구는 에이전트가 환경과 상호작용하는 데 사용하는 기능입니다.
    예: 파일 읽기, 명령 실행 등
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """함수 호출에 사용되는 도구 이름."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """도구가 무엇을 하는지에 대한 설명."""
        pass
    
    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """도구 파라미터를 위한 JSON Schema."""
        pass
    
    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        주어진 파라미터로 도구를 실행합니다.
        
        Returns:
            도구 실행 결과 문자열.
        """
        pass
    
    def to_schema(self) -> dict[str, Any]:
        """OpenAI 함수 스키마 형식으로 변환합니다."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }
```

### 핵심 포인트:
- `@property` + `@abstractmethod`: 필수로 구현해야 하는 속성
- `execute()`: 비동기 메서드, 반드시 `str` 반환
- `to_schema()`: LLM에게 전달할 함수 스키마 자동 생성

## 3. ToolRegistry (`registry.py`)

도구들을 중앙에서 관리하는 **레지스트리 패턴** 구현입니다.

```python
class ToolRegistry:
    """도구 등록 및 실행을 관리합니다."""
    
    def __init__(self):
        self._tools: dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> None:
        """도구를 등록합니다."""
        self._tools[tool.name] = tool
    
    def get(self, name: str) -> Tool | None:
        """이름으로 도구를 가져옵니다."""
        return self._tools.get(name)
    
    def get_definitions(self) -> list[dict[str, Any]]:
        """모든 도구의 스키마 목록을 반환합니다."""
        return [tool.to_schema() for tool in self._tools.values()]
    
    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """도구를 이름으로 실행합니다."""
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"
        
        try:
            return await tool.execute(**params)
        except Exception as e:
            return f"Error executing {name}: {str(e)}"
```

### 사용 흐름:

```
1. 초기화: registry = ToolRegistry()
2. 등록:   registry.register(ReadFileTool())
3. 스키마: definitions = registry.get_definitions()  # LLM에 전달
4. 실행:   result = await registry.execute("read_file", {"path": "/tmp/foo"})
```

## 4. 내장 도구 목록

### 4.1 파일 시스템 도구 (`filesystem.py`)

| 도구 | 설명 | 주요 파라미터 |
|------|------|---------------|
| `read_file` | 파일 내용 읽기 | `path` |
| `write_file` | 파일 쓰기 (디렉토리 자동 생성) | `path`, `content` |
| `edit_file` | 특정 텍스트 찾아 교체 | `path`, `old_text`, `new_text` |
| `list_dir` | 디렉토리 목록 | `path` |

**ReadFileTool 예시:**

```python
class ReadFileTool(Tool):
    @property
    def name(self) -> str:
        return "read_file"
    
    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to read"
                }
            },
            "required": ["path"]
        }
    
    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            return Path(path).read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading file: {str(e)}"
```

### 4.2 쉘 도구 (`shell.py`)

```python
class ExecTool(Tool):
    """쉘 명령어 실행 도구."""
    
    @property
    def name(self) -> str:
        return "exec"
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"}
            },
            "required": ["command"]
        }
    
    async def execute(self, command: str, timeout: int = 30, **kwargs) -> str:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.working_dir
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), 
            timeout=timeout
        )
        return stdout.decode() + stderr.decode()
```

### 4.3 웹 도구 (`web.py`)

| 도구 | 설명 |
|------|------|
| `web_search` | Brave Search API로 웹 검색 |
| `web_fetch` | URL에서 읽기 가능한 콘텐츠 추출 (Readability) |

### 4.4 메시지 도구 (`message.py`)

```python
class MessageTool(Tool):
    """채널로 메시지 전송."""
    
    def __init__(self, send_callback):
        self._send = send_callback
        self._channel = "cli"
        self._chat_id = "direct"
    
    def set_context(self, channel: str, chat_id: str):
        """현재 대화 컨텍스트 설정."""
        self._channel = channel
        self._chat_id = chat_id
    
    async def execute(self, content: str, **kwargs) -> str:
        await self._send(OutboundMessage(
            channel=self._channel,
            chat_id=self._chat_id,
            content=content
        ))
        return "Message sent."
```

### 4.5 스폰 도구 (`spawn.py`)

백그라운드에서 서브에이전트를 실행합니다.

```python
class SpawnTool(Tool):
    """백그라운드 서브에이전트 생성 도구."""
    
    @property
    def name(self) -> str:
        return "spawn"
    
    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks."
        )
    
    async def execute(self, task: str, label: str | None = None, **kwargs) -> str:
        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
        )
```

## 5. 새 도구 추가 가이드

### 5.1 도구 클래스 작성

```python
# nanobot/agent/tools/dice.py

import random
from typing import Any
from nanobot.agent.tools.base import Tool


class DiceRollTool(Tool):
    """주사위를 굴리는 도구."""
    
    @property
    def name(self) -> str:
        return "roll_dice"
    
    @property
    def description(self) -> str:
        return "Roll dice and return the result. Specify number of dice and sides."
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of dice to roll",
                    "default": 1
                },
                "sides": {
                    "type": "integer",
                    "description": "Number of sides on each die",
                    "default": 6
                }
            },
            "required": []
        }
    
    async def execute(self, count: int = 1, sides: int = 6, **kwargs: Any) -> str:
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        
        if count == 1:
            return f"🎲 Rolled a {total}!"
        else:
            return f"🎲 Rolled {count}d{sides}: {rolls} = {total}"
```

### 5.2 도구 등록

`nanobot/agent/loop.py`의 `_register_default_tools()` 메서드에 추가:

```python
from nanobot.agent.tools.dice import DiceRollTool

def _register_default_tools(self) -> None:
    # ... 기존 도구들 ...
    
    # 새 도구 추가
    self.tools.register(DiceRollTool())
```

### 5.3 테스트

```bash
nanobot agent -m "Roll 2 six-sided dice for me"
```

## 6. 도구 설계 Best Practices

| 원칙 | 설명 |
|------|------|
| **단일 책임** | 하나의 도구는 하나의 명확한 기능만 수행 |
| **명확한 설명** | `description`이 LLM의 도구 선택에 영향을 줌 |
| **안전한 기본값** | `parameters`에 합리적인 기본값 제공 |
| **에러 처리** | 예외를 문자열로 변환하여 반환 (절대 throw하지 않기) |
| **비동기** | 네트워크/파일 I/O는 `async` 활용 |

## 7. JSON Schema 참고

파라미터 정의는 JSON Schema 형식을 따릅니다:

```python
{
    "type": "object",
    "properties": {
        "required_param": {
            "type": "string",
            "description": "필수 문자열 파라미터"
        },
        "optional_param": {
            "type": "integer",
            "description": "선택적 정수 파라미터",
            "default": 10
        },
        "enum_param": {
            "type": "string",
            "enum": ["option1", "option2"],
            "description": "열거형 파라미터"
        }
    },
    "required": ["required_param"]
}
```
