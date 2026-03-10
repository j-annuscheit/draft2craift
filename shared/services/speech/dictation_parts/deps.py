"""Shared imports for WhisperDictationWorker method modules."""
from __future__ import annotations

import os
from pathlib import Path
import queue
import re
import select
import shutil
import subprocess
import time
from typing import Any

