# build context 為 repo 根(見 cloud/deploy/compose/docker-compose.yml)。
FROM python:3.12-slim

WORKDIR /app

COPY cloud/mission_svc/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 機-雲契約生成碼(MissionPlan/MissionCommand/MissionProgress 組裝解析需要)
COPY interfaces/proto/gen/python /opt/drone-proto
RUN pip install --no-cache-dir /opt/drone-proto

COPY cloud/mission_svc/mission_svc ./mission_svc
COPY cloud/mission_svc/migrations ./migrations

# 以非 root 執行(對齊 Helm securityContext runAsUser: 1000;defense-in-depth,
# compose 部署亦生效)。chown /app 使 __pycache__ 可寫。
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --system --no-log-init app \
    && chown -R app:app /app
USER app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

CMD ["uvicorn", "mission_svc.main:app", "--host", "0.0.0.0", "--port", "8092"]
