# DesayMem 车机记忆系统 - 前端

车机记忆系统前端，与 DesayMem 后端完全分离，互不影响。

## 整体调用架构

```
浏览器前端 (http://127.0.0.1:8080)
├── 记忆读写 → http://10.133.72.161:20142
└── 对话生成 → http://127.0.0.1:8767
    └── Qwen vLLM → http://10.133.72.161:20140/v1
```

- **浏览器**直接访问服务器记忆后端 (20142) 进行记忆读写
- **浏览器**对话消息发送到本地 LLM 代理 (8767)
- **本地代理**携带 API Key 转发到服务器 vLLM (20140)，API Key 不暴露给浏览器

## 公司服务器端口说明

| 端口 | 服务 | 说明 |
|------|------|------|
| 20140 | Qwen vLLM 模型服务 | OpenAI 兼容接口 `/v1/chat/completions`，由本地 llm_proxy.py 调用 |
| 20141 | BGE-M3 Embedding 服务 | 由记忆后端内部使用，前端不直接访问 |
| 20142 | DesayMem 记忆后端 | 记忆读写 API，由浏览器直接访问 |
| 20143 | PostgreSQL | 仅供服务器内部使用，外部不可访问 |
| 8767  | Windows 本地 LLM 代理 | llm_proxy.py，隐藏 API Key |
| 8080  | Windows 本地前端静态页面 | Python http.server 托管 index.html |

> **20140 vs 20142**：20140 是 Qwen 大模型服务（生成对话回复），20142 是记忆后端（存储/检索记忆）。前端不直接访问 20140，而是通过本地 8767 代理间接调用。

## 快速启动

1. 编辑 `.env`，填入与服务器 vLLM 一致的 API Key
2. 双击 `start.bat`
3. 浏览器自动打开 http://127.0.0.1:8080，点火启动即可

## 文件说明

```
cockpit-frontend/
  index.html       前端页面（三栏布局：用户卡片 / 对话区 / 记忆库）
  llm_proxy.py     本地 LLM 代理（隐藏 API Key，Mem0 OSS proxy 模式）
  .env             API Key 与模型配置（不提交 Git）
  .env.example     配置模板
  start.bat        一键启动脚本
  requirements.txt Python 依赖清单
```

## 本地安装依赖

```bash
pip install -r requirements.txt
```

依赖：fastapi、uvicorn、httpx、pydantic

## `.env` 配置方法

从模板复制并编辑：

```bash
copy .env.example .env
```

配置内容：

```
LLM_API_KEY=请填写与服务器vLLM一致的API_Key
LLM_MODEL=memory-llm
LLM_BASE_URL=http://10.133.72.161:20140/v1
PROXY_PORT=8767
LLM_ENABLE_THINKING=false
LLM_MAX_TOKENS=128
LLM_TEMPERATURE=0.3
LLM_TOP_P=0.8
```

- `LLM_API_KEY`：必须与服务器 vLLM 配置的 API Key 一致
- `LLM_MODEL`：服务器上的模型名称，默认 `memory-llm`
- `LLM_BASE_URL`：服务器 vLLM 地址
- `PROXY_PORT`：本地代理监听端口
- `LLM_ENABLE_THINKING`：关闭 Qwen3 思考模式，避免输出分析过程
- `LLM_MAX_TOKENS`：车机对话回答最大 token 数（128）
- `LLM_TEMPERATURE`：回答温度（0.3，更稳定）
- `LLM_TOP_P`：采样参数（0.8）

> `.env` 已被 `.gitignore` 忽略，不会提交到 Git。

### 车机回答 vs 记忆后端 token 限制

| 场景 | 服务 | token 限制 | 说明 |
|------|------|-----------|------|
| 前端车机回答 | 本地 llm_proxy.py → vLLM (20140) | 128 | 车机对话回复，简短口语化 |
| DesayMem 记忆提取 | 服务器记忆后端 (20142) → vLLM (20140) | 2000 | 记忆提取、画像、总结，需要更大上下文 |

前端车机回答的 `LLM_MAX_TOKENS=128` 不影响记忆后端的提取、画像和总结能力。记忆后端有自己的 `LLM_MAX_TOKENS=2000` 配置。

## `start.bat` 启动方法

双击 `start.bat`，脚本会：

1. 检查 Python 是否安装
2. 检查 `.env`，不存在则从 `.env.example` 复制
3. 检查 API Key 是否仍为占位符
4. 安装缺失的 Python 依赖
5. 启动本地 LLM 代理 (端口 8767)
6. 启动本地静态文件服务器 (端口 8080)
7. 打开浏览器 http://127.0.0.1:8080

启动完成后显示：

```
Frontend:       http://127.0.0.1:8080
LLM Proxy:      http://127.0.0.1:8767
Memory Backend: http://10.133.72.161:20142
LLM Server:     http://10.133.72.161:20140/v1
```

如果端口 8767 或 8080 已被占用，脚本会跳过对应服务的启动。

## 手动启动

```bash
pip install -r requirements.txt
python llm_proxy.py                          # 终端 1：启动 LLM 代理
python -m http.server 8080 --bind 127.0.0.1  # 终端 2：启动静态服务器
# 浏览器打开 http://127.0.0.1:8080
```

## PowerShell 连通性测试

### 健康检查 — 记忆后端

```powershell
Invoke-RestMethod http://10.133.72.161:20142/health
```

### 健康检查 — 本地 LLM 代理

```powershell
Invoke-RestMethod http://127.0.0.1:8767/health
```

### 连通性测试 — vLLM 模型服务

```powershell
Invoke-WebRequest http://10.133.72.161:20140/v1/models -Headers @{Authorization="Bearer YOUR_API_KEY"}
```

### 记忆写入验证

```powershell
$body = @{
    tenant_id = "oem_chery"
    user_id   = "user_test"
    vehicle_id = "vehicle_001"
    occupant_id = "driver"
    session_id = "session_test"
    scene = "driving"
    messages = @(
        @{ role = "user"; content = "我开车时喜欢把空调调到22度" }
    )
    infer = $true
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -Uri http://10.133.72.161:20142/v1/memories -ContentType "application/json" -Body $body
```

### 记忆检索验证

```powershell
$body = @{
    tenant_id = "oem_chery"
    user_id   = "user_test"
    query     = "空调温度"
    top_k     = 5
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://10.133.72.161:20142/v1/memories/search -ContentType "application/json" -Body $body
```

## CORS 排查

前端通过 `http://127.0.0.1:8080` 启动，避免 `file://` 页面的 `Origin null` 问题。

服务器记忆后端 (20142) 需要允许以下来源的跨域请求：

- `http://127.0.0.1:8080`
- `http://localhost:8080`

如果浏览器控制台出现 CORS 错误，检查服务器端 20142 的 CORS 配置是否包含上述来源。

本地 LLM 代理 (8767) 已配置 `allow_origins=["*"]`，不存在 CORS 问题。

## API Key 不一致的排查

如果 LLM 代理返回 HTTP 401/403 错误，说明 `.env` 中的 `LLM_API_KEY` 与服务器 vLLM 配置的 Key 不一致。

排查步骤：

1. 检查 `.env` 中 `LLM_API_KEY` 是否正确
2. 访问 `http://127.0.0.1:8767/health` 查看代理状态和 Key 掩码
3. 用 curl/PowerShell 直接测试服务器 vLLM：

```powershell
Invoke-WebRequest http://10.133.72.161:20140/v1/models -Headers @{Authorization="Bearer YOUR_API_KEY"}
```

## 思考过程泄露排错

如果界面输出模型思考过程（如"首先检查历史记忆…接下来按照规则…"）：

1. 检查 `.env` 中 `LLM_ENABLE_THINKING=false`
2. 确认重启了本地 8767 代理（见下方重启命令）
3. 确认旧的代理进程已经停止
4. 检查 vLLM 是否接受 `chat_template_kwargs.enable_thinking`（如果返回 HTTP 400，说明服务器不支持该参数）

## Windows 重启代理

```cmd
netstat -ano | findstr :8767
taskkill /PID <上面查到的PID> /F
start.bat
```

或者直接关闭"LLM Proxy"窗口后重新运行 `start.bat`。

## 默认服务地址

| 配置项 | 默认值 | 可修改 |
|--------|--------|--------|
| 后端记忆服务地址 | http://10.133.72.161:20142 | 登录页输入框 |
| LLM 代理地址 | http://127.0.0.1:8767 | 登录页输入框 |
