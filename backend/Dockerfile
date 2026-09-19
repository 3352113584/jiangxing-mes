# 匠星智造 MES 后端生产镜像
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

# 时区数据（确保容器内时间按 Asia/Shanghai 解释，与应用日志一致）
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 入口：先执行迁移（幂等），再启动 uvicorn
RUN chmod +x docker-entrypoint.sh

# 以非 root 用户运行（降低容器逃逸风险）
RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
