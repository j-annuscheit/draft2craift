"""Bind split method implementations to FactCheckPipelineMixin."""
from __future__ import annotations

from . import (
    backend_runners,
    claim_cache,
    claim_precompute,
    common,
    nli_async,
    nli_core,
    pipeline_entry,
    pipeline_finalize,
    verdicts_markdown,
)

_METHOD_MODULES = (
    common,
    claim_cache,
    claim_precompute,
    verdicts_markdown,
    pipeline_finalize,
    nli_core,
    backend_runners,
    nli_async,
    pipeline_entry,
)

def bind_factcheck_pipeline_mixin(cls):
    for module in _METHOD_MODULES:
        for name in getattr(module, "__all__", ()):
            setattr(cls, name, getattr(module, name))
