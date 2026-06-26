"""Local Alex agent loop (text).

Runs Alex's EXACT system prompt + tools through Claude's tool-use loop, in text
instead of over the phone. Vapi runs this same loop on the live call; here we run
it locally so the eval harness can exercise Alex against simulated prospects with
no telephony. A `responder(alex_line) -> prospect_line` callback supplies the
prospect's turns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import config
from .brief import CallBrief
from .prompts import ALEX_SYSTEM, call_context_block
from .tools import TERMINAL_TOOLS, anthropic_tools, execute_tool


@dataclass
class CallRun:
    transcript: str = ""
    lines: list[tuple[str, str]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    ended_reason: str = "max_turns"

    def _add(self, speaker: str, text: str) -> None:
        if text:
            self.lines.append((speaker, text))
            self.transcript += f"{speaker}: {text}\n"


def run_call(
    lead: dict[str, Any],
    brief: CallBrief,
    responder: Callable[[str], str],
    max_turns: int = 12,
) -> CallRun:
    """Drive one simulated call. `responder` returns the prospect's next line."""
    import anthropic

    client = anthropic.Anthropic()
    system = ALEX_SYSTEM + "\n" + call_context_block(lead, brief)
    tools = anthropic_tools()
    run = CallRun()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "[Call connected — the prospect just picked up.]"}
    ]

    for _ in range(max_turns):
        resp = client.messages.create(
            model=config.CALLER_MODEL,
            max_tokens=1024,
            system=system,
            tools=tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        # Capture any spoken text from this turn.
        turn_text = " ".join(
            b.text.strip() for b in resp.content if b.type == "text" and b.text.strip()
        )
        run._add("Alex", turn_text)

        if resp.stop_reason == "tool_use":
            tool_results = []
            terminal = False
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                result = execute_tool(block.name, dict(block.input), lead["lead_id"])
                run.tool_calls.append({"name": block.name, "input": block.input, "result": result})
                run._add("[tool]", f"{block.name}({dict(block.input)}) -> {result}")
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    }
                )
                if block.name in TERMINAL_TOOLS:
                    terminal = True
                    run.ended_reason = block.name
            messages.append({"role": "user", "content": tool_results})
            if terminal:
                # Let Alex deliver a final closing line after the terminal tool.
                closing = client.messages.create(
                    model=config.CALLER_MODEL,
                    max_tokens=256,
                    system=system,
                    tools=tools,
                    messages=messages,
                )
                for block in closing.content:
                    if block.type == "text":
                        run._add("Alex", block.text.strip())
                return run
            continue

        # end_turn: Alex finished speaking — get the prospect's reply.
        prospect_line = responder(turn_text)
        if prospect_line is None or prospect_line.strip() == "":
            run.ended_reason = "prospect_hung_up"
            return run
        run._add("Prospect", prospect_line.strip())
        messages.append({"role": "user", "content": prospect_line.strip()})

    return run
