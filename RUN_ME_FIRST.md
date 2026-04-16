# RUN ME FIRST

## 方案0：Windows 本地一键启动

如果本机没有 Docker，直接运行：

```powershell
./scripts/start_local.ps1
```

通过后：
- 前端：http://127.0.0.1:3000
- 后端：http://127.0.0.1:8100

若同一局域网内的手机或电脑访问这台机器，也可以直接打开：
- 前端：`http://<你的内网IP>:3000`
- 后端：`http://<你的内网IP>:8100`

如需启用千问大模型，请先配置本机环境变量：
- `QWEN_API_BASE_URL`
- `QWEN_API_KEY`
- `QWEN_FAST_MODEL`
- `QWEN_DEEP_MODEL`

推荐：
- `QWEN_FAST_MODEL=qwen3.5-flash`
- `QWEN_DEEP_MODEL=qwen3.6-plus`

若未单独配置，也会回退使用 `QWEN_MODEL`。

停止：

```powershell
./scripts/stop_local.ps1
```

## 方案A：本地 Python + Node 启动
请参考 `docs/LOCAL_STARTUP.md`

## 方案B：Docker Compose 启动
```bash
cp backend/.env.example backend/.env
docker compose up --build
```

然后：
- 前端：http://127.0.0.1:3000
- 后端：http://127.0.0.1:8100

## 初始化 Demo 数据
先执行：
```bash
mysql -u hotel_ai_user -p hotel_ai < demo/demo_init.sql
```

或者容器启动后在 MySQL 容器中导入。
