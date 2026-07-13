# build context 必須是 repo 根(見 cloud/deploy/compose/docker-compose.yml):
# 需要 COPY interfaces/proto/gen/python 的契約生成碼。
FROM python:3.14-slim

WORKDIR /app

COPY cloud/ingest/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY interfaces/proto/gen/python /opt/drone-proto
RUN pip install --no-cache-dir /opt/drone-proto

COPY cloud/ingest/ingest ./ingest

CMD ["python", "-m", "ingest.main"]
