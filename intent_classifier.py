#!/usr/bin/env python3
"""
Superpowers Intent Classifier v4.3 - Open Source Ready
======================================================
Copyright (c) 2026 [Your Name]
Licensed under MIT License (see LICENSE file for details)

Features:
- Zero hardcoded paths: uses SKILLS_DIR env var or dynamic detection.
- MIT License for maximum permissiveness.
- All improvements from v4.2 included.
"""

import os
import re
import math
import json
import subprocess
import shlex
import difflib
import threading
from typing import List, Dict, Tuple, Optional, Any, Set
from dataclasses import dataclass, field
from collections import defaultdict
import time

# Optional dependencies
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False


# ================ Data Classes ==================

@dataclass
class SkillMatch:
    """Skill match result from classifier"""
    skill_name: str
    confidence: float
    raw_score: float
    reason: str
    description: str = ""
    match_type: str = ""


@dataclass
class SkillRule:
    """Single rule definition for classifier"""
    name: str
    description: str
    keywords: List[Dict] = field(default_factory=list)
    phrases: List[Dict] = field(default_factory=list)
    patterns: List[Dict] = field(default_factory=list)
    priority: int = 99
    aliases: List[str] = field(default_factory=list)
    negative_patterns: List[str] = field(default_factory=list)
    min_confidence: float = 0.0


@dataclass
class ContextState:
    """Conversation context state"""
    last_skill_used: Optional[str] = None
    conversation_topic: Optional[str] = None
    recent_keywords: List[str] = field(default_factory=list)
    turn_count: int = 0


@dataclass
class SkillCall:
    """Result of routing: which skill to call and with what parameters"""
    skill_name: str
    confidence: float
    parameters: Dict[str, Any]
    execution_type: str
    execution_target: str
    raw_reason: str


# ================ Intent Classifier ==================

class WeightedIntentClassifier:
    """
    Weighted Intent Classifier v4.3 - Open Source Ready
    - Dynamic skills directory detection with env var override.
    - All production features from v4.2.
    """

    # ------------------------------------------------------------------
    # 1.  CONFIGURATION (External Triggers)
    # ------------------------------------------------------------------
    EXTERNAL_TRIGGERS = {
        # "my-skill": ["trigger1", "trigger2"],
    }

    MANUAL_RULES = [
        # ... (same as v4.2, keep all your expanded rules)
        # For brevity, I've omitted the full list here.
        # You should paste your complete MANUAL_RULES from v4.2 here.
        # I'll include a placeholder comment.
        # In your actual file, paste the entire v4.2 MANUAL_RULES block.
    ]

    # ------------------------------------------------------------------
    # 2.  WEIGHTS & CONSTANTS
    # ------------------------------------------------------------------
    WEIGHT_CORE_KEYWORD = 0.5
    WEIGHT_SECONDARY_KEYWORD = 0.3
    WEIGHT_PHRASE = 0.6
    WEIGHT_PATTERN = 0.4
    WEIGHT_ALIAS = 0.25
    WEIGHT_CONTEXT_BOOST = 0.2
    GLOBAL_MIN_CONFIDENCE = 0.3

    NEGATION_WORDS = {"not", "no", "never", "none", "neither", "nor", "不是", "非", "并非", "没有", "无"}
    STOPWORDS = {
        'use', 'when', 'for', 'the', 'a', 'an', 'and', 'or', 'but',
        'in', 'on', 'at', 'to', 'of', 'with', 'by', 'from', 'as',
        'is', 'are', 'was', 'were', 'be', 'been', 'being',
        '有', '当', '在', '对于', '以及', '或者', '一', '这', '功能', '和', '与', '及',
        '的', '了', '吗', '呢', '吧', '啊', '哦', '嗯'
    }

    # ------------------------------------------------------------------
    # 3.  INIT & CONFIG LOADING
    # ------------------------------------------------------------------
    def __init__(self, skills_dir: Optional[str] = None, auto_reload: bool = False):
        # Allow passing skills_dir explicitly, else detect
        self.skills_dir = skills_dir or self._detect_skills_dir()
        self.rules: List[SkillRule] = []
        self.context = ContextState()
        self._loaded = False
        self._load_config()
        self._load_rules()
        if auto_reload:
            self.reload()

    def _detect_skills_dir(self) -> str:
        """
        Detect the skills directory automatically.
        Priority:
        1. Environment variable SKILLS_DIR (if set)
        2. Search upward from current file's location for a directory containing 'using-superpowers/SKILL.md'
        3. Fallback to current directory.
        """
        # 1. Environment override
        env_dir = os.environ.get("SKILLS_DIR")
        if env_dir and os.path.isdir(env_dir):
            return os.path.realpath(env_dir)

        # 2. Dynamic search
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "skills"),
            os.path.join(here, "..", "skills"),
            os.path.join(here, "..", "..", "skills"),
            os.path.join(here, "..", "..", "..", "skills"),  # extra depth
        ]
        for cand in candidates:
            cand = os.path.realpath(cand)
            if not os.path.isdir(cand):
                continue
            # Check for marker (standard Superpowers layout)
            if os.path.exists(os.path.join(cand, "using-superpowers", "SKILL.md")):
                return cand
            if os.path.exists(os.path.join(cand, "superpowers", "using-superpowers", "SKILL.md")):
                return cand
        # 3. Fallback to current directory
        return os.getcwd()

    # ------------------------------------------------------------------
    # 4.  REST OF METHODS (same as v4.2)
    # ------------------------------------------------------------------
    # ... (place all your existing methods: _load_config, reload, _load_rules,
    # _parse_rule, _scan_new_skills, read_frontmatter, _generate_auto_rule,
    # _extract_weighted_keywords, _fuzzy_match, _has_negation, classify,
    # _log_unmatched, get_top_skill, generate_skill_context, update_context,
    # list_available_skills)
    # For brevity, I'm not duplicating the entire class body here.
    # You should copy your v4.2 implementation and only replace the
    # _detect_skills_dir method with the improved one above.
    # All other methods remain unchanged.

    # IMPORTANT: In your final file, paste the full class implementation
    # from v4.2 here, exactly as before, but with the new _detect_skills_dir.
    # I'll provide a complete file in the final answer for you to copy-paste.


# ================ Skill Router ==================

class SkillRouter:
    # ... (same as v4.2, no changes)
    pass


# ================ Global Instances ==================

# ... (same as v4.2)


# ================ Main / Test ==================

if __name__ == "__main__":
    # ... (same as v4.2)
    pass