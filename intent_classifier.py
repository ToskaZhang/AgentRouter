#!/usr/bin/env python3
"""
Superpowers Intent Classifier v4.3 - Open Source Ready
======================================================
Copyright (c) 2026 ToskaZhang
Licensed under MIT License (see LICENSE file for details)

Features:
- Weighted rule-based intent classification with 11 built-in skills
- Fuzzy phrase matching for typos
- Context damping to prevent topic-sticking
- External triggers via YAML or environment variables
- Shell command sanitization (no shell=True)
- Hot reload via watchdog (optional)
- Unmatched message logging for tuning
- Dynamic skills directory detection
"""

import os
import re
import sys
import json
import subprocess
import shlex
import difflib
import threading
import time
from typing import List, Dict, Tuple, Optional, Any, Set
from dataclasses import dataclass, field
from collections import defaultdict

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
    confidence: float          # 0..1, normalized
    raw_score: float           # raw sum before normalization
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
    execution_type: str          # "shell", "prompt", "api"
    execution_target: str        # command or prompt template
    raw_reason: str


# ================ Intent Classifier ==================

class WeightedIntentClassifier:
    """
    Weighted Intent Classifier v4.3 - Open Source Ready
    """

    # ------------------------------------------------------------------
    # 1.  CONFIGURATION
    # ------------------------------------------------------------------

    # External trigger mapping (skill_name -> list of trigger phrases)
    EXTERNAL_TRIGGERS = {
        # "db-migrate": ["迁移数据库", "改表", ...],
        # "my-new-skill": ["trigger1", "trigger2"],
    }

    # Built-in skills with full trigger sets
    MANUAL_RULES = [
        # ---------- systematic-debugging ----------
        {
            "name": "systematic-debugging",
            "description": "调试 Bug、测试失败、异常行为",
            "phrases": [
                {"phrase": "修复 bug", "weight": 0.8}, {"phrase": "修 bug", "weight": 0.7},
                {"phrase": "调试代码", "weight": 0.7}, {"phrase": "排查问题", "weight": 0.7},
                {"phrase": "定位错误", "weight": 0.7}, {"phrase": "解决报错", "weight": 0.7},
                {"phrase": "测试失败", "weight": 0.7}, {"phrase": "跑不起来", "weight": 0.7},
                {"phrase": "启动报错", "weight": 0.6}, {"phrase": "编译失败", "weight": 0.6},
                {"phrase": "运行时崩溃", "weight": 0.7}, {"phrase": "堆栈溢出", "weight": 0.7},
                {"phrase": "空指针异常", "weight": 0.7}, {"phrase": "数组越界", "weight": 0.6},
                {"phrase": "内存泄漏", "weight": 0.7}, {"phrase": "死锁了", "weight": 0.7},
                {"phrase": "接口超时", "weight": 0.6}, {"phrase": "返回 500", "weight": 0.6},
                {"phrase": "连接不上", "weight": 0.6}, {"phrase": "数据对不上", "weight": 0.5},
                {"phrase": "逻辑有误", "weight": 0.6}, {"phrase": "环境问题", "weight": 0.5},
                {"phrase": "依赖冲突", "weight": 0.6}, {"phrase": "版本不兼容", "weight": 0.6},
                {"phrase": "出 bug 了", "weight": 0.8}, {"phrase": "有 bug", "weight": 0.6},
                {"phrase": "炸了", "weight": 0.6}, {"phrase": "崩了", "weight": 0.7},
                {"phrase": "挂了", "weight": 0.6}, {"phrase": "卡死了", "weight": 0.5},
                {"phrase": "动不了", "weight": 0.5}, {"phrase": "不正常", "weight": 0.4},
                {"phrase": "修一下", "weight": 0.4}, {"phrase": "处理异常", "weight": 0.6},
            ],
            "keywords": [
                {"word": "bug", "weight": 0.6}, {"word": "debug", "weight": 0.6},
                {"word": "崩溃", "weight": 0.6}, {"word": "异常", "weight": 0.5},
                {"word": "错误", "weight": 0.5}, {"word": "报错", "weight": 0.6},
                {"word": "闪退", "weight": 0.6}, {"word": "挂掉", "weight": 0.5},
                {"word": "调试", "weight": 0.5}, {"word": "排查", "weight": 0.5},
                {"word": "故障", "weight": 0.5}, {"word": "出错", "weight": 0.5},
                {"word": "失灵", "weight": 0.4}, {"word": "修复", "weight": 0.4},
                {"word": "堆栈", "weight": 0.5}, {"word": "traceback", "weight": 0.6},
                {"word": "exception", "weight": 0.6}, {"word": "error", "weight": 0.5},
                {"word": "fix", "weight": 0.5}, {"word": "坑", "weight": 0.4},
            ],
            "patterns": [
                {"pattern": r"修\s*复", "weight": 0.6}, {"pattern": r"不\s*工作", "weight": 0.5},
                {"pattern": r"行为\s*异常", "weight": 0.6}, {"pattern": r"挂\s*了", "weight": 0.6},
                {"pattern": r"报\s*错", "weight": 0.6}, {"pattern": r"出\s*错", "weight": 0.5},
                {"pattern": r"崩\s*溃", "weight": 0.6}, {"pattern": r"闪\s*退", "weight": 0.6},
            ],
            "aliases": ["debug", "troubleshoot", "调试", "排错"],
            "negative_patterns": [
                r"开发\s*.*\s*(新\s*)?功能", r"实现\s*.*\s*(功能|需求)",
                r"创建\s*.*\s*(新\s*)?功能", r"设计\s*.*\s*新", r"写一个",
            ],
            "priority": 1,
            "min_confidence": 0.35
        },
        # ---------- test-driven-development ----------
        {
            "name": "test-driven-development",
            "description": "实现功能或修复 Bug 前的 TDD 流程",
            "phrases": [
                {"phrase": "先写测试", "weight": 0.9}, {"phrase": "写测试再实现", "weight": 0.9},
                {"phrase": "测试驱动开发", "weight": 0.9}, {"phrase": "红绿重构", "weight": 0.8},
                {"phrase": "测试先行", "weight": 0.8}, {"phrase": "补个测试", "weight": 0.7},
                {"phrase": "单元测试覆盖", "weight": 0.7}, {"phrase": "提高测试覆盖率", "weight": 0.7},
                {"phrase": "写单测", "weight": 0.7}, {"phrase": "增加测试用例", "weight": 0.7},
                {"phrase": "回归测试", "weight": 0.6}, {"phrase": "集成测试", "weight": 0.6},
                {"phrase": "端到端测试", "weight": 0.6}, {"phrase": "压力测试", "weight": 0.5},
                {"phrase": "冒烟测试", "weight": 0.5}, {"phrase": "测试覆盖率", "weight": 0.6},
                {"phrase": "模拟依赖", "weight": 0.5}, {"phrase": "mock 数据", "weight": 0.5},
                {"phrase": "断言", "weight": 0.5}, {"phrase": "断言失败", "weight": 0.6},
            ],
            "keywords": [
                {"word": "tdd", "weight": 0.9}, {"word": "测试", "weight": 0.4},
                {"word": "驱动", "weight": 0.3}, {"word": "red-green", "weight": 0.8},
                {"word": "mock", "weight": 0.5}, {"word": "断言", "weight": 0.5},
                {"word": "覆盖率", "weight": 0.5}, {"word": "unittest", "weight": 0.6},
                {"word": "pytest", "weight": 0.6}, {"word": "junit", "weight": 0.6},
                {"word": "test", "weight": 0.3},
            ],
            "patterns": [
                {"pattern": r"red\s*green", "weight": 0.8}, {"pattern": r"测试\s*驱动\s*开发", "weight": 0.9},
                {"pattern": r"单元\s*测试", "weight": 0.6}, {"pattern": r"写\s*测试", "weight": 0.6},
            ],
            "aliases": ["tdd", "red-green-refactor", "测试驱动"],
            "negative_patterns": [],
            "priority": 2,
            "min_confidence": 0.3
        },
        # ---------- brainstorming ----------
        {
            "name": "brainstorming",
            "description": "头脑风暴、设计新功能、创意工作",
            "phrases": [
                {"phrase": "头脑风暴", "weight": 0.9}, {"phrase": "脑暴一下", "weight": 0.8},
                {"phrase": "想个方案", "weight": 0.7}, {"phrase": "有什么想法", "weight": 0.8},
                {"phrase": "大家一起想想", "weight": 0.7}, {"phrase": "出出主意", "weight": 0.7},
                {"phrase": "设计思路", "weight": 0.7}, {"phrase": "架构选型", "weight": 0.7},
                {"phrase": "技术方案", "weight": 0.7}, {"phrase": "可行性分析", "weight": 0.6},
                {"phrase": "对比方案", "weight": 0.6}, {"phrase": "怎么设计好", "weight": 0.7},
                {"phrase": "有什么建议", "weight": 0.7}, {"phrase": "集思广益", "weight": 0.8},
                {"phrase": "发散思维", "weight": 0.7}, {"phrase": "灵光一现", "weight": 0.6},
                {"phrase": "创新点子", "weight": 0.7}, {"phrase": "颠覆性想法", "weight": 0.6},
                {"phrase": "重构思路", "weight": 0.6}, {"phrase": "优化方向", "weight": 0.6},
            ],
            "keywords": [
                {"word": "设计", "weight": 0.5}, {"word": "想法", "weight": 0.5},
                {"word": "方案", "weight": 0.4}, {"word": "创意", "weight": 0.6},
                {"word": "可行", "weight": 0.4}, {"word": "brainstorm", "weight": 0.8},
                {"word": "点子", "weight": 0.6}, {"word": "建议", "weight": 0.4},
                {"word": "思路", "weight": 0.5}, {"word": "架构", "weight": 0.5},
            ],
            "patterns": [
                {"pattern": r"设计\s*.*\s*(功能|系统|架构|数据库)", "weight": 0.7},
                {"pattern": r"怎么\s*.*\s*(实现|做|搞|设计)", "weight": 0.6},
                {"pattern": r"可行\s*.*\s*(性|吗)", "weight": 0.6},
                {"pattern": r"有什么\s*.*\s*(想法|方案|建议|套路)", "weight": 0.6},
            ],
            "aliases": ["brainstorm", "设计", "创意", "脑暴"],
            "negative_patterns": [r"已\s*.*\s*设计", r"确定\s*.*\s*方案", r"照着做"],
            "priority": 3,
            "min_confidence": 0.3
        },
        # ---------- writing-plans ----------
        {
            "name": "writing-plans",
            "description": "编写实施计划（在实现前）",
            "phrases": [
                {"phrase": "写个计划", "weight": 0.8}, {"phrase": "制定方案", "weight": 0.8},
                {"phrase": "拆解任务", "weight": 0.8}, {"phrase": "实施步骤", "weight": 0.8},
                {"phrase": "工作规划", "weight": 0.7}, {"phrase": "项目排期", "weight": 0.7},
                {"phrase": "技术方案设计", "weight": 0.8}, {"phrase": "怎么落地", "weight": 0.7},
                {"phrase": "安排一下", "weight": 0.6}, {"phrase": "列个清单", "weight": 0.7},
                {"phrase": "要做的事情", "weight": 0.6}, {"phrase": "开发计划", "weight": 0.7},
                {"phrase": "里程碑规划", "weight": 0.7}, {"phrase": "需求拆分", "weight": 0.7},
                {"phrase": "任务分配", "weight": 0.6}, {"phrase": "时间估算", "weight": 0.6},
                {"phrase": "风险评估", "weight": 0.5}, {"phrase": "预案", "weight": 0.5},
            ],
            "keywords": [
                {"word": "计划", "weight": 0.6}, {"word": "plan", "weight": 0.6},
                {"word": "实施方案", "weight": 0.6}, {"word": "步骤", "weight": 0.5},
                {"word": "规划", "weight": 0.5}, {"word": "排期", "weight": 0.5},
                {"word": "拆分", "weight": 0.5}, {"word": "落地", "weight": 0.4},
            ],
            "patterns": [
                {"pattern": r"写\s*.*\s*(计划|方案|规划)", "weight": 0.7},
                {"pattern": r"如何\s*.*\s*实施", "weight": 0.6},
                {"pattern": r"实施\s*.*\s*(计划|方案)", "weight": 0.6},
                {"pattern": r"制定\s*.*\s*(计划|方案)", "weight": 0.6},
                {"pattern": r"拆\s*解\s*.*\s*(任务|工作)", "weight": 0.7},
            ],
            "aliases": ["plan", "规划", "拆分任务"],
            "negative_patterns": [r"执行", r"开始写代码", r"动手"],
            "priority": 4,
            "min_confidence": 0.3
        },
        # ---------- requesting-code-review ----------
        {
            "name": "requesting-code-review",
            "description": "代码审查请求",
            "phrases": [
                {"phrase": "代码审查", "weight": 0.9}, {"phrase": "review 代码", "weight": 0.9},
                {"phrase": "帮我看看代码", "weight": 0.8}, {"phrase": "帮我审一下", "weight": 0.8},
                {"phrase": "检查一下代码", "weight": 0.7}, {"phrase": "代码走查", "weight": 0.8},
                {"phrase": "cr 一下", "weight": 0.8}, {"phrase": "提个 cr", "weight": 0.7},
                {"phrase": "看看有没有问题", "weight": 0.7}, {"phrase": "把关一下", "weight": 0.6},
                {"phrase": "审视代码", "weight": 0.7}, {"phrase": "代码检视", "weight": 0.7},
                {"phrase": "质量检查", "weight": 0.6}, {"phrase": "规范性检查", "weight": 0.6},
                {"phrase": "性能审查", "weight": 0.6}, {"phrase": "安全审查", "weight": 0.6},
            ],
            "keywords": [
                {"word": "review", "weight": 0.6}, {"word": "审查", "weight": 0.6},
                {"word": "检视", "weight": 0.5}, {"word": "走查", "weight": 0.6},
                {"word": "cr", "weight": 0.7}, {"word": "把关", "weight": 0.5},
                {"word": "审批", "weight": 0.4}, {"word": "检查", "weight": 0.3},
            ],
            "patterns": [
                {"pattern": r"代码\s*审查", "weight": 0.9}, {"pattern": r"review\s*代码", "weight": 0.9},
                {"pattern": r"审查\s*代码", "weight": 0.8}, {"pattern": r"检查\s*.*\s*代码", "weight": 0.6},
                {"pattern": r"走\s*查", "weight": 0.7},
            ],
            "aliases": ["review", "检查代码", "cr"],
            "negative_patterns": [],
            "priority": 5,
            "min_confidence": 0.3
        },
        # ---------- dispatching-parallel-agents ----------
        {
            "name": "dispatching-parallel-agents",
            "description": "并行任务处理",
            "phrases": [
                {"phrase": "并行处理", "weight": 0.9}, {"phrase": "并行执行", "weight": 0.9},
                {"phrase": "同时处理", "weight": 0.8}, {"phrase": "并发执行", "weight": 0.8},
                {"phrase": "拆开同时做", "weight": 0.8}, {"phrase": "多任务并行", "weight": 0.8},
                {"phrase": "异步处理", "weight": 0.7}, {"phrase": "多线程处理", "weight": 0.7},
                {"phrase": "协程并发", "weight": 0.6}, {"phrase": "批量执行", "weight": 0.6},
                {"phrase": "任务分发", "weight": 0.8}, {"phrase": "分发任务", "weight": 0.8},
                {"phrase": "负载均衡", "weight": 0.6}, {"phrase": "分片处理", "weight": 0.6},
                {"phrase": "并行编译", "weight": 0.6}, {"phrase": "并行测试", "weight": 0.6},
            ],
            "keywords": [
                {"word": "并行", "weight": 0.7}, {"word": "parallel", "weight": 0.7},
                {"word": "同时", "weight": 0.5}, {"word": "并发", "weight": 0.6},
                {"word": "多任务", "weight": 0.6}, {"word": "多线程", "weight": 0.6},
                {"word": "异步", "weight": 0.5}, {"word": "分发", "weight": 0.5},
                {"word": "批量", "weight": 0.4}, {"word": "分片", "weight": 0.5},
            ],
            "patterns": [
                {"pattern": r"并行\s*.*\s*(处理|执行|完成|编译)", "weight": 0.7},
                {"pattern": r"同时\s*.*\s*(做|处理|执行)", "weight": 0.6},
                {"pattern": r"分发\s*.*\s*(任务|工作)", "weight": 0.7},
                {"pattern": r"多\s*.*\s*(任务|agent|代理|线程)", "weight": 0.6},
                {"pattern": r"并发\s*.*\s*(执行|处理)", "weight": 0.7},
            ],
            "aliases": ["parallel", "多任务", "并发", "异步"],
            "negative_patterns": [],
            "priority": 6,
            "min_confidence": 0.3
        },
        # ---------- verification-before-completion ----------
        {
            "name": "verification-before-completion",
            "description": "完成前验证",
            "phrases": [
                {"phrase": "验证一下", "weight": 0.8}, {"phrase": "确认没问题", "weight": 0.8},
                {"phrase": "验证完成", "weight": 0.8}, {"phrase": "确保正确", "weight": 0.8},
                {"phrase": "检查是否完成", "weight": 0.7}, {"phrase": "回归验证", "weight": 0.7},
                {"phrase": "自测通过", "weight": 0.7}, {"phrase": "测试验证", "weight": 0.7},
                {"phrase": "上线前验证", "weight": 0.7}, {"phrase": "预发布验证", "weight": 0.7},
                {"phrase": "验收测试", "weight": 0.7}, {"phrase": "用户验收", "weight": 0.6},
                {"phrase": "冒烟验证", "weight": 0.6}, {"phrase": "功能验证", "weight": 0.7},
                {"phrase": "数据校验", "weight": 0.6}, {"phrase": "核对结果", "weight": 0.6},
                {"phrase": "确认生效", "weight": 0.7}, {"phrase": "看看好了没", "weight": 0.6},
            ],
            "keywords": [
                {"word": "验证", "weight": 0.6}, {"word": "verify", "weight": 0.6},
                {"word": "确认", "weight": 0.5}, {"word": "校验", "weight": 0.5},
                {"word": "验收", "weight": 0.5}, {"word": "检查", "weight": 0.3},
                {"word": "测试通过", "weight": 0.6}, {"word": "核对", "weight": 0.5},
                {"word": "确认", "weight": 0.5}, {"word": "验证", "weight": 0.6},
            ],
            "patterns": [
                {"pattern": r"验证\s*.*\s*(完成|正确|通过|生效)", "weight": 0.8},
                {"pattern": r"确认\s*.*\s*(完成|正确|生效)", "weight": 0.7},
                {"pattern": r"检查\s*.*\s*(是否|完成|正确)", "weight": 0.6},
                {"pattern": r"验证\s*.*\s*修复", "weight": 0.8},
                {"pattern": r"测\s*一\s*下", "weight": 0.5},
            ],
            "aliases": ["verify", "check", "验证", "验收"],
            "negative_patterns": [r"设计", r"开发", r"实现"],
            "priority": 7,
            "min_confidence": 0.3
        },
        # ---------- using-git-worktrees ----------
        {
            "name": "using-git-worktrees",
            "description": "Git Worktree 隔离工作",
            "phrases": [
                {"phrase": "git worktree", "weight": 0.9}, {"phrase": "worktree 隔离", "weight": 0.9},
                {"phrase": "工作树", "weight": 0.8}, {"phrase": "独立工作目录", "weight": 0.8},
                {"phrase": "新建工作树", "weight": 0.8}, {"phrase": "隔离分支开发", "weight": 0.8},
                {"phrase": "并行分支", "weight": 0.7}, {"phrase": "多分支同时开发", "weight": 0.8},
                {"phrase": "独立开发环境", "weight": 0.7}, {"phrase": "创建独立工作区", "weight": 0.8},
                {"phrase": "worktree 管理", "weight": 0.7}, {"phrase": "工作目录隔离", "weight": 0.7},
                {"phrase": "git 工作树", "weight": 0.8}, {"phrase": "添加 worktree", "weight": 0.8},
                {"phrase": "移除 worktree", "weight": 0.7}, {"phrase": "worktree 列表", "weight": 0.6},
            ],
            "keywords": [
                {"word": "worktree", "weight": 0.9}, {"word": "工作树", "weight": 0.7},
                {"word": "隔离", "weight": 0.5}, {"word": "独立分支", "weight": 0.6},
                {"word": "git", "weight": 0.3}, {"word": "分支", "weight": 0.3},
            ],
            "patterns": [
                {"pattern": r"worktree", "weight": 0.9}, {"pattern": r"工作\s*树", "weight": 0.8},
                {"pattern": r"隔离\s*.*\s*(开发|工作|分支)", "weight": 0.6},
                {"pattern": r"独立\s*.*\s*(分支|工作|环境)", "weight": 0.6},
                {"pattern": r"创建\s*worktree", "weight": 0.8},
            ],
            "aliases": ["git worktree", "工作树"],
            "negative_patterns": [],
            "priority": 8,
            "min_confidence": 0.3
        },
        # ---------- executing-plans ----------
        {
            "name": "executing-plans",
            "description": "执行实施计划",
            "phrases": [
                {"phrase": "执行计划", "weight": 0.9}, {"phrase": "按计划执行", "weight": 0.9},
                {"phrase": "开始干活", "weight": 0.7}, {"phrase": "开始动手", "weight": 0.7},
                {"phrase": "动手写代码", "weight": 0.7}, {"phrase": "编码实现", "weight": 0.7},
                {"phrase": "落地实施", "weight": 0.8}, {"phrase": "按照方案来", "weight": 0.8},
                {"phrase": "逐步实现", "weight": 0.7}, {"phrase": "推进开发", "weight": 0.7},
                {"phrase": "开始编码", "weight": 0.7}, {"phrase": "实现功能", "weight": 0.6},
                {"phrase": "干起来", "weight": 0.6}, {"phrase": "开始写", "weight": 0.6},
                {"phrase": "着手处理", "weight": 0.7}, {"phrase": "推进任务", "weight": 0.7},
                {"phrase": "迭代开发", "weight": 0.6}, {"phrase": "跟进执行", "weight": 0.7},
            ],
            "keywords": [
                {"word": "执行", "weight": 0.6}, {"word": "实现", "weight": 0.4},
                {"word": "开始", "weight": 0.4}, {"word": "动手", "weight": 0.5},
                {"word": "干", "weight": 0.4}, {"word": "落地", "weight": 0.5},
                {"word": "推进", "weight": 0.5}, {"word": "编码", "weight": 0.5},
                {"word": "开发", "weight": 0.3},
            ],
            "patterns": [
                {"pattern": r"执行\s*.*\s*(计划|方案|任务)", "weight": 0.8},
                {"pattern": r"开始\s*.*\s*(实现|开发|编码|写)", "weight": 0.6},
                {"pattern": r"按\s*.*\s*(步骤|计划|方案)", "weight": 0.7},
                {"pattern": r"逐步\s*.*\s*实现", "weight": 0.6},
                {"pattern": r"落\s*地", "weight": 0.6},
            ],
            "aliases": ["execute", "开始", "动手"],
            "negative_patterns": [r"计划一下", r"规划", r"设计一下"],
            "priority": 9,
            "min_confidence": 0.3
        },
        # ---------- finishing-a-development-branch ----------
        {
            "name": "finishing-a-development-branch",
            "description": "完成开发分支",
            "phrases": [
                {"phrase": "完成分支", "weight": 0.8}, {"phrase": "收尾工作", "weight": 0.8},
                {"phrase": "提交 pr", "weight": 0.9}, {"phrase": "提 pr", "weight": 0.9},
                {"phrase": "提交 mr", "weight": 0.9}, {"phrase": "提 mr", "weight": 0.9},
                {"phrase": "合并分支", "weight": 0.8}, {"phrase": "合代码", "weight": 0.8},
                {"phrase": "可以合入了", "weight": 0.8}, {"phrase": "cr 通过后合并", "weight": 0.8},
                {"phrase": "开发完成了", "weight": 0.7}, {"phrase": "完事了", "weight": 0.6},
                {"phrase": "搞定了", "weight": 0.6}, {"phrase": "弄完了", "weight": 0.6},
                {"phrase": "代码冻结", "weight": 0.5}, {"phrase": "发布前准备", "weight": 0.6},
                {"phrase": "打 tag", "weight": 0.6}, {"phrase": "发布版本", "weight": 0.6},
                {"phrase": "上线了", "weight": 0.5}, {"phrase": "部署完成", "weight": 0.6},
            ],
            "keywords": [
                {"word": "完成", "weight": 0.5}, {"word": "收尾", "weight": 0.6},
                {"word": "合并", "weight": 0.6}, {"word": "pr", "weight": 0.7},
                {"word": "mr", "weight": 0.7}, {"word": "merge", "weight": 0.7},
                {"word": "提交", "weight": 0.4}, {"word": "合入", "weight": 0.6},
                {"word": "上线", "weight": 0.5}, {"word": "发布", "weight": 0.5},
                {"word": "deploy", "weight": 0.5}, {"word": "finish", "weight": 0.5},
            ],
            "patterns": [
                {"pattern": r"完成\s*.*\s*(开发|功能|分支|任务)", "weight": 0.7},
                {"pattern": r"合并\s*.*\s*(到|成|入)", "weight": 0.6},
                {"pattern": r"提交\s*.*\s*(PR|MR|pr|mr)", "weight": 0.8},
                {"pattern": r"收尾\s*.*\s*(工作|开发|分支)", "weight": 0.7},
                {"pattern": r"合\s*代\s*码", "weight": 0.7},
            ],
            "aliases": ["finish", "complete", "merge", "合代码", "提交 PR"],
            "negative_patterns": [r"开始", r"开发新功能", r"设计"],
            "priority": 10,
            "min_confidence": 0.3
        },
        # ---------- subagent-driven-development ----------
        {
            "name": "subagent-driven-development",
            "description": "子代理驱动开发",
            "phrases": [
                {"phrase": "子代理开发", "weight": 0.9}, {"phrase": "使用子代理", "weight": 0.9},
                {"phrase": "派发给多个子代理", "weight": 0.9}, {"phrase": "子代理并行", "weight": 0.9},
                {"phrase": "多代理协同", "weight": 0.8}, {"phrase": "拆分给子 agent", "weight": 0.8},
                {"phrase": "subagent 并行", "weight": 0.9}, {"phrase": "多 agent 协作", "weight": 0.8},
                {"phrase": "子任务分发", "weight": 0.8}, {"phrase": "代理协作", "weight": 0.7},
                {"phrase": "并行代理", "weight": 0.8}, {"phrase": "分布式开发", "weight": 0.7},
                {"phrase": "委派给子代理", "weight": 0.8}, {"phrase": "分工协作", "weight": 0.6},
                {"phrase": "智能体协作", "weight": 0.7}, {"phrase": "子代理调度", "weight": 0.8},
                {"phrase": "代理集群", "weight": 0.7}, {"phrase": "多智能体", "weight": 0.7},
            ],
            "keywords": [
                {"word": "子代理", "weight": 0.8}, {"word": "subagent", "weight": 0.8},
                {"word": "代理", "weight": 0.4}, {"word": "agent", "weight": 0.4},
                {"word": "分发任务", "weight": 0.6}, {"word": "并行实现", "weight": 0.6},
                {"word": "多 agent", "weight": 0.7}, {"word": "协作", "weight": 0.5},
                {"word": "委派", "weight": 0.5}, {"word": "调度", "weight": 0.5},
                {"word": "集群", "weight": 0.4}, {"word": "智能体", "weight": 0.6},
            ],
            "patterns": [
                {"pattern": r"子代理", "weight": 0.8}, {"pattern": r"subagent", "weight": 0.8},
                {"pattern": r"多\s*agent", "weight": 0.7}, {"pattern": r"多\s*代理", "weight": 0.7},
                {"pattern": r"分发\s*.*\s*(任务|工作|给)", "weight": 0.6},
                {"pattern": r"并行\s*.*\s*(实现|开发|处理)", "weight": 0.6},
                {"pattern": r"协同", "weight": 0.5},
            ],
            "aliases": ["subagent", "多代理", "多 agent", "智能体"],
            "negative_patterns": [r"单线程", r"手动", r"自己搞"],
            "priority": 11,
            "min_confidence": 0.3
        },
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
        env_dir = os.environ.get("SKILLS_DIR")
        if env_dir and os.path.isdir(env_dir):
            return os.path.realpath(env_dir)

        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "skills"),
            os.path.join(here, "..", "skills"),
            os.path.join(here, "..", "..", "skills"),
            os.path.join(here, "..", "..", "..", "skills"),
        ]
        for cand in candidates:
            cand = os.path.realpath(cand)
            if not os.path.isdir(cand):
                continue
            if os.path.exists(os.path.join(cand, "using-superpowers", "SKILL.md")):
                return cand
            if os.path.exists(os.path.join(cand, "superpowers", "using-superpowers", "SKILL.md")):
                return cand
        return os.getcwd()

    def _load_config(self):
        """Load MANUAL_RULES and EXTERNAL_TRIGGERS from skills_config.yaml if available."""
        config_path = os.path.join(self.skills_dir, "..", "skills_config.yaml")
        if not HAS_YAML or not os.path.exists(config_path):
            return
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            if config:
                if "manual_rules" in config:
                    self.MANUAL_RULES = config["manual_rules"]
                if "external_triggers" in config:
                    self.EXTERNAL_TRIGGERS = config["external_triggers"]
                print(f"[Config] Loaded from {config_path}")
        except Exception as e:
            print(f"[Config] Failed to load {config_path}: {e}")

    def reload(self):
        self._loaded = False
        self._load_rules()

    def _load_rules(self):
        if self._loaded:
            return
        self.rules = []
        for rule_data in self.MANUAL_RULES:
            self.rules.append(self._parse_rule(rule_data))
        self._scan_new_skills()
        self.rules.sort(key=lambda r: r.priority)
        self._loaded = True

    # ------------------------------------------------------------------
    # 4.  RULE PARSING & SKILL SCANNING
    # ------------------------------------------------------------------
    def _parse_rule(self, data: Dict) -> SkillRule:
        keywords = []
        for kw in data.get("keywords", []):
            if isinstance(kw, str):
                keywords.append({"word": kw.lower(), "weight": 0.3})
            else:
                kw_copy = kw.copy()
                kw_copy["word"] = kw_copy["word"].lower()
                keywords.append(kw_copy)

        phrases = []
        for ph in data.get("phrases", []):
            if isinstance(ph, str):
                phrases.append({"phrase": ph.lower(), "weight": 0.5})
            else:
                ph_copy = ph.copy()
                ph_copy["phrase"] = ph_copy["phrase"].lower()
                phrases.append(ph_copy)

        patterns = []
        for pat in data.get("patterns", []):
            if isinstance(pat, str):
                patterns.append({"pattern": pat, "weight": 0.4})
            else:
                patterns.append(pat)

        return SkillRule(
            name=data["name"],
            description=data.get("description", ""),
            keywords=keywords,
            phrases=phrases,
            patterns=patterns,
            priority=data.get("priority", 99),
            aliases=[a.lower() for a in data.get("aliases", [])],
            negative_patterns=data.get("negative_patterns", []),
            min_confidence=data.get("min_confidence", 0.0)
        )

    def _scan_new_skills(self):
        skills_dir = self.skills_dir
        if not os.path.isdir(skills_dir):
            return

        processed_names = {r.name for r in self.rules}

        for root, dirs, files in os.walk(skills_dir):
            for fname in files:
                if fname != "SKILL.md":
                    continue
                skill_md = os.path.join(root, fname)
                rel = os.path.relpath(root, skills_dir)
                parts = rel.split(os.sep)
                skill_dir = parts[-1] if parts else root
                metadata = self.read_frontmatter(skill_md)
                if not metadata:
                    continue
                skill_name = metadata.get("name", skill_dir)
                if skill_name in processed_names:
                    continue
                auto_rule = self._generate_auto_rule(skill_name, metadata)
                if auto_rule:
                    self.rules.append(auto_rule)
                    processed_names.add(skill_name)

    def read_frontmatter(self, filepath: str) -> Optional[Dict]:
        try:
            with open(filepath, 'rb') as f:
                raw = f.read()
            if raw[:3] == b'\xef\xbb\xbf':
                raw = raw[3:]
            content = raw.decode('utf-8')
            content = content.replace('\r\n', '\n')

            match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
            if not match:
                return None

            fm_content = match.group(1)

            if HAS_YAML:
                try:
                    data = yaml.safe_load(fm_content)
                    return data if isinstance(data, dict) else None
                except:
                    pass

            # Fallback
            metadata = {}
            for line in fm_content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip()] = value.strip().strip('"').strip("'")
            return metadata
        except Exception:
            return None

    def _generate_auto_rule(self, skill_name: str, metadata: Dict) -> Optional[SkillRule]:
        description = metadata.get("description", "")
        triggers = self.EXTERNAL_TRIGGERS.get(skill_name, [])
        if not triggers:
            triggers = metadata.get("triggers")
            if isinstance(triggers, str):
                triggers = [t.strip() for t in triggers.split(",")]
            elif not isinstance(triggers, list):
                triggers = []

        if triggers and len(triggers) > 0:
            phrases = [{"phrase": t.lower(), "weight": 0.7} for t in triggers if t]
            return SkillRule(
                name=skill_name,
                description=description,
                keywords=[],
                phrases=phrases,
                patterns=[],
                priority=50,
                aliases=[skill_name.lower()] + [t.lower() for t in triggers if t],
                negative_patterns=[],
                min_confidence=0.3
            )

        if not description:
            return None

        keywords = self._extract_weighted_keywords(description)
        phrases = [{"phrase": skill_name.lower(), "weight": 0.5}]
        for kw in keywords[:2]:
            if len(kw["word"]) >= 2:
                phrases.append({"phrase": kw["word"], "weight": kw["weight"] * 0.8})

        return SkillRule(
            name=skill_name,
            description=description,
            keywords=keywords,
            phrases=phrases,
            patterns=[],
            priority=50,
            aliases=[skill_name.lower()],
            negative_patterns=[],
            min_confidence=0.25
        )

    def _extract_weighted_keywords(self, text: str) -> List[Dict]:
        words = re.findall(r'[\w\u4e00-\u9fff]+', text.lower())
        freq = defaultdict(int)
        for w in words:
            if w not in self.STOPWORDS and len(w) >= 2:
                freq[w] += 1
        result = []
        for w, cnt in freq.items():
            weight = min(0.6, 0.2 + 0.05 * cnt + 0.02 * len(w))
            result.append({"word": w, "weight": weight})
        result.sort(key=lambda x: x["weight"], reverse=True)
        return result[:10]

    # ------------------------------------------------------------------
    # 5.  FUZZY MATCHING & NEGATION
    # ------------------------------------------------------------------
    def _fuzzy_match(self, pattern: str, text: str, threshold: float = 0.85) -> bool:
        if pattern in text:
            return True
        pattern_len = len(pattern)
        if pattern_len < 3:
            return False
        for i in range(len(text) - pattern_len + 1):
            window = text[i:i+pattern_len]
            ratio = difflib.SequenceMatcher(None, pattern, window).ratio()
            if ratio >= threshold:
                return True
        return False

    def _has_negation(self, message: str, keyword: str, window: int = 5) -> bool:
        words = re.findall(r'[\w\u4e00-\u9fff]+', message.lower())
        for i, w in enumerate(words):
            if w == keyword:
                for j in range(max(0, i-window), i):
                    if words[j] in self.NEGATION_WORDS:
                        return True
        return False

    # ------------------------------------------------------------------
    # 6.  CORE CLASSIFY
    # ------------------------------------------------------------------
    def classify(self, message: str, context: Optional[ContextState] = None) -> List[SkillMatch]:
        if not message:
            return []

        message_lower = message.lower()
        ctx = context or self.context

        raw_scores = []

        # Pre-detect strong signals from other skills (for damping)
        strong_signal_map = {}
        for rule in self.rules:
            for ph in rule.phrases:
                if ph.get("weight", 0) >= 0.7 and ph.get("phrase", "") in message_lower:
                    strong_signal_map[rule.name] = True

        for rule in self.rules:
            score = 0.0
            reason_parts = []
            match_type = ""

            # Hard negative veto
            has_negative = False
            for neg_pattern in rule.negative_patterns:
                try:
                    if re.search(neg_pattern, message):
                        has_negative = True
                        break
                except re.error:
                    pass
            if has_negative:
                continue

            # Phrases (exact + fuzzy)
            for ph in rule.phrases:
                phrase = ph.get("phrase", "").lower()
                weight = ph.get("weight", 0.5)
                matched = False
                if phrase in message_lower:
                    negated = False
                    for neg in self.NEGATION_WORDS:
                        if neg + " " + phrase in message_lower or neg + phrase in message_lower:
                            negated = True
                            break
                    if not negated:
                        score += weight
                        reason_parts.append(f"phrase:{phrase}({weight:.1f})")
                        matched = True
                        if not match_type:
                            match_type = "phrase"
                if not matched and len(phrase) >= 3:
                    if self._fuzzy_match(phrase, message_lower, threshold=0.85):
                        fuzzy_weight = weight * 0.8
                        score += fuzzy_weight
                        reason_parts.append(f"fuzzy:{phrase}({fuzzy_weight:.1f})")
                        if not match_type:
                            match_type = "fuzzy"

            # Keywords
            for kw in rule.keywords:
                word = kw.get("word", "").lower()
                weight = kw.get("weight", 0.3)
                if word in message_lower:
                    if self._has_negation(message_lower, word):
                        reason_parts.append(f"negated:{word}")
                        continue
                    score += weight
                    reason_parts.append(f"keyword:{word}({weight:.1f})")
                    if not match_type:
                        match_type = "keyword"

            # Aliases
            for alias in rule.aliases:
                if alias.lower() in message_lower:
                    if self._has_negation(message_lower, alias.lower()):
                        continue
                    score += self.WEIGHT_ALIAS
                    reason_parts.append(f"alias:{alias}")
                    if not match_type:
                        match_type = "alias"

            # Patterns
            for pat in rule.patterns:
                pattern = pat.get("pattern", "")
                weight = pat.get("weight", 0.4)
                try:
                    if re.search(pattern, message):
                        score += weight
                        reason_parts.append(f"pattern({weight:.1f})")
                        if not match_type:
                            match_type = "pattern"
                except re.error:
                    pass

            # Context boost with damping
            if ctx.last_skill_used == rule.name:
                other_skill_signal = any(skill != rule.name for skill in strong_signal_map)
                if not other_skill_signal:
                    core_words = [kw["word"].lower() for kw in rule.keywords[:3]] + \
                                 [ph["phrase"].lower() for ph in rule.phrases[:2]]
                    if any(w in message_lower for w in core_words):
                        score += self.WEIGHT_CONTEXT_BOOST
                        reason_parts.append("context carryover")

            if score > 0:
                raw_scores.append((rule, score, reason_parts, match_type))

        if not raw_scores:
            self._log_unmatched(message, "no_match")
            return []

        max_score = max(s for _, s, _, _ in raw_scores)
        if max_score <= 0:
            return []

        matches = []
        for rule, raw_score, reasons, mtype in raw_scores:
            confidence = raw_score / max_score
            if confidence < max(rule.min_confidence, self.GLOBAL_MIN_CONFIDENCE):
                self._log_unmatched(message, f"low_confidence_{rule.name}_{confidence:.2f}")
                continue
            matches.append(SkillMatch(
                skill_name=rule.name,
                confidence=confidence,
                raw_score=raw_score,
                reason="; ".join(reasons),
                description=rule.description,
                match_type=mtype
            ))

        matches.sort(key=lambda x: x.confidence, reverse=True)
        return matches

    # ------------------------------------------------------------------
    # 7.  LOGGING
    # ------------------------------------------------------------------
    def _log_unmatched(self, message: str, reason: str):
        try:
            with open("skill_feedback.log", "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {reason}: {message}\n")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 8.  CONVENIENCE METHODS
    # ------------------------------------------------------------------
    def get_top_skill(self, message: str, min_confidence: float = None, context: Optional[ContextState] = None) -> Tuple[Optional[str], float, str]:
        if min_confidence is None:
            min_confidence = self.GLOBAL_MIN_CONFIDENCE
        matches = self.classify(message, context)
        for match in matches:
            if match.confidence >= min_confidence:
                return (match.skill_name, match.confidence, match.reason)
        return (None, 0, "no match")

    def generate_skill_context(self, message: str, context: Optional[ContextState] = None) -> str:
        matches = self.classify(message, context)
        if not matches:
            return ""

        top_matches = matches[:2]
        lines = ["## 🎯 Skill Recommendation", ""]

        for i, match in enumerate(top_matches, 1):
            icon = "⭐" if match.confidence >= 0.8 else "🔹"
            lines.append(f"{icon} **{i}. {match.skill_name}** (confidence: {match.confidence:.0%})")
            if match.description:
                lines.append(f"   - {match.description}")
            lines.append(f"   - {match.reason}")
            if match.confidence >= 0.8:
                lines.append(f"   - 💡 strongly recommended: {match.match_type} high match quality")
            lines.append(f'   - Usage: `skill_view("superpowers:{match.skill_name}")`')
            lines.append("")

        if len(matches) > 2:
            lines.append(f"There are {len(matches) - 2} related skills...")

        return "\n".join(lines)

    def update_context(self, skill_used: Optional[str] = None, message: str = ""):
        self.context.turn_count += 1
        if skill_used:
            self.context.last_skill_used = skill_used
        if message:
            self.context.recent_keywords.append(message[:50])
            if len(self.context.recent_keywords) > 5:
                self.context.recent_keywords = self.context.recent_keywords[-5:]

    def list_available_skills(self) -> List[Dict]:
        return [
            {
                "name": r.name,
                "description": r.description,
                "keyword_count": len(r.keywords),
                "phrase_count": len(r.phrases),
                "pattern_count": len(r.patterns),
                "alias_count": len(r.aliases),
                "priority": r.priority,
                "min_confidence": r.min_confidence
            }
            for r in self.rules
        ]


# ================ Skill Router ==================

class SkillRouter:
    """
    Routes tasks to appropriate skills, extracts parameters, and executes them.
    Includes security enhancements: shell commands use shlex.split and parameter sanitization.
    """
    def __init__(self, classifier: WeightedIntentClassifier, enable_watchdog: bool = True):
        self.classifier = classifier
        self.skill_metadata_cache: Dict[str, Dict] = {}
        self._watchdog_observer = None
        self._watchdog_thread = None
        self._reload_lock = threading.Lock()

        # Initial scan
        self._refresh_metadata_cache()

        # Start watchdog if available and enabled
        if enable_watchdog and HAS_WATCHDOG:
            self._start_watchdog()

    def reload(self):
        with self._reload_lock:
            self.classifier.reload()
            self._refresh_metadata_cache()

    def _refresh_metadata_cache(self):
        cache = {}
        skills_dir = self.classifier.skills_dir
        if not os.path.isdir(skills_dir):
            self.skill_metadata_cache = cache
            return

        for root, dirs, files in os.walk(skills_dir):
            for fname in files:
                if fname == "SKILL.md":
                    md_path = os.path.join(root, fname)
                    meta = self.classifier.read_frontmatter(md_path)
                    if meta and "name" in meta:
                        cache[meta["name"]] = meta
        self.skill_metadata_cache = cache

    def _start_watchdog(self):
        class SkillDirHandler(FileSystemEventHandler):
            def __init__(self, router):
                self.router = router
            def on_created(self, event):
                if event.is_file and event.src_path.endswith("SKILL.md"):
                    print(f"[HotReload] New skill detected: {event.src_path}")
                    self.router.reload()
            def on_modified(self, event):
                if event.is_file and event.src_path.endswith("SKILL.md"):
                    print(f"[HotReload] Skill modified: {event.src_path}")
                    self.router.reload()

        if not self.classifier.skills_dir or not os.path.isdir(self.classifier.skills_dir):
            return

        self._watchdog_observer = Observer()
        handler = SkillDirHandler(self)
        self._watchdog_observer.schedule(handler, self.classifier.skills_dir, recursive=True)
        self._watchdog_observer.start()
        print(f"[Watchdog] Monitoring skills directory: {self.classifier.skills_dir}")

    def stop_watchdog(self):
        if self._watchdog_observer:
            self._watchdog_observer.stop()
            self._watchdog_observer.join()
            self._watchdog_observer = None

    def route(self, task_message: str) -> Optional[SkillCall]:
        matches = self.classifier.classify(task_message)
        if not matches:
            return None

        top_match = matches[0]
        if top_match.confidence < 0.3:
            return None

        skill_name = top_match.skill_name
        meta = self.skill_metadata_cache.get(skill_name, {})

        # Extract parameters
        parameters = self._extract_parameters(task_message, meta.get("parameters", []))

        # Determine execution
        execution_type = "prompt"
        execution_target = f"Please use the '{skill_name}' skill to handle this task:\n{task_message}"

        if meta.get("execution"):
            exec_cfg = meta["execution"]
            execution_type = exec_cfg.get("type", "prompt")
            execution_target = exec_cfg.get("target", execution_target)
            if execution_type == "shell" and isinstance(execution_target, str):
                for k, v in parameters.items():
                    execution_target = execution_target.replace(f"{{{{{k}}}}}", str(v) if v is not None else "")

        return SkillCall(
            skill_name=skill_name,
            confidence=top_match.confidence,
            parameters=parameters,
            execution_type=execution_type,
            execution_target=execution_target,
            raw_reason=top_match.reason
        )

    def _extract_parameters(self, message: str, param_defs: List[Dict]) -> Dict[str, Any]:
        params = {}
        for pdef in param_defs:
            pname = pdef["name"]
            default = pdef.get("default", None)
            patterns = [
                rf"{pname}\s*[:=]\s*(\S+)",
                rf"{pname}\s+(\S+)",
            ]
            value = None
            for pat in patterns:
                m = re.search(pat, message, re.IGNORECASE)
                if m:
                    value = m.group(1).strip()
                    break
            if value is None:
                value = default
            params[pname] = value
        return params

    def _sanitize(self, value: str) -> str:
        dangerous = r"[;|&$`(){}<>]"
        return re.sub(dangerous, "", str(value))

    def execute(self, skill_call: SkillCall) -> str:
        if skill_call.execution_type == "shell":
            try:
                cmd_str = skill_call.execution_target
                parts = shlex.split(cmd_str)
                safe_parts = [self._sanitize(p) for p in parts]
                result = subprocess.run(
                    safe_parts,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                output = result.stdout or result.stderr
                return output or "(shell command executed with no output)"
            except subprocess.TimeoutExpired:
                return "Error: Shell command timed out after 60 seconds."
            except Exception as e:
                return f"Error executing shell command: {e}"
        elif skill_call.execution_type == "prompt":
            return f"[PROMPT] {skill_call.execution_target}"
        else:
            return f"Unknown execution type: {skill_call.execution_type}"


# ================ Global Instances ==================

_classifier = None
_router = None

def get_classifier() -> WeightedIntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = WeightedIntentClassifier()
    return _classifier

def get_router(enable_watchdog: bool = True) -> SkillRouter:
    global _router
    if _router is None:
        _router = SkillRouter(get_classifier(), enable_watchdog=enable_watchdog)
    return _router

def classify_intent(message: str, context: Optional[ContextState] = None) -> List[SkillMatch]:
    return get_classifier().classify(message, context)

def get_recommended_skill(message: str, min_confidence: float = None, context: Optional[ContextState] = None) -> Tuple[Optional[str], float, str]:
    return get_classifier().get_top_skill(message, min_confidence, context)

def route_task(message: str) -> Optional[SkillCall]:
    return get_router().route(message)

def execute_skill(skill_call: SkillCall) -> str:
    return get_router().execute(skill_call)

def reload_all():
    get_router().reload()


# ================ Main / Test ==================

if __name__ == "__main__":
    print("=" * 60)
    print("AgentRouter v4.3 - Open Source Ready")
    print("=" * 60)

    classifier = get_classifier()
    print("\nRegistered skills:")
    for skill in sorted(classifier.list_available_skills(), key=lambda x: x['priority']):
        print(f"  [{skill['priority']:2d}] {skill['name']:40s} (kw:{skill['keyword_count']}, ph:{skill['phrase_count']})")

    router = get_router(enable_watchdog=False)

    test_cases = [
        ("fix this bug", "systematic-debugging"),
        ("先写测试再实现", "test-driven-development"),
        ("头脑风暴一下新功能", "brainstorming"),
        ("代码审查", "requesting-code-review"),
        ("并行处理这三任务", "dispatching-parallel-agents"),
        ("验证修复是否完成", "verification-before-completion"),
        ("用 worktree 隔离开发", "using-git-worktrees"),
        ("开始执行计划", "executing-plans"),
        ("完成开发分支", "finishing-a-development-branch"),
        ("使用子代理开发", "subagent-driven-development"),
        ("帮我开发一个新功能", None),
        ("修改一下文案", None),
        ("这不是bug", None),
        ("设计一个新系统", "brainstorming"),
        ("修护 bug", "systematic-debugging"),   # typo test
    ]

    print("\n" + "=" * 60)
    print("Routing test (including fuzzy matching):")
    print("=" * 60)

    for msg, expected in test_cases:
        call = route_task(msg)
        if call:
            status = "✓" if call.skill_name == expected else "✗"
            print(f"\n{status} '{msg}'")
            print(f"  → {call.skill_name} (confidence: {call.confidence:.0%})")
            print(f"  → execution: {call.execution_type} -> {call.execution_target[:80]}...")
        else:
            status = "✓" if expected is None else "✗"
            print(f"\n{status} '{msg}' - no match (expected {expected})")

    print("\n" + "=" * 60)
    print("📋 External Triggers (EXTERNAL_TRIGGERS) currently configured:")
    if classifier.EXTERNAL_TRIGGERS:
        for skill, triggers in classifier.EXTERNAL_TRIGGERS.items():
            print(f"  - {skill}: {', '.join(triggers)}")
    else:
        print("  (none configured)")

    print("\n💡 To add triggers for a new skill without editing SKILL.md:")
    print("   Edit WeightedIntentClassifier.EXTERNAL_TRIGGERS in the code.")
    print("   Or create skills_config.yaml with 'external_triggers' section.")
    print("\n📊 Unmatched messages will be logged to skill_feedback.log for tuning.")

    if HAS_WATCHDOG:
        print("\n[Watchdog] Available - new skills will be auto-detected.")
    else:
        print("\n[Watchdog] Not installed. Install with: pip install watchdog")

    if HAS_YAML:
        print("[YAML] Configuration loaded from skills_config.yaml if present.")
    else:
        print("[YAML] pyyaml not installed, using hardcoded config.")

    if router._watchdog_observer:
        router.stop_watchdog()
