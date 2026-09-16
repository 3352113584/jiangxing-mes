# 钢结构出口加工厂 MES

> 以「构件」为核心、以「二维码」为入口、以「生产履历」为主线的制造执行系统。

## 项目信息

- 项目名称：钢结构出口加工厂 MES
- 字符集：UTF-8
- 时区：Asia/Shanghai (UTC+8)

## 技术栈

| 端 | 技术 |
|------|------|
| 后端 | Python · FastAPI · SQLAlchemy · Alembic · Pydantic |
| 数据库 | PostgreSQL |
| PC 管理端 | Vue 3 · TypeScript · Vite |
| Android 端 | Kotlin |
| 接口 | REST API |
| 部署 | Docker · Docker Compose · Nginx |
| 版本管理 | Git |

## 目录结构

```
匠星智造MES/
├── backend/      # FastAPI 后端
├── frontend/     # Vue 3 PC 管理端
├── android/      # Kotlin Android 车间端
├── database/     # 数据库相关脚本与初始化
├── docs/         # 项目文档
├── deploy/       # Docker / Nginx / 部署配置
├── scripts/      # 通用脚本
├── tests/        # 集成 / 端到端测试
├── .gitignore
└── README.md
```

## 开发阶段

```
需求分析 → 业务设计 → 数据库设计 → 架构设计 → 接口设计
→ 后端开发 → PC 开发 → Android 开发 → 联调 → 测试 → 部署 → 验收
```

## 当前阶段

第 1 阶段：开发环境初始化（进行中）

## 开发环境

- 操作系统：Windows 11
- IDE：Trae CN
- Python：3.12
- Node.js：v24
- pnpm：12.x
- Docker Desktop：已安装
- PostgreSQL：通过 Docker Compose 运行（开发环境）

## 本地开发启动（PostgreSQL）

```powershell
# 1. 复制环境变量示例
Copy-Item deploy/.env.example deploy/.env

# 2. 修改 deploy/.env 中的密码为本地开发密码

# 3. 启动 PostgreSQL
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d

# 4. 查看运行状态
docker compose -f deploy/docker-compose.yml ps

# 5. 停止
docker compose -f deploy/docker-compose.yml down
```

## 重要说明

- `.env` 文件不进入 Git，仅提交 `.env.example` 作为模板。
- 数据库密码、Token 等敏感信息不得硬编码到代码或提交到 Git。
- 所有数据库结构变更必须通过 Alembic migration 管理。
