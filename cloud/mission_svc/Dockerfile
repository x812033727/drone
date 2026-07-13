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

CMD ["uvicorn", "mission_svc.main:app", "--host", "0.0.0.0", "--port", "8092"]
