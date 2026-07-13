# build context 為 repo 根(見 cloud/deploy/compose/docker-compose.yml)。
FROM python:3.12-slim

WORKDIR /app

COPY cloud/fleet_svc/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 機-雲契約生成碼(遙測消費者解析 telemetry proto 需要)
COPY interfaces/proto/gen/python /opt/drone-proto
RUN pip install --no-cache-dir /opt/drone-proto

COPY cloud/fleet_svc/fleet_svc ./fleet_svc
COPY cloud/fleet_svc/migrations ./migrations

# 以非 root 執行(對齊 Helm securityContext runAsUser: 1000;defense-in-depth,
# compose 部署亦生效)。chown /app 使 __pycache__ 可寫。
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --system --no-log-init app \
    && chown -R app:app /app
USER app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# migrate.py 以 parents[1]/migrations 尋找 → /app/migrations
CMD ["uvicorn", "fleet_svc.main:app", "--host", "0.0.0.0", "--port", "8091"]
