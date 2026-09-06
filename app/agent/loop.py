"""The agent's tool-calling loop. M2 scope: non-streamed (streaming over the WebSocket
lands in M6). This same function is also the "wake up and narrate" entry point the
async job/notification system (M4+) calls once a background job completes.
"""
import json
import logging

from .. import chat, openrouter, storyboard
from . import tools

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 8


async def _build_system_prompt(thread: dict) -> str:
    lines = [
        "You are the Director AI for a chat-first movie production studio. This is a genuine "
        "creative back-and-forth, not a one-shot command interface: talk with the user about what "
        "their movie/episode is about, ask questions, offer suggestions, and help them think through "
        "premise, characters, style, and scene structure before rushing to lock anything in.",
        "As the conversation firms up decisions, use your storyboard tools (update_episode, "
        "create_character, create_scene, etc.) to record them for real — silently, as a natural part "
        "of the conversation — rather than only describing changes in prose. Call get_storyboard "
        "first if you don't already know the current state.",
        "Generating actual media (images, video) is a separate, deliberate step — never call a "
        "generate_* tool speculatively or as a side effect of planning conversation. Only move toward "
        "generation when the user's own words clearly ask for it right now (e.g. \"let's generate a "
        "character image\" / \"render this scene\"). When that happens: first quote the estimated "
        "cost back to the user in plain language, then wait for their explicit go-ahead in their next "
        "message, and only then call the generate tool with confirmed=true. Never assume approval "
        "from enthusiasm or context alone — you need an actual yes.",
    ]
    episode = await storyboard.get_full_episode(thread["episode_id"])
    if episode:
        scene_lines = "\n".join(
            f"  - {s['id']} [{s['status']}] {s['title']} ({s['type']}, {s['duration']}s)"
            for s in episode["scenes"]
        ) or "  (none yet)"
        char_lines = ", ".join(c["name"] for c in episode["characters"]) or "(none yet)"
        loc_lines = ", ".join(l["name"] for l in episode["locations"]) or "(none yet)"
        lines.append(
            f"Current episode {episode['id']}: \"{episode['title']}\"\n"
            f"Premise: {episode['premise'] or '(not set yet)'}\n"
            f"Style: {episode['style'] or '(not set yet)'}\n"
            f"Characters: {char_lines}\n"
            f"Locations: {loc_lines}\n"
            f"Scenes:\n{scene_lines}"
        )
    if thread.get("scene_id"):
        lines.append(
            f"This conversation is focused on scene {thread['scene_id']} — default to that scene "
            "when the user says 'this scene' without needing to ask which one."
        )
    return "\n\n".join(lines)


async def _execute_tool_call(call: dict) -> str:
    name = call["function"]["name"]
    raw_args = call["function"].get("arguments") or "{}"
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"invalid tool arguments: {e}"})
    fn = tools.DISPATCH.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool: {name}"})
    try:
        result = await fn(**args)
        return json.dumps(result, default=str)
    except Exception as e:  # noqa: BLE001 - tool errors must come back to the model, not crash the loop
        logger.exception("tool %s failed", name)
        return json.dumps({"error": str(e)})


async def run_agent_turn(thread_id: str, user_message: str | None = None) -> dict:
    thread = await chat.get_thread(thread_id)
    if thread is None:
        raise ValueError(f"unknown thread {thread_id}")

    if user_message is not None:
        await chat.append_message(thread_id, "user", content=user_message)

    system_prompt = await _build_system_prompt(thread)

    last_assistant_message: dict | None = None
    for _ in range(MAX_TOOL_ITERATIONS):
        history = chat.to_api_messages(await chat.list_messages(thread_id))
        messages = [{"role": "system", "content": system_prompt}, *history]

        response = await openrouter.chat_completion(
            thread["model"], messages, tools=tools.TOOL_SCHEMAS, tool_choice="auto",
        )
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls")

        if not tool_calls:
            last_assistant_message = await chat.append_message(
                thread_id, "assistant", content=message.get("content") or "",
            )
            break

        await chat.append_message(
            thread_id, "assistant", content=message.get("content"), tool_calls=tool_calls,
        )
        for call in tool_calls:
            result_json = await _execute_tool_call(call)
            await chat.append_message(
                thread_id, "tool", content=result_json, tool_call_id=call["id"],
            )
        # loop again so the model sees the tool results and can respond or call more tools
    else:
        last_assistant_message = await chat.append_message(
            thread_id, "assistant",
            content="(stopped after too many tool calls in a row — ask me to continue if needed)",
        )

    return last_assistant_message
