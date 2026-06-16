import asyncio
import logging
logging.disable(logging.CRITICAL)
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits
from agent.hooks.llm import timed_agent_run

agent = Agent(TestModel(), system_prompt='test')

@agent.tool_plain
def search(q: str) -> str:
    return 'tool result: phone A, phone B'

async def main():
    res = await timed_agent_run(agent, 'hi', 'test', usage_limits=UsageLimits(request_limit=1))
    print('OUTPUT:', repr(res.output))
    print('MSG COUNT:', len(res.all_messages()))

asyncio.run(main())
