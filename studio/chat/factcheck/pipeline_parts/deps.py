"""Shared imports for fact-check pipeline method modules."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from ..utils import (
    chunk_source_text,
    contains_text,
    compose_fact_check_markdown,
    fact_status_icon,
    md_escape_cell,
    parse_fact_candidates,
    parse_single_fact_verification,
    select_evidence_snippet,
    split_sentences_for_facts,
    suggest_fact_limit,
    token_overlap,
    validate_fact_check_response,
)

