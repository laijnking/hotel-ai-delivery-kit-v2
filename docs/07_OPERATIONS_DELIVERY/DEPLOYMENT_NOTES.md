# 部署说明

## 当前部署模式
- 单机 docker-compose
- 适合本地开发、测试、演示

## 后续生产化建议
- 拆分各服务 Dockerfile 镜像
- 接入 Nginx / API Gateway
- 接入企业 SSO
- 接入真实日志平台与监控平台
- 审计日志写入数据库而不是文件
- 通过配置中心管理 .env 与 YAML
