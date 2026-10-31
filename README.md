# HOLYXIETE

**中文** · [English](README.en.md)

> **HOLYXIETE** —— 一个跑在终端里的 AI 编程智能体（CLI Code Agent）  
> 由 Hugging Face [smolagents](https://github.com/huggingface/smolagents) 的 `CodeAgent` 驱动：模型写出 Python 代码 → 在本地沙箱里直接执行 → 调用文件读写 / Shell 工具完成任务。

```
██╗  ██╗ ██████╗ ██╗     ██╗   ██╗██╗  ██╗██╗███████╗████████╗███████╗
██║  ██║██╔═══██╗██║     ╚██╗ ██╔╝╚██╗██╔╝██║██╔════╝╚══██╔══╝██╔════╝
███████║██║   ██║██║      ╚████╔╝  ╚███╔╝ ██║█████╗     ██║   █████╗
██╔══██║██║   ██║██║       ╚██╔╝   ██╔██╗ ██║██╔══╝     ██║   ██╔══╝
██║  ██║╚██████╔╝███████╗   ██║   ██╔╝ ██╗██║███████╗   ██║   ███████╗
╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚══════╝   ╚═╝   ╚══════╝
```

> 命令行入口仍为 `xiete`（包名/命令未变，仅界面品牌显示为 HOLYXIETE）。

当前版本：**v0.1.0**

---

## 特性

| 能力 | 说明 |
| --- | --- |
| 🐋 默认适配 DeepSeek | 开箱即用对接 **DeepSeek-V4.1-Flash-1017**（`deepseek-flash`），自动处理思考模式兼容问题 |
| 🧠 代码式 Agent | 基于 `smolagents.CodeAgent`，模型生成 Python 代码并执行，而不是 JSON 工具调用 |
| 🖥️ 终端 UI | `rich` + `prompt_toolkit`：渐变 ASCII Logo 面板、Spinner 加载动画、Markdown 代码高亮 |
| ⌨️ 全局唤醒 | `pip install -e .` 后任意目录输入 `xiete` 即可使用 |
| 🗂️ 历史记录 | 上下键翻阅历史，持久化到本地文件 |
| 🔌 多服务商 | 任何 OpenAI 兼容接口：DeepSeek / OpenAI / Moonshot / 通义 / Ollama / vLLM / one-api |
| ⚙️ 配置灵活 | 环境变量或项目 `.env` 文件，带自动向上查找 |
| 🛡️ 安全护栏 | 工具只能访问工作目录、Shell 命令 30s 超时 + 高危命令拦截 |

---

## 快速开始

### 1. 安装

```bash
# 在项目目录（含 pyproject.toml 的 xiete-cli/）下执行
cd xiete-cli
pip install -e .
```

> 建议使用虚拟环境，避免污染全局 Python：
>
> ```bash
> python -m venv .venv
> source .venv/bin/activate        # Windows: .venv\Scripts\activate
> pip install -e .
> ```

安装完成后，`xiete` 命令会被注册到 Python 的 Scripts 目录中，在**任意目录**下都可直接调用：

```bash
xiete --version
```

如果提示找不到命令，请确认该 Scripts 目录已加入 `PATH`（Windows 通常是 `%APPDATA%\Python\Python3xx\Scripts`）。

### 2. 配置 DeepSeek API Key

XIETE 默认就对接 **DeepSeek-V4.1-Flash-1017**，只需填入你自己的 Key。

先到 [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) 创建 Key，然后：

```bash
cp .env.example .env          # macOS / Linux
copy .env.example .env        # Windows CMD
Copy-Item .env.example .env   # PowerShell
```

编辑 `.env`，只需改第一行（其余三行的默认值已经是对的）：

```dotenv
XIETE_API_KEY=sk-your-deepseek-key-here     # ← 改成你自己的 Key
XIETE_BASE_URL=https://api.deepseek.com     # ← 默认已正确
XIETE_MODEL=deepseek-flash                  # ← 默认已正确
```

或者直接用系统环境变量（优先级高于 `.env`，适合不想落地明文 Key 的场景）：

```powershell
# Windows PowerShell（当前会话有效）
$env:XIETE_API_KEY="sk-your-deepseek-key-here"
$env:XIETE_BASE_URL="https://api.deepseek.com"
$env:XIETE_MODEL="deepseek-flash"

# 永久写入用户环境变量
[Environment]::SetEnvironmentVariable("XIETE_API_KEY","sk-your-deepseek-key-here","User")
```

```bash
# macOS / Linux
export XIETE_API_KEY="sk-your-deepseek-key-here"
```

配置完成后可以随时在 XIETE 里输入 `/config` 核对是否生效。

### 3. 启动

```bash
xiete                                    # 进入交互模式
xiete "给 utils.py 补一个单元测试并运行"    # 单次任务模式
```

---

## DeepSeek 适配说明（重要）

### 推荐配置

| 配置项 | 值 | 说明 |
| --- | --- | --- |
| `XIETE_API_KEY` | `sk-...`（你自己提供） | 在 DeepSeek 开放平台创建 |
| `XIETE_BASE_URL` | `https://api.deepseek.com` | 官方 OpenAI 兼容端点。**不需要**写 `/v1`（写了也能用） |
| `XIETE_MODEL` | `deepseek-flash` | DeepSeek-V4.1-Flash-1017，1M 上下文，推荐 |

### 模型名对照

| 模型 | `XIETE_MODEL` 取值 | 说明 |
| --- | --- | --- |
| DeepSeek-V4.1-Flash-1017 | `deepseek-flash` | **默认推荐**，快、便宜、擅长编程 |
| DeepSeek-V4-Pro-0813 | `deepseek-v4-pro` | 更强，单价更高 |
| 旧别名 | `deepseek-v4-flash` / `deepseek-v4.1-flash` / `deepseek-v4.1-flash-1017` | 仍被接受，服务端会路由到 V4.1-Flash，XIETE 会自动归一为 `deepseek-flash` |

> ⚠️ 旧的 `deepseek-chat` / `deepseek-reasoner` 已不是当前模型名，请改用上表取值。

### XIETE 已经帮你处理好的三个 DeepSeek 思考模式“坑”

DeepSeek V4 默认开启思考模式（thinking），它有三条规则会直接让普通的 OpenAI 兼容客户端报 **HTTP 400**。XIETE 的 `DeepSeekModel` 已自动适配，无需手动配置：

| # | DeepSeek 规则 | 如果不处理会怎样 | XIETE 的处理 |
| --- | --- | --- | --- |
| 1 | 思考模式下 `tool_choice` 只能是 `auto` / `none`，传 `required` 会 400 | smolagents 默认就传 `required`，**每次调用都失败** | 自动改写为 `tool_choice="auto"` |
| 2 | 请求带 `tools` 时，后续轮次的 assistant 消息必须回传 `reasoning_content` | 从第 2 步开始 400，多步 Agent 必然失败 | 逐轮捕获并在下一轮按顺序回传 |
| 3 | 思考模式下 `temperature` 不生效 | 不报错但设置被静默忽略，行为难预期 | 思考模式下自动移除，关闭思考后才下发 |

此外思考模式通过 `extra_body={"thinking": {"type": "enabled"}}` 显式固定，不依赖服务端默认值。

### 思考模式开关

```dotenv
# 默认开启：准确率更高，适合复杂编程任务
XIETE_THINKING=enabled

# 关闭：响应更快、更省 token，适合简单问答
XIETE_THINKING=disabled

# 控制思考强度（默认 high）：low / high / max
XIETE_REASONING_EFFORT=high
```

> 填 `XIETE_REASONING_EFFORT=none` 等同于关闭思考模式。

---

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `XIETE_API_KEY` | ✅ | — | API Key；未设置时依次回退 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY` |
| `XIETE_BASE_URL` | | `https://api.deepseek.com` | OpenAI 兼容接口地址 |
| `XIETE_MODEL` | | `deepseek-flash` | 模型名称 |
| `XIETE_THINKING` | | `enabled` | DeepSeek 思考模式开关（`enabled` / `disabled`） |
| `XIETE_REASONING_EFFORT` | | 服务端默认 `high` | 思考强度：`low` / `high` / `max` / `none` |
| `XIETE_MAX_STEPS` | | `40` | Agent 单次任务最大推理步数 |
| `XIETE_TIMEOUT` | | `300` | 单次模型请求超时（秒），思考模式较慢 |
| `XIETE_TEMPERATURE` | | 服务商默认 | 采样温度，**仅在关闭思考模式时生效** |
| `XIETE_HISTORY_FILE` | | 系统状态目录 | 自定义输入历史文件路径 |
| `XIETE_SYSTEM_PROMPT` | | 不设置 | 系统提示词追加文件路径，内容叠加在内置规则之后，见 [编辑系统提示词](#编辑系统提示词) |

### 配置文件查找顺序

1. 已存在的进程环境变量（最高优先级）
2. 当前工作目录的 `.env`
3. 向上逐级回溯（最多 5 层）的 `.env`；遇到 `.git` / `pyproject.toml` 视为项目根并停止

### 切换到其他服务商

只用 DeepSeek 时无需关心这些。要切到别家，把三个变量一起改掉即可（此时 XIETE 会自动改用标准 `OpenAIModel`，不再套用 DeepSeek 的思考模式改写）：

```dotenv
# OpenAI
XIETE_BASE_URL=https://api.openai.com/v1
XIETE_MODEL=gpt-4o

# 通义千问（DashScope 兼容模式）
XIETE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
XIETE_MODEL=qwen-max

# 智谱 GLM
XIETE_BASE_URL=https://open.bigmodel.cn/api/paas/v4
XIETE_MODEL=glm-4-plus

# 本地 Ollama（无需真实 Key，填占位符即可）
XIETE_API_KEY=ollama
XIETE_BASE_URL=http://localhost:11434/v1
XIETE_MODEL=qwen2.5-coder:14b
```

> 💡 走 Ollama / one-api 等代理访问 DeepSeek 时，只要 `XIETE_MODEL` 仍以 `deepseek` 开头，XIETE 依旧会启用思考模式适配。

---

## 使用说明

### 交互模式（`xiete`）

启动后会清屏并显示 Logo 面板，包含版本号、当前工作目录、挂载的模型与快捷键提示，然后进入 REPL：

```
❯ xiete 分析一下这个项目的目录结构，并说明入口文件在哪
```

- `Enter` 发送指令
- `↑` / `↓` 翻阅历史输入
- `Ctrl+C` **仅中断当前任务**，不会退出 CLI
- `Ctrl+D` 退出（等待输入时按 `Ctrl+C` 只会提示如何退出）

### 内置斜杠命令

| 命令 | 说明 |
| --- | --- |
| `/help` | 显示帮助与已挂载工具列表 |
| `/clear` | 清屏并重绘 Logo 面板 |
| `/config` | 查看当前 API Key（脱敏）、Base URL、模型等配置 |
| `/reset` | 重置 Agent 记忆，开启全新对话上下文 |
| `/exit` / `/quit` | 优雅退出 |

### 单次任务模式

```bash
xiete "把 src/utils.py 里的函数都加上类型注解"
xiete "解释 ./app.py 的作用，输出 3 句话"
xiete -m deepseek-v4-pro "列出这个项目里所有的 TODO"
```

也可以从管道或文件读取任务：

```bash
echo "统计仓库里有多少个 .py 文件" | xiete
xiete < task.txt
```

### 命令行参数

```bash
xiete --help
```

| 参数 | 说明 |
| --- | --- |
| `-m, --model` | 本次运行使用的模型（覆盖环境变量） |
| `-b, --base-url` | 本次运行的 API 地址 |
| `-k, --api-key` | 本次运行的 API Key（**不推荐**，会留在 shell 历史里） |
| `--max-steps` | Agent 最大推理步数 |
| `-v, --verbose` | 打印 smolagents 内部步骤日志，便于调试 |
| `--version` | 显示版本号 |

---

## 内置工具

工具定义在 `xiete/tools.py`，使用 `smolagents` 的 `@tool` 装饰器（含完整类型注解与 Google 风格 Docstring）。

| 工具 | 签名 | 说明 |
| --- | --- | --- |
| `read_file` | `(file_path: str, max_lines: int \| None = None) -> str` | 读取文件文本内容，自动拒绝二进制文件 |
| `write_file` | `(file_path: str, content: str) -> str` | 创建或覆盖写入，自动创建父目录 |
| `list_directory` | `(dir_path: str = ".", max_depth: int = 2, name_filter: str \| None = None) -> str` | 树状列出目录结构，自动跳过 `.git`/`node_modules` 等 |
| `run_shell_command` | `(command: str) -> str` | 执行终端命令，返回退出码、stdout、stderr |

### 安全边界

- **路径沙箱**：所有文件工具只能访问启动时的工作目录及其子目录，`../` 越界会被拒绝。
- **Shell 超时**：命令超过 30 秒会被强制终止并返回部分输出。
- **高危拦截**：`rm -rf`、`mkfs`、`dd of=`、`shutdown`、`git push --force`、`curl | sh` 等模式会被直接阻断并告知原因。
- **不使用 shell 解释器**：命令以参数列表方式执行（`shell=False`），因此管道、重定向、通配符不会被解释，也杜绝了命令注入。
- **只读模式**：调用 `configure_tools(allow_write=False)` 可禁用写文件能力。

---

## 项目结构

```text
xiete-cli/
├── pyproject.toml         # 依赖项与 [project.scripts] xiete = "xiete.cli:main"
├── .env.example           # 环境变量配置模板
├── README.md              # 本文档（中文）
├── README.en.md           # English documentation
├── LICENSE                # MIT
└── xiete/
    ├── __init__.py        # __version__ = "0.1.0"
    ├── cli.py             # 终端入口、REPL 循环、斜杠命令、参数解析
    ├── ui.py              # XIETE_LOGO 字符画（HOLYXIETE）、Banner 渲染、Rich 样式封装
    ├── agent.py           # 配置加载（.env / 环境变量）+ CodeAgent 初始化
    └── tools.py           # @tool 本地工具实现
```

### 自定义 Logo

`xiete/ui.py` 顶部有独立的 **LOGO 区域**，整个字符画就是一个字符串常量：

```python
XIETE_LOGO: str = r"""
██╗  ██╗ ██████╗ ...
"""
```

直接替换成你自己的 ASCII Art 即可。当前品牌为 **HOLYXIETE**，渲染时会自动按字符列做 `#ffe066 → #c8912a`（金黄色）对角渐变；渐变端点可通过 `LOGO_GRADIENT` 调整，支持 `#rrggbb` 十六进制色值与 `gold` / `yellow` 等名称。

### 编辑系统提示词

内置规则写在 `xiete/agent.py` 的 `AGENT_INSTRUCTIONS` 常量里（工具使用方法、安全边界等 6 条）。**不建议直接改源码**，推荐用外部文件追加：

**方式一：项目内放一个 `XIETE_PROMPT.md`（最省事）**

在启动 `xiete` 的目录下新建文件（或放在上层项目根目录），重启即生效：

```markdown
# 额外要求

- 所有回答一律使用简体中文。
- 修改代码前先说明改动计划。
- 提交信息遵循 Conventional Commits 规范。
```

**方式二：用环境变量指定任意路径**

```bash
# .env 或环境变量中
XIETE_SYSTEM_PROMPT=.\my_prompt.md
```

**优先级**：`XIETE_SYSTEM_PROMPT` 指定的文件 → 工作目录下的 `XIETE_PROMPT.md` → 上层目录（最多 5 层）下的 `XIETE_PROMPT.md` → 都不用，仅使用内置规则。

**行为说明**

- 文件内容会**追加**在内置规则之后，并标注为“Additional user requirements (highest priority)”，因此**内置的安全边界与工具规则依然生效**，你只做叠加。
- 文件为空时自动回退到内置规则。
- 环境变量指向的文件不存在会直接报错（避免静默失效）。
- 修改后需**重启 `xiete`** 生效，运行中的会话不会热更新。
- 用 `/config` 查看当前生效来源，例如 `System prompt  workspace file (XIETE_PROMPT.md)`。

> 若确实要**整体替换**内置提示词，改 `xiete/agent.py` 里的 `AGENT_INSTRUCTIONS` 字符串本身即可。

---

## 故障排查

| 现象 | 处理方式 |
| --- | --- |
| 启动后出现黄色「缺少 API Key」面板 | 按面板提示创建 `.env` 或导出环境变量；修复后可直接再输入任务，无需重启 |
| `认证失败 / 401` | `XIETE_API_KEY` 无效或已过期；确认 `XIETE_BASE_URL=https://api.deepseek.com` |
| `Model does not exist` / 模型不存在 | 当前模型名应为 `deepseek-flash` 或 `deepseek-v4-pro`；旧的 `deepseek-chat` 已不可用 |
| `tool_choice: required ... not supported in thinking mode` | 说明当前未走 XIETE 的 DeepSeek 适配；确认 `XIETE_MODEL` 以 `deepseek` 开头，或设 `XIETE_THINKING=disabled` |
| `reasoning_content is required ...` | 同上，检查是否混进了非 DeepSeek 的 base_url，或升级 XIETE |
| 连接超时 / 响应很慢 | 思考模式本身较慢，可调大 `XIETE_TIMEOUT`（默认 300）；或设 `XIETE_THINKING=disabled` |
| 余额不足 `Insufficient Balance` | 到 DeepSeek 开放平台充值 |
| 中文在 Windows 终端乱码 | 使用 Windows Terminal，或执行 `chcp 65001` 切换到 UTF-8 |
| 无彩色的环境（CI / 重定向） | 设置 `NO_COLOR=1` 可关闭颜色输出 |

---

## 开发与测试

```bash
git clone https://github.com/IAMCODEMAN/xiete.git && cd xiete-cli
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 语法检查 / 导入自检
python -c "import xiete, xiete.cli, xiete.ui; print(xiete.__version__)"
python -m compileall xiete
```

离线测试（不需要真实 API Key，全部走本地 mock 服务器）：

```bash
python tests/smoke_test.py           # 工具/配置/UI/Agent 构建
python tests/deepseek_test.py        # DeepSeek 思考模式三条规则的单元验证
python tests/deepseek_e2e_test.py    # 模拟 DeepSeek 严格规则的完整 Agent 运行
python tests/e2e_mock_server.py      # REPL/斜杠命令/Ctrl+C 端到端
```

依赖基线：

- Python ≥ 3.10
- `smolagents >= 1.26`（该版本起 `OpenAIServerModel` 已更名为 `OpenAIModel`；代码中保留了双向导入回退，兼容旧版本）

## License

MIT
