# build context 必須是 repo 根(見 cloud/deploy/compose/docker-compose.yml):
# 需要 COPY tools/ulog_report.py(報告工具與 log-svc 同映像,背景子程序執行)。
FROM python:3.14-slim

WORKDIR /app

COPY cloud/log_svc/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/ulog_report.py tools/ulog_report.py
COPY cloud/log_svc/log_svc ./log_svc

CMD ["uvicorn", "log_svc.main:app", "--host", "0.0.0.0", "--port", "8090"]
