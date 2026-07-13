# build context 為 repo 根(見 cloud/deploy/compose/docker-compose.yml)。
FROM python:3.12-slim

WORKDIR /app

COPY cloud/fleet_svc/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cloud/fleet_svc/fleet_svc ./fleet_svc
COPY cloud/fleet_svc/migrations ./migrations

# migrate.py 以 parents[1]/migrations 尋找 → /app/migrations
CMD ["uvicorn", "fleet_svc.main:app", "--host", "0.0.0.0", "--port", "8091"]
