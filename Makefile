.PHONY: help up down logs rebuild

help:
	@echo "make up      - 启动 docker compose"
	@echo "make down    - 停止 docker compose"
	@echo "make logs    - 查看日志"
	@echo "make rebuild - 重建并启动"
	@echo "PowerShell 本地启动: ./scripts/start_local.ps1"

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

rebuild:
	docker compose down
	docker compose up --build --force-recreate
