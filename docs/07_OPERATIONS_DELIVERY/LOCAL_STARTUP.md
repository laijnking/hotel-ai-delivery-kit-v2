# 本地启动说明

## Windows 推荐方式：PowerShell 一键启动

```powershell
./scripts/start_local.ps1
```

说明：
- 自动创建 `.venv`
- 自动安装后端与前端依赖
- 自动启动全部服务
- 自动执行 smoke check

停止服务：

```powershell
./scripts/stop_local.ps1
```

## Linux 推荐方式：tmux 托管启动

首次迁移到 Linux 后建议重建依赖：

```bash
cd /root/project/HotelAgent/hotel-ai-delivery-kit-v2
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m pip install pytest
cd frontend
npm install
npx playwright install chromium
cd ..
```

启动全部服务：

```bash
tmux new-session -d -s hotel-agent './scripts/start_local.sh'
```

停止服务：

```bash
./scripts/stop_local.sh
tmux kill-session -t hotel-agent
```

验证：

```bash
.venv/bin/python scripts/smoke_check.py
```

默认监听：

- 前端：`0.0.0.0:3000`
- 后端入口：`0.0.0.0:8100`
- 内部后端服务：`8101-8107`

## Linux Docker Compose 启动

服务器部署或需要和其他应用统一托管时，推荐 Docker Compose：

```bash
cd /root/project/HotelAgent/hotel-ai-delivery-kit-v2
cp backend/.env.example backend/.env
docker compose up -d --build
```

验证：

```bash
docker compose ps
curl -I http://127.0.0.1:3000
curl -X POST http://127.0.0.1:3000/api/v1/ai/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"请分析一下万达所有酒店3月份经营情况，按区域维度输出","role":"GROUP_ADMIN"}'
```

停止：

```bash
docker compose down
```

Docker 模式下，浏览器仍只访问 `3000`；前端容器会把 `/api` 代理到 Compose 网络里的 `ai-query-service:8100`。

## 外网访问

如果部署机器有公网 IP，且安全组/防火墙已放行端口，可以直接访问：

```text
http://<公网IP>:3000
```

本项目前端默认使用同源 `/api` 地址，Vite 会把 `/api` 代理到本机 `8100` 后端入口。因此外网演示只需要访问前端端口：

```text
http://<公网IP>:3000
```

需要确认：

- 服务器安全组放行 TCP `3000`
- 若需要外部系统直连 API，再放行 TCP `8100`
- 本机防火墙未阻断对应端口
- 不建议直接向公网暴露 `8101-8107` 内部微服务端口

## 后端依赖
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
```

## 启动顺序
1. auth-service          8105
2. metric-service        8102
3. semantic-service      8101
4. sql-guardrail-service 8103
5. db-executor-service   8106
6. explanation-service   8104
7. audit-service         8107
8. ai-query-service      8100

## 前端
```bash
cd frontend
npm install
npm run dev
```

## 前端环境变量

如需修改前端请求地址，可复制：

```bash
cp frontend/.env.example frontend/.env
```

并修改：

```text
VITE_API_URL=http://127.0.0.1:8100/api/v1/ai/query
```
