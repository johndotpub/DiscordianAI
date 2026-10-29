# Run in container

The bot can be configured entirely through environment variables or through a mounted `config.ini`.
Environment variables take precedence over values in the config file.

## Docker Compose (recommended)

```bash
cp .env.example .env
# Edit .env and set DISCORD_TOKEN plus the provider keys you use.
# Optionally copy config.ini.example to config.ini for non-secret settings.
docker compose up -d
```

The shipped `docker-compose.yml`:

- injects `.env` into the container with `env_file: [.env]`, so the environment-only
  secrets pattern works without exposing them in the compose file;
- mounts `./config.ini` read-only at `/app/config.ini` when you use a config file;
- publishes the health endpoint on `127.0.0.1:8080` and sets `HEALTH_HOST=0.0.0.0`
  inside the container so the published port is reachable from the host;
- defines a `healthcheck` that calls `http://127.0.0.1:8080/health` with Python's
  standard-library `urllib.request`; it fails when the endpoint reports unhealthy or
  cannot be reached.

Check the running service:

```bash
docker compose ps
curl -fsS http://127.0.0.1:8080/health
```

`/health` returns 200 only when the bot and its configured providers are healthy.
`/health/live` and `/health/ready` are also available for liveness and readiness probes.
The health server binds `127.0.0.1:8080` by default; set `HEALTH_HOST=0.0.0.0` whenever
you publish the port.

Logs are written to stderr, so use `docker compose logs` (which captures both streams) or
your supervisor's log capture. Redirecting stdout alone produces an empty file. The
container does not write to `./logs` or `./data`.

## docker run

```bash
docker build . -t discordianai:latest
docker run --restart always \
  --env-file .env \
  -p 127.0.0.1:8080:8080 \
  -e HEALTH_HOST=0.0.0.0 \
  -v "$(pwd)/config.ini:/app/config.ini:ro" \
  discordianai:latest
```

Omit the `-v` option if you configure everything through `.env`. The image defines the
same `/health` `HEALTHCHECK` as the compose file, so `docker ps` reports the container as
unhealthy when the bot or its providers stop responding. Replace `$(pwd)/config.ini`
with the actual path if it lives elsewhere.
