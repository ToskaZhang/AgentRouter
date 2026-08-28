📖 简介
AgentRouter 是一个轻量级、零依赖（可选）的本地意图识别与技能路由引擎，专为 AI 编程助手（如 Cursor、Cline、Continue 等）设计。

它能在毫秒级内判断用户意图，自动匹配最合适的技能（Skill），并安全地执行（Shell / Prompt / API），全程不消耗任何 Token。

🎯 核心价值
传统方案	AgentRouter
调用 LLM 做意图识别	本地规则引擎，毫秒响应
高成本、高延迟	零 Token 开销，确定性高
难以定制触发词	支持 YAML 配置 + 热加载
容易被上下文带偏	上下文阻尼 + 负向硬否决
Shell 命令安全风险	参数自动清洗，禁用 shell=True
新技能需改代码	自动扫描 SKILL.md，即插即用
✨ 核心特性
⚡ 零 Token 开销：纯本地规则匹配，不调用任何 LLM API

🔍 模糊匹配：自动纠正用户错别字（如“修护 bug”→“修复 bug”）

🔒 安全沙箱：Shell 命令自动过滤危险字符（;、|、$() 等）

🧩 即插即用：放入 SKILL.md 自动识别，支持 triggers 字段

🔄 热加载：配合 Watchdog，新增/修改技能自动生效

📊 反馈日志：自动记录未命中消息，方便持续调优

⚙️ 外部配置：支持 YAML 文件管理触发词，无需修改代码

🧠 上下文阻尼：避免话题切换时被旧上下文带偏
🚀 快速上手
1. 安装
bash
# 推荐：直接 clone 仓库
git clone https://github.com/ToskaZhang/AgentRouter.git
cd AgentRouter

# 安装可选依赖（强烈推荐）
pip install pyyaml watchdog
2. 目录结构
text
AgentRouter/
├── intent_classifier.py          # 核心代码
├── skills/                       # 技能文件夹
│   └── using-superpowers/
│       └── SKILL.md              # 超级技能标准格式
├── skills_config.yaml            # 外部配置（可选）
├── skill_feedback.log            # 自动生成的反馈日志
└── LICENSE                       # MIT License
3. 添加第一个技能
在 skills/ 下创建一个技能文件夹（如 db-migrate/），放入 SKILL.md：

yaml
---
name: db-migrate
description: 数据库迁移工具
triggers:
  - 迁移数据库
  - 改表结构
  - 新增字段
  - 执行迁移
parameters:
  - name: migration_name
    type: string
    required: true
execution:
  type: shell
  target: "python manage.py migrate {{migration_name}}"
---
4. 在代码中使用
python
from intent_classifier import route_task, execute_skill

# 路由
task = "帮我迁移数据库"
call = route_task(task)

if call:
    print(f"✅ 匹配技能: {call.skill_name} (置信度: {call.confidence:.0%})")
    print(f"📦 参数: {call.parameters}")
    
    # 执行
    result = execute_skill(call)
    print(f"📤 结果: {result}")
else:
    print("❌ 未找到合适的技能")
5. 输出示例
text
✅ 匹配技能: db-migrate (置信度: 92%)
📦 参数: {'migration_name': None}
📤 结果: (shell command executed with no output)
⚙️ 配置详解
方式一：环境变量（推荐用于部署）
bash
# 指定技能目录
export SKILLS_DIR=/path/to/your/skills

# 然后在代码中自动生效
python your_agent.py
方式二：外部 YAML 配置（推荐用于团队协作）
在项目根目录创建 skills_config.yaml：

yaml
# 覆盖内置规则
manual_rules:
  - name: my-custom-skill
    description: 自定义技能
    phrases:
      - phrase: 自定义触发
        weight: 0.8
    priority: 12

# 外部触发词映射（无需修改 SKILL.md）
external_triggers:
  db-migrate:
    - 迁移
    - 改表
    - 字段变更
  deploy-helper:
    - 部署
    - 发布
    - 上线
方式三：代码中直接修改
python
from intent_classifier import get_classifier

classifier = get_classifier()
classifier.EXTERNAL_TRIGGERS["my-skill"] = ["触发词1", "触发词2"]
classifier.reload()  # 立即生效
📚 工作原理
text
┌─────────────────────────────────────────────────────────────┐
│                      用户输入                                │
│              "修护一下登录报错"                              │
└────────────────────┬────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              1. 加权打分（多规则并行）                      │
│  ┌──────────────────┐  ┌──────────────────┐               │
│  │ systematic-      │  │ test-driven-     │               │
│  │ debugging        │  │ development      │               │
│  │ 关键词: bug ✓    │  │ 关键词: 测试 ✗  │               │
│  │ 短语: 修bug ✓    │  │ 短语: TDD ✗     │               │
│  │ 模糊: 修护→修bug │  │                  │               │
│  │ 得分: 0.85       │  │ 得分: 0.05      │               │
│  └──────────────────┘  └──────────────────┘               │
└────────────────────┬────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────┐
│          2. 归一化 + 置信度过滤                            │
│  最高分 0.85 → 归一化为 100%                              │
│  其他技能按比例衰减                                        │
│  置信度 > 0.3 才返回                                       │
└────────────────────┬────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────┐
│         3. 上下文阻尼（防止话题切换误判）                   │
│  上次用了 debugging，但这次有 "部署" 强信号                │
│  → 取消上下文加成，切换到 deploy-helper                     │
└────────────────────┬────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────────┐
│         4. 参数提取 + 安全执行                              │
│  提取参数: {migration_name: "login"}                       │
│  Shell 命令参数自动清洗（过滤危险字符）                    │
│  执行: python manage.py migrate login                      │
└─────────────────────────────────────────────────────────────┘
🔧 高级用法
1. 使用上下文记忆
python
from intent_classifier import get_classifier, ContextState

classifier = get_classifier()
ctx = ContextState()

# 第一次调用
skill, conf, _ = classifier.get_top_skill("fix login bug", context=ctx)
classifier.update_context(skill, "fix login bug")

# 第二次调用（会继承上下文）
skill, conf, _ = classifier.get_top_skill("验证一下", context=ctx)
# 如果没有 "验证" 强信号，会优先考虑上次的 debugging 技能
2. 查看所有已注册技能
python
from intent_classifier import get_classifier

for skill in get_classifier().list_available_skills():
    print(f"{skill['name']:40s} 优先级: {skill['priority']}")
3. 禁用 Watchdog（节省资源）
python
from intent_classifier import get_router

# 不启动文件监控
router = get_router(enable_watchdog=False)

# 手动重载
router.reload()
📝 反馈日志调优
每次未命中或低置信度的匹配，会自动记录到 skill_feedback.log：

text
[2026-08-29 14:23:45] no_match: 帮我压缩一下这个文件夹
[2026-08-29 14:25:12] low_confidence_db-migrate_0.21: 数据库结构要改
调优建议：

看到 no_match → 往对应技能加 triggers 或 phrases

看到 low_confidence → 提高该技能的权重词数量或权重值

🤝 贡献指南
欢迎贡献！无论是新的触发词、Bug 修复还是功能增强。

1. 添加新技能（无需改代码）
在 skills/ 下创建 SKILL.md，添加 triggers 字段即可。

2. 改进内置规则
编辑 WeightedIntentClassifier.MANUAL_RULES，提交 PR。

3. 完善测试用例
在 if __name__ == "__main__" 块中增加测试用例。

4. 报告 Bug
提 Issue 时请附带：

完整错误堆栈

你使用的 Python 版本

触发问题的用户输入

📦 依赖
包	版本	用途	必需
Python	>=3.8	运行环境	✅
pyyaml	>=5.0	YAML 配置解析	可选
watchdog	>=2.0	热加载文件监控	可选
🛣️ 路线图
□ 支持更丰富的参数提取（LLM 辅助）
□ 插件化架构（支持自定义匹配器）
□ Web UI 管理控制台
□ Docker 镜像一键部署
📄 License
本项目采用 MIT License，你可以自由使用、修改、商用、分发。

🙏 致谢
deepseek hermes Agent - 启发了技能定义标准

所有贡献者和用户

📧 联系
作者：[ToskaZhang]

GitHub：[https://github.com/ToskaZhang]

Issues：[https://github.com/ToskaZhang/AgentRouter]

如果这个项目帮到了你，请给它一个 ⭐ Star 支持一下！
