from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Type
from app.core.config import settings


class LLMProvider(ABC):
    @abstractmethod
    def invoke(self,messages:list[dict],response_model:Type[Any]|None=None): ...
    @abstractmethod
    async def ainvoke(self,messages:list[dict],response_model:Type[Any]|None=None): ...
    @abstractmethod
    def stream(self,messages:list[dict]): ...


class OpenAIProvider(LLMProvider):
    def __init__(self):
        from langchain_openai import ChatOpenAI
        self.model=ChatOpenAI(model=settings.llm_model or settings.openai_model,api_key=settings.openai_api_key,
                              temperature=settings.llm_temperature,base_url=settings.llm_base_url,timeout=settings.mcp_timeout_seconds,max_retries=2)
    def _wrap(self,response_model):
        return self.model.with_structured_output(response_model) if response_model else self.model
    def invoke(self,messages,response_model=None): return self._wrap(response_model).invoke(messages)
    async def ainvoke(self,messages,response_model=None): return await self._wrap(response_model).ainvoke(messages)
    def stream(self,messages): return self.model.stream(messages)


class AnthropicProvider(LLMProvider):
    def __init__(self):
        from langchain_anthropic import ChatAnthropic
        self.model=ChatAnthropic(model=settings.llm_model,api_key=settings.anthropic_api_key,temperature=settings.llm_temperature,max_retries=2)
    def _wrap(self,response_model):
        return self.model.with_structured_output(response_model) if response_model else self.model
    def invoke(self,messages,response_model=None): return self._wrap(response_model).invoke(messages)
    async def ainvoke(self,messages,response_model=None): return await self._wrap(response_model).ainvoke(messages)
    def stream(self,messages): return self.model.stream(messages)


class LocalProvider(OpenAIProvider):
    pass


def create_provider()->LLMProvider:
    provider=settings.llm_provider.lower()
    if provider=="openai":
        if not settings.openai_api_key: raise RuntimeError("OPENAI_API_KEY is required for OpenAI provider.")
        return OpenAIProvider()
    if provider=="anthropic":
        if not settings.anthropic_api_key: raise RuntimeError("ANTHROPIC_API_KEY is required for Anthropic provider.")
        return AnthropicProvider()
    if provider in {"local","ollama","openai-compatible"}:
        if not settings.llm_base_url: raise RuntimeError("LLM_BASE_URL is required for local/OpenAI-compatible provider.")
        return LocalProvider()
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


class LLMClient:
    def __init__(self): self.provider=create_provider()
    def generate(self,system,prompt,response_model=None):
        from langchain_core.messages import SystemMessage,HumanMessage
        return self.provider.invoke([SystemMessage(content=system),HumanMessage(content=prompt)],response_model=response_model)
    async def agenerate(self,system,prompt,response_model=None):
        from langchain_core.messages import SystemMessage,HumanMessage
        return await self.provider.ainvoke([SystemMessage(content=system),HumanMessage(content=prompt)],response_model=response_model)
    def stream(self,system,prompt):
        from langchain_core.messages import SystemMessage,HumanMessage
        return self.provider.stream([SystemMessage(content=system),HumanMessage(content=prompt)])
