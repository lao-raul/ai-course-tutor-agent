"""Provider interfaces and adapters.

All LLM, embedding and object-store access goes through these protocols. Production
uses LM Studio and MinIO; tests use the deterministic fakes (design-spec §1).
"""

from course_tutor_api.providers.base import (
    ChatMessage,
    EmbeddingProvider,
    LLMProvider,
    ObjectStore,
    ProviderError,
)
from course_tutor_api.providers.fake import FakeLLMProvider, FakeObjectStore
from course_tutor_api.providers.lmstudio import LMStudioProvider
from course_tutor_api.providers.resilience import ResilientLLMProvider

__all__ = [
    "ChatMessage",
    "EmbeddingProvider",
    "FakeLLMProvider",
    "FakeObjectStore",
    "LLMProvider",
    "LMStudioProvider",
    "ObjectStore",
    "ProviderError",
    "ResilientLLMProvider",
]
