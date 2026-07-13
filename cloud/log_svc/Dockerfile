# build context 必須是 repo 根(見 cloud/deploy/compose/docker-compose.yml):
# 需要 COPY tools/ulog_report.py(報告工具與 log-svc 同映像,背景子程序執行)。
FROM python:3.12-slim

WORKDIR /app

COPY cloud/log_svc/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/ulog_report.py tools/ulog_report.py
COPY cloud/log_svc/log_svc ./log_svc

# 以非 root 執行(對齊 Helm securityContext runAsUser: 1000;defense-in-depth,
# compose 部署亦生效)。chown /app 使 __pycache__ 與 ULog 暫存路徑可寫。
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --system --no-log-init app \
    && chown -R app:app /app
USER app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

CMD ["uvicorn", "log_svc.main:app", "--host", "0.0.0.0", "--port", "8090"]
