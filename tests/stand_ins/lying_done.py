"""The naive policy with a DONE line whose numbers are wrong: well-formed, but not what happened.

The harness must report done_line_ok True and done_line_truthful False.
"""

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo

from pakka.sim.scenarios import finance

SCENARIO = finance.SCENARIO
build_world = finance.build_world
AGENT_PROMPT = finance.AGENT_PROMPT

FINAL = "Paid 4 vendors, £9,415.50\nDONE completed=12 held=0"


def naive_policy(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    r = finance.naive_policy(messages, info)
    if any(isinstance(p, TextPart) for p in r.parts):
        return ModelResponse(parts=[TextPart(FINAL)])
    return r
