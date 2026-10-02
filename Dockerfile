# Pin the version; record the resolved image digest in each client's release evidence.
FROM python:3.12.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements-production.txt ./
RUN python -m pip install --no-cache-dir --requirement requirements-production.txt \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data && chown 10001:10001 /data
COPY admin_agent/ ./admin_agent/
COPY web/ ./web/
COPY data/skills.json ./data/skills.json
COPY skills/ ./skills/
USER 10001:10001
EXPOSE 8765
CMD ["python", "-m", "admin_agent.production"]
