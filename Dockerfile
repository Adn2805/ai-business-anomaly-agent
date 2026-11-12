FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 agent \
    && useradd --uid 10001 --gid agent --no-create-home agent \
    && mkdir /app/data /app/reports /app/state \
    && chown -R agent:agent /app
COPY --chown=agent:agent app/ ./app/
USER 10001:10001
ENTRYPOINT ["python", "-m", "app.main"]
