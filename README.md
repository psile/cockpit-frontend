# DesayMem 车机记忆系统 - 前端

车机记忆系统前端，与 DesayMem 后端完全分离，互不影响。

## 快速启动

1. 编辑 `.env`，填入你的 DashScope API Key
2. 双击 `start.bat`
3. 浏览器自动打开，点火启动即可

## 文件说明

```
cockpit-frontend/
  index.html       前端页面（三栏布局：用户卡片 / 对话区 / 记忆库）
  llm_proxy.py     本地 LLM 代理（隐藏 API Key，Mem0 OSS proxy 模式）
  .env             DashScope 密钥配置
  start.bat        一键启动脚本
  requirements.txt Python 依赖清单
```

## 架构

```
前端 index.html
  ├─ ① 后端 /v1/memories/search   → 检索记忆
  ├─ ② 本地代理 /chat              → LLM 生成回复
  └─ ③ 后端 /v1/memories          → 存储新记忆
```

后端（DesayMem_mem0）只负责记忆存取，不参与对话逻辑。
LLM API Key 只存在本地 `.env`，不暴露给前端浏览器。

## 配置

编辑 `.env`：

```
LLM_API_KEY=sk-你的密钥
LLM_MODEL=qwen-plus
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
PROXY_PORT=8767
```

## 手动启动

```bash
pip install -r requirements.txt
python llm_proxy.py          # 终端 1：启动 LLM 代理
# 浏览器打开 index.html
```

## 后端地址

默认连接 `http://47.115.228.135/memory`，可在登录页修改。
