# 部署说明

## 当前部署模式
- 单机 Docker Compose 或 `tmux + scripts/start_local.sh`。
- Docker Compose 适合服务器部署、迁移复用和后续多应用共存。
- `tmux + scripts/start_local.sh` 适合快速本机调试、无 Docker 环境或临时排障。

## Docker Compose 部署

首次部署：

```bash
cd /root/project/HotelAgent/hotel-ai-delivery-kit-v2
cp backend/.env.example backend/.env  # 如需接入大模型或外部服务，可在该文件补充密钥
docker compose up -d --build
```

查看状态与日志：

```bash
docker compose ps
docker compose logs -f --tail=100 frontend ai-query-service
```

停止 Docker 部署：

```bash
docker compose down
```

Docker 部署端口：

- 前端：宿主机 `0.0.0.0:3000`
- 后端入口：宿主机 `127.0.0.1:8100`，供本机 smoke check 或前端容器代理使用
- 内部微服务：仅在 Compose 网络中互通，不对公网暴露

容器内服务发现：

- `ai-query-service` 通过 `AUTH_SERVICE_URL=http://auth-service:8105` 等服务名访问内部微服务。
- 前端 Vite 代理通过 `VITE_PROXY_TARGET=http://ai-query-service:8100` 转发同源 `/api`。
- 本机非 Docker 启动仍默认代理到 `http://127.0.0.1:8100`。

## 外网访问部署

当前对公网建议只暴露前端：

- 前端：`3000`
- 后端入口：Docker 模式下绑定 `127.0.0.1:8100`；本机脚本模式下监听 `0.0.0.0:8100`
- 内部微服务：`8101-8107`

公网访问建议：

```text
http://<公网IP>:3000
```

前端默认请求同源 `/api`，由 Vite 代理到本机 `127.0.0.1:8100`。因此浏览器访问公网 `3000` 即可完成问答，不必额外向浏览器暴露 `8100`。

安全组/防火墙建议：

- 放行 TCP `3000`，供浏览器访问前端。
- 如需外部系统直连 API，放行 TCP `8100`。
- 不要直接放行 `8101-8107`，这些端口只应供本机服务间调用。

本机检查命令：

```bash
ss -ltnp | grep -E ':(3000|8100)\b'
ufw status verbose
curl http://127.0.0.1:8100/health
```

云服务器还需要在云控制台安全组中放行端口；本机 `ufw inactive` 不代表公网安全组已经打开。

## 后续生产化建议
- 拆分各服务 Dockerfile 镜像
- 接入 Nginx / API Gateway
- 接入企业 SSO
- 接入真实日志平台与监控平台
- 审计日志写入数据库而不是文件
- 通过配置中心管理 .env 与 YAML
