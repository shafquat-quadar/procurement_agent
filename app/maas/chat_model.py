"""LangChain-compatible chat model wrapper around MaaS.

Exposes both:
  * a simple `generate_text(sys_prompt, prompt, mode)` method used by the agent
    nodes, and
  * a minimal LangChain `BaseChatModel` interface (`_generate`) so it can be
    used with LangChain/LangGraph tooling if desired.

Two parameter presets are supported:
  * "factual"  -> temperature 0.0, top_p 0.1, max_tokens 1200  (SAP queries)
  * "help"     -> temperature 0.2, top_p 0.8, max_tokens 1500  (explanations)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.maas.client import MaaSClient
from app.maas.schemas import MaaSRequest

_MODE_PRESETS: dict[str, dict[str, Any]] = {
    "factual": {"temperature": 0.0, "top_p": 0.1, "max_tokens": 1200},
    "help": {"temperature": 0.2, "top_p": 0.8, "max_tokens": 1500},
}


@runtime_checkable
class ChatModel(Protocol):
    """Minimal chat interface the agent depends on (allows test fakes)."""

    def generate_text(self, sys_prompt: str, prompt: str, mode: str = "factual") -> str: ...


class MaaSChatModel(BaseChatModel):
    """A LangChain chat model backed by the MaaS client."""

    client: MaaSClient
    model_name: str = "gemini-3"

    def __init__(self, client: MaaSClient, model_name: str = "gemini-3", **kwargs: Any) -> None:
        super().__init__(client=client, model_name=model_name, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "maas"

    def generate_text(self, sys_prompt: str, prompt: str, mode: str = "factual") -> str:
        """Generate text with the given mode preset. Raises MaaSError on failure."""
        preset = _MODE_PRESETS.get(mode, _MODE_PRESETS["factual"])
        request = MaaSRequest(
            model=self.model_name,
            sys_prompt=sys_prompt,
            prompt=prompt,
            **preset,
        )
        return self.client.complete(request).text

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        sys_prompt = "\n".join(m.content for m in messages if isinstance(m, SystemMessage))
        user_prompt = "\n".join(
            m.content for m in messages if isinstance(m, (HumanMessage,))
        )
        mode = kwargs.get("mode", "factual")
        text = self.generate_text(sys_prompt, user_prompt, mode=mode)
        generation = ChatGeneration(message=AIMessage(content=text))
        return ChatResult(generations=[generation])
