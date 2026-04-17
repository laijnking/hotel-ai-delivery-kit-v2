# 本地启动说明

## 推荐方式：PowerShell 一键启动

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
