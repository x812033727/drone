# build context 必須是 repo 根(見 cloud/deploy/compose/docker-compose.yml):
# 需要 COPY interfaces/proto/gen/python 的契約生成碼。
FROM python:3.14-slim

WORKDIR /app

COPY cloud/ingest/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY interfaces/proto/gen/python /opt/drone-proto
RUN pip install --no-cache-dir /opt/drone-proto

COPY cloud/ingest/ingest ./ingest

# 以非 root 執行(對齊 Helm securityContext runAsUser: 1000;defense-in-depth,
# compose 部署亦生效)。chown /app 使 __pycache__ 可寫。
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --system --no-log-init app \
    && chown -R app:app /app
USER app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

CMD ["python", "-m", "ingest.main"]
