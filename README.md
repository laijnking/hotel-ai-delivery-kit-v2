# 酒店经营 AI 分析系统交付包（Delivery Kit v2）

这是一个更接近一键运行的交付包，适合：
- 本地演示
- 团队联调
- 作为后续生产化改造基础

## 推荐启动方式

当前工作区已补齐 Windows 本地无人值守启动脚本，若本机没有 Docker，推荐直接使用：

```powershell
./scripts/start_local.ps1
```

启动后可通过本机或局域网访问：
- 本机前端：`http://127.0.0.1:3000`
- 局域网前端：`http://<你的内网IP>:3000`
- 本机后端：`http://127.0.0.1:8100`
- 局域网后端：`http://<你的内网IP>:8100`

它会自动：
- 创建 `.venv`
- 安装后端依赖
- 安装前端依赖
- 启动 8 个后端服务和前端
- 执行 smoke check

停止本地进程可使用：

```powershell
./scripts/stop_local.ps1
```

## 本版新增
- 统一 Dockerfile
- docker-compose 运行编排
- Makefile 常用命令
- 一键初始化 SQL 脚本说明
- 运维与环境变量说明
- Windows 本地启动脚本
- 本地 smoke check

## 核心能力
- 经营问答
- 经营报告生成
- 千问语义增强解析
- 千问管理层摘要生成
- 权限范围返回
- SQL 护栏校验
- Demo 数据查询
- 管理层摘要生成
- 审计日志记录
- explain / report 结构化返回

## 大模型配置
当前版本支持通过 OpenAI 兼容接口接入阿里云千问，并支持快慢双模型分层：
- `QWEN_API_BASE_URL`
- `QWEN_API_KEY`
- `QWEN_FAST_MODEL`
- `QWEN_DEEP_MODEL`
- `QWEN_MODEL`
- `QWEN_TIMEOUT`

推荐配置：
- `QWEN_FAST_MODEL=qwen3.5-flash`
- `QWEN_DEEP_MODEL=qwen3.6-plus`

当前策略：
- 快模型负责首轮语义理解、自然语言容错和必要的澄清追问
- 深模型负责结合真实数据库做管理层摘要、横向分析和行动建议
