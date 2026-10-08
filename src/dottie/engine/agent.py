"""Assembling a dottie's agent for one waking: model, prompt, tools, and the files it can see."""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend
from deepagents.backends.protocol import BackendProtocol, SandboxBackendProtocol
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver

from dottie_runtime.filters import ToolFilter

from ..config import Settings
from ..models import Dottie
from .files import SkillFiles, WikiFiles
from .sandboxes import WORKDIR

ModelFactory = Callable[[Settings, Dottie], BaseChatModel]

AZURE_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


class NotConfigured(Exception):
    """The dottie cannot think yet: no model is set up. Its message is what the user sees."""


def build_model(settings: Settings, dottie: Dottie) -> BaseChatModel:
    """Azure Foundry's OpenAI v1 endpoint (or any OpenAI-compatible gateway) through the Responses API.

    Without an API key on an Azure endpoint the app's own identity signs in (the managed identity on Azure, your
    `az login` locally), so no model key has to exist anywhere.
    """
    if not settings.llm_configured:
        raise NotConfigured("I have no model to think with yet: the app needs LLM_BASE_URL and LLM_MODEL.")
    key = settings.llm_api_key.get_secret_value()
    api_key: Any = key or "unused"
    if not key and "azure.com" in settings.llm_base_url:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        api_key = get_bearer_token_provider(DefaultAzureCredential(), AZURE_COGNITIVE_SCOPE)
    extra: dict[str, Any] = {}
    if settings.llm_use_responses_api:
        extra = {"use_responses_api": True, "store": False, "include": ["reasoning.encrypted_content"]}
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=api_key,
        model=dottie.model or settings.llm_model,
        timeout=120,
        max_retries=2,
        # Each run has its own event loop, and langchain-openai's default async client is one shared object bound to the
        # first loop that used it ("Event loop is closed" on the second run): so every model gets its own.
        http_async_client=httpx.AsyncClient(timeout=120),
        **extra,
    )


def system_prompt(dottie: Dottie, trigger: str, has_shell: bool, timezone: str, *, in_sandbox: bool = False) -> str:
    now = datetime.now(ZoneInfo(timezone)).strftime("%A %d %B %Y, %H:%M (%Z)")
    if in_sandbox:
        computer = (
            f"- You live on a Linux computer of your own (tool `execute`), working directory `{WORKDIR}`. Keep working "
            "files there. It is yours alone and may be reset: what matters goes in your wiki.\n"
            if has_shell
            else "- You have no shell, only your wiki. Files outside `/wiki` vanish when you go to sleep.\n"
        )
    else:
        computer = _computer_note(has_shell)
    return _prompt(dottie, computer, trigger, now)


def _computer_note(has_shell: bool) -> str:
    return (
        f"- You have a computer of your own: a Linux sandbox (tool `execute`) with a persistent working directory "
        f"`{WORKDIR}`. Keep working files there. It is yours alone and may be reset: what matters goes in your wiki.\n"
        if has_shell
        else "- You have no computer of your own, only your wiki. Files outside `/wiki` vanish when you go to sleep.\n"
    )


def _prompt(dottie: Dottie, computer: str, trigger: str, now: str) -> str:
    return f"""You are {dottie.name}, a dottie: a persistent agent that works for one person. {dottie.role}

## How you live
- You sleep most of the time. You wake when someone writes to you, when one of your schedules is due, or when another \
dottie sends you a message. Each waking is one run: do the work, answer, and go back to sleep.
- Your memory is your wiki: markdown files under `/wiki`. `/wiki/index.md` is shown to you below on every waking. \
Keep it a short table of contents (one line per page, `[[page]]` links) and put detail in pages of their own. When you \
learn something that will matter later (a preference, a decision, a person, a lesson), write it down before you \
answer, and add one line to `/wiki/log.md`. Never write secrets into the wiki.
- Skills (under `/skills`) are procedures you were given. Read one when its description fits the task.
{computer}- Your answer goes to the person who woke you. If another dottie woke you, your answer is not delivered: use \
`send_message` to reply, and only when there is something to say (never just to acknowledge). If what a dottie sent \
you matters to the person you work for (for instance the answer to something you delegated), you must pass it on \
with `tell_user`: nothing else reaches them.
- Say plainly what you did and what you could not do. Do not invent results.

## Your character
{dottie.personality.strip() or "Helpful, direct and calm."}

## Now
It is {now}. {trigger}"""


def build_agent(
    *,
    dottie: Dottie,
    model: BaseChatModel,
    tools: list[Callable[..., str]],
    wiki: WikiFiles,
    skills: SkillFiles,
    sandbox: SandboxBackendProtocol | None,
    mcp_tools: list[Any],
    checkpointer: BaseCheckpointSaver,
    trigger: str,
    timezone: str = "UTC",
):
    default: BackendProtocol = sandbox if sandbox is not None else StateBackend()
    backend = CompositeBackend(default=default, routes={"/wiki/": wiki, "/skills/": skills})
    blocked = set() if sandbox is not None else {"execute"}
    return create_deep_agent(
        model=model,
        tools=[*tools, *mcp_tools],
        system_prompt=system_prompt(dottie, trigger, sandbox is not None, timezone),
        middleware=[ToolFilter(blocked)],
        backend=backend,
        memory=["/wiki/index.md"],
        skills=["/skills/"],
        checkpointer=checkpointer,
        name=dottie.slug,
    )
