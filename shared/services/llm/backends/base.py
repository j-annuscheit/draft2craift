"""Base abstraction for pluggable LLM inference backends."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator


class BaseLLMBackend(ABC):
    """Common interface used by the runtime to load and run text models."""

    @property
    @abstractmethod
    def backend_id(self) -> str:
        """Stable backend identifier (for logging and persistence)."""

    @property
    @abstractmethod
    def model_ref(self) -> str:
        """Model path/id currently loaded by this backend."""

    @abstractmethod
    def load_model(
        self,
        model_ref: str,
        *,
        n_ctx: int = 4096,
        n_gpu_layers: int = 0,
        n_threads: int = 0,
        embedding: bool = False,
        flash_attn: bool = True,
    ) -> tuple[bool, str]:
        """Load model and return ``(success, status_message)``."""

    @abstractmethod
    def unload_model(self) -> None:
        """Release backend resources and loaded model state."""

    @abstractmethod
    def is_loaded(self) -> bool:
        """Return whether generation can be performed."""

    @abstractmethod
    def context_window(self, default_n_ctx: int = 4096) -> int:
        """Return effective context window for prompt budgeting."""

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Return token count estimate for prompt budgeting."""

    @abstractmethod
    def prepare_prompt(self, prompt: str) -> str:
        """Convert a runtime prompt into backend-native input text."""

    @abstractmethod
    def generate_once(
        self,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        repeat_penalty: float,
        stop: list[str] | None = None,
        forbidden_chars: tuple[str, ...] = (),
    ) -> str:
        """Generate non-streaming text completion."""

    @abstractmethod
    def generate_stream(
        self,
        prompt: str,
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        repeat_penalty: float,
        stop: list[str] | None = None,
        forbidden_chars: tuple[str, ...] = (),
        stop_requested: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        """Yield generated text pieces in streaming mode."""
