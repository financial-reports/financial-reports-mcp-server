[English](README.md) | 简体中文

# FinancialFilings MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![MCP Spec](https://img.shields.io/badge/MCP-2025--11--25-green)](https://modelcontextprotocol.io)
[![Status](https://img.shields.io/badge/status-production-green)](https://mcp.financialfilings.com/health)

> **[FinancialFilings](https://financialfilings.com) API 的官方 Model Context Protocol (MCP) 服务器。**
> 在 Claude 以及任何支持 MCP 的客户端里，直接查询全球上市公司的公告、财务数据和公司信息。**默认提供 17 个精选工具**（设置 `MCP_FULL_SURFACE=1` 可开启完整的 55 个工具）。**任何 FinancialFilings 账号均可免费使用。**

本文是英文 [README.md](README.md) 的中文版。两者如有出入，以英文版为准。

---

## 快速开始

如果你是分析师、研究员，或者只是想让 Claude 帮你查上市公司公告：

1. 在 [financialfilings.com](https://financialfilings.com/) **注册免费账号**。任何 FinancialFilings 用户都可以免费使用 MCP 连接器，不需要付费套餐。
2. 在你的 MCP 客户端里**添加连接器**，具体步骤见下文[连接你的客户端](#连接你的客户端)。最常用的两种：
   - **Claude.ai / Claude Desktop**：Settings → Connectors → Add custom connector，URL 填 `https://mcp.financialfilings.com/mcp`
   - **Claude Code**：`claude mcp add --transport http financialreports https://mcp.financialfilings.com/mcp`
3. 按提示用 FinancialFilings 账号**登录**，完成。

带截图的完整配置说明：[financialfilings.com/integrations/claude/](https://financialfilings.com/integrations/claude/)。中文介绍页：[financialfilings.com/zh-hans/mcp/](https://financialfilings.com/zh-hans/mcp/)。

---

## 连接你的客户端

这是一个**远程** MCP 服务器，使用 Streamable HTTP 传输，通过 OAuth（PKCE + 动态客户端注册）认证。**不需要复制 API 密钥，也不需要保存任何密钥**：连接时会在浏览器中打开 FinancialFilings 账号登录页。

**端点：** `https://mcp.financialfilings.com/mcp`

在下面找到你的客户端。如果没有列出，请使用最后的[**通用配置**](#通用配置任意-mcp-客户端)：各客户端的端点和 OAuth 流程完全相同，只是配置文件不同。

### Claude.ai / Claude Desktop

Settings → Connectors → **Add custom connector**，URL 填 `https://mcp.financialfilings.com/mcp`，按提示登录。

### Claude Code

```bash
claude mcp add --transport http financialreports https://mcp.financialfilings.com/mcp
```

在会话中运行 `/mcp` 完成浏览器登录。

**也可以安装插件**。插件会添加同一个服务器，另外附带 `financial-filings-research` 技能（工具速查表和研究工作流）：

```
/plugin install financialfilings --marketplace financial-reports/financial-reports-mcp-server
```

如果 Claude Code 版本低于 2.1.275，请先添加 marketplace：`/plugin marketplace add financial-reports/financial-reports-mcp-server`，再运行 `/plugin install financialfilings@financialfilings`。无论哪种方式，都需要运行一次 `/mcp` 登录。

### Codex (OpenAI)

Codex 使用 TOML 配置。添加到 `~/.codex/config.toml`（或项目内的 `.codex/config.toml`）：

```toml
[mcp_servers.financialreports]
url = "https://mcp.financialfilings.com/mcp"
```

然后完成认证。对于支持 OAuth 的服务器，Codex 会打开浏览器登录流程：

```bash
codex mcp login financialreports
```

### Cursor

可以在 [Cursor Directory](https://cursor.directory/plugins/financialfilings-mcp) 一键安装，也可以手动添加到 `~/.cursor/mcp.json`（全局）或 `.cursor/mcp.json`（单个项目）：

```json
{
  "mcpServers": {
    "financialfilings": { "url": "https://mcp.financialfilings.com/mcp" }
  }
}
```

首次使用时会在浏览器中完成 OAuth 登录。

### Kilo Code

项目内的 `.kilocode/mcp.json`（或全局 MCP 配置文件）：

```json
{
  "mcpServers": {
    "financialreports": {
      "type": "remote",
      "url": "https://mcp.financialfilings.com/mcp"
    }
  }
}
```

### opencode

`opencode.json`：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "financialreports": {
      "type": "remote",
      "url": "https://mcp.financialfilings.com/mcp",
      "enabled": true
    }
  }
}
```

### Gemini CLI

`~/.gemini/settings.json`：

```json
{
  "mcpServers": {
    "financialreports": { "httpUrl": "https://mcp.financialfilings.com/mcp" }
  }
}
```

### Hermes

在 Hermes 配置（YAML）中的 `mcp_servers` 下添加：

```yaml
mcp_servers:
  financialreports:
    url: "https://mcp.financialfilings.com/mcp"
    auth: oauth
```

### 通用配置（任意 MCP 客户端）

大多数支持 MCP 的工具都接受 `mcpServers` 对象。通过 Streamable HTTP 指向端点即可：

```json
{
  "mcpServers": {
    "financialreports": {
      "type": "streamable-http",
      "url": "https://mcp.financialfilings.com/mcp"
    }
  }
}
```

原生支持远程 MCP OAuth 的客户端（Claude、Cursor、Windsurf、VS Code、opencode，以及通过 `codex mcp login` 的 Codex）会自动在浏览器中完成登录。**OpenClaw** 等其他支持 MCP 的工具，请使用上面的配置块填入连接器 URL，并在提示时完成 OAuth 登录。配置文件的具体位置请参考对应客户端的 MCP 文档。

### 常见问题：“Client Not Registered”

如果登录时跳转到标题为 **Client Not Registered** 的页面，提示 “The client ID `…` was not found in the server's client registry”，说明你的客户端仍在使用一个服务器端已不存在的注册信息。

**删除连接器后重新添加。** 这是唯一的解决方法，几秒钟即可完成：

| 客户端 | 操作 |
|---|---|
| **ChatGPT / OpenAI** | Settings → Connectors，删除 **FinancialFilings**（如果在更名前就已连接，名称可能显示为旧名），然后用 `https://mcp.financialfilings.com/mcp` 重新添加并登录。 |
| **Claude.ai / Claude Desktop** | Settings → Connectors，删除 **FinancialFilings**（如果在更名前就已连接，名称可能显示为旧名），然后重新添加并登录。 |
| **Claude Code / Codex / Cursor / opencode** | 删除并重新添加服务器（例如先 `claude mcp remove financialreports` 再重新添加），或重新运行客户端的登录命令（`codex mcp login financialreports`）。 |

错误页面本身没有说明的两点：

- **它不会自行恢复，重试也没有用。** 登录是在浏览器里进行的，客户端并不知道登录失败了，它会一直等待一个不会到来的回调，并反复使用同一个失效的 ID。重启也无济于事：托管型连接器（ChatGPT、Claude.ai）把注册信息保存在服务端，只有删除连接器才能清除。
- **你的账号没有问题，数据也不受影响。** 重新添加会生成新的注册信息，一切照常使用。

**如果你在 2026 年 7 月 14 日或之后遇到此问题：** 当时一次缓存故障切换导致已存储的客户端注册信息丢失。此后登录一直正常，只有在该日期**之前**添加的连接器需要按上述方法删除并重新添加。

---

## 功能概览

**默认提供 17 个可由 LLM 调用的工具**，覆盖分析师最常用的场景：

| 领域 | 工具数 | 用途 |
|---|---|---|
| 公司 | 5 | 按名称、股票代码、ISIN 搜索公司；获取完整公司资料；获取标准化财务数据；预测下一份年报的发布时间；把一组标识符批量解析为公司 ID |
| 公告 | 4 | 列出、获取公告；获取公告的 Markdown 正文（上限 15 万字符）；在单份公告内做关键词搜索 |
| ISIN | 2 | 按 ISIN 查询；列出多地上市信息 |
| 参考分类 | 2 | 公告类别和公告类型 |
| 账户 | 1 | 本计费周期内 API 和 MCP 的用量费用、消费上限和剩余免费点数（此工具本身免费，不计费） |
| 指南 | 3 | 公告类型分类、ISIC 行业分类、Markdown 获取策略：供无法读取 MCP 资源、只能调用工具的客户端使用的参考资料 |

设置 `MCP_FULL_SURFACE=1` 可恢复完整的 **55 个工具**：ISIC 门类/大类/中类/小类层级、其余参考数据（国家、语言、数据源、财务科目定义、公告历史）、个人关注列表、Webhook 订阅、公司合并审计记录、各交易所证券上市信息、智能体账户开通相关端点（注册、领取密钥、轮换密钥、结账链接、所有者确认、状态），`filings_markdown_search` 背后的原始端点 `filings_markdown_search_retrieve`，以及 `filings_document_retrieve`（返回文件而非 JSON）。

对外提供的工具集由已提交并经过审核的 [FinancialFilings OpenAPI schema](https://financialreports.eu/api/schema/) 快照（`scripts/openapi.snapshot.json`，在 CI 和 Docker 构建中通过 `FR_PIN_SCHEMA=1` 固定）生成，因此结果是确定的，重新构建也不会悄悄发生变化。

### 配套技能

本仓库附带一个 [Agent Skill](skills/financial-filings-research/)：`financial-filings-research`。它教 Claude 把这些工具组合成分析师常用的工作流：查找公司、总结公告、多公司财务对比、ISIC 行业筛选、公告监控。当用户提到公司名称、股票代码、ISIN、公告类型或财务指标时会自动启用。

---

## 架构

```
┌──────────────────┐     OAuth (PKCE + DCR)      ┌──────────────────┐
│  Claude / MCP    │  ───────────────────────►   │  AWS Cognito     │
│  client          │                              │  (user pool)     │
└────────┬─────────┘                              └────────┬─────────┘
         │  Streamable HTTP /mcp                           │
         │  + bearer token                                 │
         ▼                                                 │
┌──────────────────┐     verify subscription tier          │
│  This server     │  ───────────────────────────────────► │
│  (FastAPI +      │                                       ▼
│   FastMCP)       │     proxy bearer token         ┌──────────────────┐
│                  │  ─────────────────────────►    │  api.            │
│  17 tools        │                                │  financial-      │
│  generated from  │                                │  reports.eu      │
│  OpenAPI schema  │                                │  (first-party)   │
└──────────────────┘                                └──────────────────┘
```

**关键设计决策：**

- **工具是生成的，不是手写的。** `scripts/generate_mcp_tools.py` 读取 OpenAPI schema（在 CI 和 Docker 构建中通过 `FR_PIN_SCHEMA=1` 固定到已提交的快照），生成 `src/financial_reports_mcp.py`。默认工具集精选为 17 个；`MCP_FULL_SURFACE=1` 会生成完整工具集。注意生成器中的 `_PRUNED_EXCLUDE` 是一个**黑名单**：上游新增的端点会自动进入精选工具集，除非刷新快照的 PR 明确将其排除。
- **代理 bearer token，不保存会话。** 每次调用都会把用户的 Cognito access token 转发给上游 API。服务端不缓存任何对话数据或 API 响应。
- **进程内做订阅校验。** 一个 15 秒的 LRU 缓存保存 Cognito `sub` 到订阅等级的映射，避免每次调用工具都去请求 FR API。
- **同源静态资源代理。** `/favicon.ico`、`/icon.png`、`/icon-{32,192,512}.png` 由本服务器同源提供（从 CDN 代理并缓存），这样连接器界面和 `/consent` 页面不会遇到跨域 CSP 问题。

---

## MCP 规范兼容性

符合 [MCP 2025-11-25 规范](https://modelcontextprotocol.io/specification/2025-11-25)：

- ✅ **Streamable HTTP 传输**：`POST /mcp`，回显 `MCP-Protocol-Version`，不支持的版本返回 400
- ✅ **OAuth 2.0**：RFC 7591 动态客户端注册 + PKCE S256
- ✅ **RFC 9728 受保护资源元数据**：同时提供 `/.well-known/oauth-protected-resource` 和 `/.well-known/oauth-protected-resource/mcp`
- ✅ **工具注解**：每个工具都有 `title`，以及 `readOnlyHint` 或 `destructiveHint`
- ✅ **`outputSchema`**：6 个返回结构化内容的工具（`companies_list`、`companies_retrieve`、`companies_financials_retrieve`、`filings_list`、`filings_retrieve`、`isins_list`）
- ✅ **Origin 校验**：无法识别的 Origin 返回 403，未认证请求返回 401 并带有正确的 `WWW-Authenticate` 头
- ✅ **多尺寸连接器图标**：在 `initialize` 响应中提供 32×32、192×192、512×512 PNG

CI 会在每个 PR 上验证以上所有项目。

---

## 工具目录

以下列表摘自英文 README。英文 README 中的列表由 `scripts/generate_mcp_tools.py` 在每次构建时自动重新生成，最新版本请以英文版为准。

### Account（账户）
* `usage_retrieve`：获取 API 用量和费用

### Companies（公司）
* `companies_financials_retrieve`：获取公司财务数据
* `companies_list`：列出公司
* `companies_next_annual_report_retrieve`：预测下一份年报
* `companies_resolve_create`：按标识符批量解析公司
* `companies_retrieve`：获取公司详情

### Filing Categories（公告类别）
* `filing_categories_list`：列出公告类别

### Filing Types（公告类型）
* `filing_types_list`：列出公告类型

### Filings（公告）
* `filings_list`：列出公告
* `filings_markdown_retrieve`：获取公告 Markdown 正文
* `filings_retrieve`：获取公告详情

### ISINs
* `isins_list`：列出 ISIN
* `isins_retrieve`：获取 ISIN

---

## 示例提示词

连接后可以试试：

- *“找到 Apple 最新的 10-K，总结与上一年相比有变化的风险因素。”*
- *“获取 ASML 的完整公司信息。”*
- *“对比 Iberdrola、Engie、Enel、RWE 最近一个财年的净债务。”*
- *“列出过去 6 个月内发布了年报的欧盟航空公司。”*
- *“列出 Tesla 过去 30 天的内部人交易公告。”*
- *“我的关注列表里有公司发布 8-K 时提醒我。”*
- *“Volkswagen AG 的 LEI 是什么？”*

---

## 自行部署

自行部署需要搭建你自己的 AWS Cognito 用户池，主要适用于 fork 本项目并改造对接其他上游 API 的场景。对于 FinancialFilings API 本身，推荐使用托管在 `mcp.financialfilings.com` 的服务器。

自行部署的详细文档（Docker、Cognito 配置、环境变量、CDN/图标配置）：**[docs/SELF-HOSTING.md](docs/SELF-HOSTING.md)**（英文）。

---

## 开发

一键初始化（venv → 依赖 → 环境检查 → 生成 → 运行）：

```bash
cp .env.example .env   # fill in Cognito values first; see docs/SELF-HOSTING.md
make dev               # creates .venv, installs, validates env, regenerates, serves on :8000
# MCP endpoint: http://localhost:8000/mcp
```

或者分步执行：

```bash
# 1. Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt

# 2. Configure
cp .env.example .env  # then fill in Cognito values; see docs/SELF-HOSTING.md

# 3. Generate the MCP module from the OpenAPI schema
python scripts/generate_mcp_tools.py

# 4. Run tests
pytest

# 5. Run locally
python -m uvicorn src.financial_reports_mcp:app --host 0.0.0.0 --port 8000
# MCP endpoint: http://localhost:8000/mcp
```

CI 会在每个 PR 上运行完整的单元测试，以及一个基于 Docker Compose（含 Redis）的端到端测试。详见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)。

### 使用个人 API 密钥进行本地开发

如果你要在真实后端上反复调试生成器、工具或提示词，又**不想**每次重启都走一遍 Cognito OAuth 流程，服务器支持一个仅用于开发的环境变量 `DEV_MODE_API_KEY`。设置后，现有 `/mcp` 端点会跳过 JWT 校验（`subscription_required` 和 `_authorize_or_raise` 两条路径都会跳过），并把该密钥作为 `X-API-Key` 转发给 `API_BASE_URL`。

**这只是方便维护者的开发手段，不是生产环境的认证方式。** 如果 `MCP_BASE_URL` 包含生产域名（`mcp.financialfilings.com`），模块会拒绝加载。

1. 把你的 FinancialFilings 个人 API 密钥写入 `.env`：
   ```
   DEV_MODE_API_KEY=fr_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   MCP_BASE_URL=http://localhost:8000
   ```
2. 重新生成并启动服务器（仍需设置 Cognito 相关变量，因为即使启用了绕过，OAuth 代理模块也会被加载）：
   ```bash
   make regen
   python -m uvicorn src.financial_reports_mcp:app --host 0.0.0.0 --port 8000 --reload
   ```
3. 让 Claude Code 连接本地实例：
   ```bash
   claude mcp add --transport http financialfilings-local http://localhost:8000/mcp
   ```
   请每位开发者按上面的方式自行添加，不要写进仓库的 `.mcp.json`：该文件只列出生产服务器，因为扫描本仓库的目录站点（例如 Cursor Directory）会把其中每一项都作为公开安装项展示。

生产环境的无界面 / API 密钥认证（独立的 `/mcp/apikey` 端点，每个请求携带 `X-API-Key`）在 [#28](https://github.com/financial-reports/financial-reports-mcp-server/issues/28) 中跟踪，与这个开发模式捷径是两回事。

### 常用操作

```bash
# Regenerate tools after the OpenAPI schema changes
python scripts/generate_mcp_tools.py

# Run only fast unit tests
pytest tests/test_*.py

# Run end-to-end tests with Redis (requires Docker)
make e2e
```

---

## 评估变更

本服务器由 [`financial-reports/mcp-evals`](https://github.com/financial-reports/mcp-evals)（私有仓库）做基准测试。跨模型评分卡（任务成功率、工具选择准确率、路径一致性、token 数/轮数/延迟）保存在那里。修改工具描述、Prompts 或生成器之前，请对生产环境或本地开发 MCP 运行评测并对比评分卡。

**本仓库**中保留的是位于 `tests/eval/` 的确定性提示词注册测试：速度快，不需要 API 密钥，每个 PR 都会运行。跨仓库流程见 [`tests/eval/README.md`](tests/eval/README.md)。

---

## 安全

本服务器处理 OAuth 流程和 bearer token。**发现漏洞？请不要提交公开 issue。** 负责任披露流程见 [SECURITY.md](SECURITY.md)。

服务端保证：

- Bearer token 按请求代理转发，从不记录日志，也不持久化保存。
- 强制使用 HTTPS（HTTP 在边缘节点重定向到 HTTPS）。
- HTML 响应启用 CSP（`default-src 'none'`，只允许同源资源）。
- Origin 校验会拒绝来自无法识别来源的请求。
- 所有加密操作都依赖标准库和 AWS SDK，没有自定义加密实现。

---

## 参与贡献

欢迎贡献。开发环境、“重新生成 → 测试 → 提交 PR”的流程，以及哪些改动受欢迎（测试、文档、生成器改进、在 `scripts/generate_mcp_tools.py` 中手动调整工具描述）、哪些会被拒绝（手动编辑 `src/financial_reports_mcp.py`：它是自动生成的，每次构建都会被覆盖），请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 项目状态

- **生产环境**：已上线，地址 `https://mcp.financialfilings.com/mcp`
- **已收录于**：[Claude 连接器目录](https://claude.ai/directory/financialreports-eu)、[Cursor Directory](https://cursor.directory/plugins/financialfilings-mcp)
- **规范兼容性**：MCP 2025-11-25
- **已测试客户端**：Claude.ai、Claude Code、Claude Desktop、Cursor、Windsurf。另外为 Codex、Kilo Code、opencode、Gemini CLI 和 Hermes 提供了配置示例（见[连接你的客户端](#连接你的客户端)）。

---

## 许可证

[MIT](LICENSE)，© FINANCIALREPORTS PTE. LTD.

---

## 致谢

特别感谢 [@itisaevalex](https://github.com/itisaevalex) 开发的[最初的社区版 MCP 服务器](https://github.com/itisaevalex/financial-reports-mcp-server)，它作为概念验证，促成了这个官方版本的诞生。

基于 [FastMCP](https://github.com/jlowin/fastmcp)、[FastAPI](https://fastapi.tiangolo.com/) 和 [Model Context Protocol](https://modelcontextprotocol.io) 构建。
