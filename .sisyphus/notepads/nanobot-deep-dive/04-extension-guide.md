# Nanobot 확장 가이드

이 문서에서는 Nanobot에 새로운 기능을 추가하는 방법을 실습합니다.

---

## 1. 새 CLI 명령어 추가

### 1.1 목표
`nanobot greet --name Atlas` 명령어를 추가합니다.

### 1.2 코드 (`nanobot/cli/commands.py`)

```python
# 파일 끝부분에 추가

@app.command()
def greet(
    name: str = typer.Option("World", "--name", "-n", help="Name to greet"),
    emoji: bool = typer.Option(False, "--emoji", "-e", help="Add emoji")
):
    """Greet someone with a friendly message."""
    greeting = f"Hello, {name}!"
    if emoji:
        greeting = f"👋 {greeting} 🎉"
    console.print(greeting)
```

### 1.3 테스트

```bash
nanobot greet --name Atlas --emoji
# 출력: 👋 Hello, Atlas! 🎉
```

---

## 2. 새 도구 추가: DiceRollTool

### 2.1 목표
에이전트가 주사위를 굴릴 수 있는 `roll_dice` 도구를 추가합니다.

### 2.2 도구 클래스 작성

```python
# nanobot/agent/tools/dice.py

import random
from typing import Any
from nanobot.agent.tools.base import Tool


class DiceRollTool(Tool):
    """주사위 굴리기 도구."""
    
    @property
    def name(self) -> str:
        return "roll_dice"
    
    @property
    def description(self) -> str:
        return (
            "Roll one or more dice with specified number of sides. "
            "Returns the individual rolls and total. "
            "Example: roll 2 six-sided dice (2d6)."
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of dice to roll (default: 1)",
                    "minimum": 1,
                    "maximum": 100
                },
                "sides": {
                    "type": "integer",
                    "description": "Number of sides on each die (default: 6)",
                    "minimum": 2,
                    "maximum": 100
                }
            },
            "required": []
        }
    
    async def execute(
        self, 
        count: int = 1, 
        sides: int = 6, 
        **kwargs: Any
    ) -> str:
        # 입력 검증
        count = max(1, min(count, 100))
        sides = max(2, min(sides, 100))
        
        # 주사위 굴리기
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        
        # 결과 포맷팅
        dice_notation = f"{count}d{sides}"
        
        if count == 1:
            return f"🎲 Rolled {dice_notation}: **{total}**"
        else:
            rolls_str = ", ".join(str(r) for r in rolls)
            return f"🎲 Rolled {dice_notation}: [{rolls_str}] = **{total}**"
```

### 2.3 도구 등록

```python
# nanobot/agent/loop.py

from nanobot.agent.tools.dice import DiceRollTool  # 상단에 추가

def _register_default_tools(self) -> None:
    # ... 기존 도구들 ...
    
    # 주사위 도구 추가
    self.tools.register(DiceRollTool())
```

### 2.4 테스트

```bash
nanobot agent -m "Roll 3 twenty-sided dice for my D&D attack"
```

---

## 3. 새 스킬 추가: Calculator

### 3.1 스킬이란?
스킬은 에이전트에게 **특정 작업 수행 방법**을 알려주는 마크다운 문서입니다. 도구와 달리 코드가 아닌 지침입니다.

### 3.2 스킬 구조

```
nanobot/skills/
└── calculator/
    └── SKILL.md
```

### 3.3 스킬 작성 (`SKILL.md`)

```markdown
---
name: calculator
description: Perform mathematical calculations
version: 1.0.0
author: Your Name
always: false
available: true
---

# Calculator Skill

You can perform mathematical calculations using Python's `exec` tool.

## Usage

When asked to calculate something:

1. Write a Python script that performs the calculation
2. Use the `exec` tool to run it
3. Return the result

## Examples

### Simple Calculation
```bash
python3 -c "print(2 + 2 * 3)"
```

### Complex Formula
```bash
python3 -c "import math; print(math.sqrt(144) + math.pi)"
```

### Statistics
```bash
python3 -c "
data = [1, 2, 3, 4, 5]
mean = sum(data) / len(data)
print(f'Mean: {mean}')
"
```

## Notes

- Always show your work (the formula used)
- Round results to 2 decimal places when appropriate
- For very large numbers, use scientific notation
```

### 3.4 스킬 사용

```bash
nanobot agent -m "Calculate the compound interest on $1000 at 5% for 10 years"
```

에이전트는 `calculator` 스킬을 로드하고 지침에 따라 Python으로 계산합니다.

---

## 4. Context Builder 확장

### 4.1 새 부트스트랩 파일 추가

시스템 프롬프트에 포함될 새 파일을 추가합니다.

```python
# nanobot/agent/context.py

class ContextBuilder:
    # 기존 파일에 추가
    BOOTSTRAP_FILES = [
        "AGENTS.md", 
        "SOUL.md", 
        "USER.md", 
        "TOOLS.md", 
        "IDENTITY.md",
        "RULES.md"  # 새로 추가
    ]
```

그리고 워크스페이스에 `RULES.md` 파일을 생성합니다:

```markdown
# Rules

## Safety Rules
- Never delete files without explicit confirmation
- Always backup before making destructive changes

## Style Rules
- Use Korean when the user writes in Korean
- Be concise but thorough
```

---

## 5. 새 채널 추가: Discord

### 5.1 채널 클래스 작성

```python
# nanobot/channels/discord.py

from nanobot.channels.base import Channel
from nanobot.bus.events import InboundMessage, OutboundMessage


class DiscordChannel(Channel):
    """Discord 채널 통합."""
    
    def __init__(self, bus, token: str, allowed_channels: list[str]):
        super().__init__(bus)
        self.token = token
        self.allowed_channels = allowed_channels
        self._client = None
    
    @property
    def name(self) -> str:
        return "discord"
    
    async def start(self) -> None:
        import discord
        
        intents = discord.Intents.default()
        intents.message_content = True
        
        self._client = discord.Client(intents=intents)
        
        @self._client.event
        async def on_message(message):
            # 자신의 메시지 무시
            if message.author == self._client.user:
                return
            
            # 허용된 채널만 처리
            if str(message.channel.id) not in self.allowed_channels:
                return
            
            # 인바운드 메시지 생성
            await self.bus.publish_inbound(InboundMessage(
                channel="discord",
                sender_id=str(message.author.id),
                chat_id=str(message.channel.id),
                content=message.content
            ))
        
        await self._client.start(self.token)
    
    async def send(self, msg: OutboundMessage) -> None:
        channel = self._client.get_channel(int(msg.chat_id))
        if channel:
            await channel.send(msg.content)
```

### 5.2 설정 스키마 추가

```python
# nanobot/config/schema.py

class DiscordConfig(BaseModel):
    enabled: bool = False
    token: str | None = None
    allow_channels: list[str] = []
```

### 5.3 ChannelManager에 등록

```python
# nanobot/channels/manager.py

if config.channels.discord.enabled:
    self.channels["discord"] = DiscordChannel(
        bus=bus,
        token=config.channels.discord.token,
        allowed_channels=config.channels.discord.allow_channels
    )
```

---

## 6. 체크리스트

새 기능을 추가할 때 확인할 사항:

- [ ] 타입 힌트 추가 (`-> str`, `list[dict]` 등)
- [ ] 독스트링 작성
- [ ] 에러 처리 (예외를 문자열로 변환)
- [ ] 로깅 추가 (`from loguru import logger`)
- [ ] 설정 스키마 업데이트 (필요시)
- [ ] README 업데이트 (필요시)

---

## 7. 디버깅 팁

### 7.1 상세 로그 활성화

```bash
nanobot gateway --verbose
```

### 7.2 직접 테스트

```python
# 테스트 스크립트
import asyncio
from nanobot.agent.tools.dice import DiceRollTool

async def test():
    tool = DiceRollTool()
    result = await tool.execute(count=3, sides=20)
    print(result)

asyncio.run(test())
```

### 7.3 LLM 호출 디버깅

```python
# nanobot/providers/litellm_provider.py

# acompletion 호출 전에 추가
from loguru import logger
logger.debug(f"LLM Request: model={model}, messages={len(messages)}")
logger.debug(f"Tools: {[t['function']['name'] for t in tools] if tools else 'None'}")
```
