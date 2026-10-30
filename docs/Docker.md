# Run in container

The image requires a config file: its entrypoint runs `python -m src.main --conf config.ini`.
Environment variables override values inside that file, but they do not replace it. The image
cannot be configured through environment variables alone.

## Docker Compose (recommended)

Create the config file before starting the service. Compose mounts `./config.ini`
unconditionally, so the mount fails or misbehaves when the path does not exist.

```bash
cp .env.example .env
# Edit .env and set DISCORD_TOKEN plus the provider keys you use.
cp config.ini.example config.ini
# If every value comes from .env, an empty config file is enough:
# touch config.ini
docker compose up -d
```

If `config.ini` is missing, Docker creates a directory at that path. The bot then exits
because it cannot read the config file.

The shipped `docker-compose.yml`:

- injects `.env` into the container with `env_file: [.env]`, so secrets stay out of the
  compose file;
- mounts `./config.ini` read-only at `/app/config.ini`;
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
cp config.ini.example config.ini
docker run --restart always \
  --env-file .env \
  -p 127.0.0.1:8080:8080 \
  -e HEALTH_HOST=0.0.0.0 \
  -v "$(pwd)/config.ini:/app/config.ini:ro" \
  discordianai:latest
```

The image defines the same `/health` `HEALTHCHECK` as the compose file, so `docker ps`
reports the container as unhealthy when the bot or its providers stop responding.

The `-v` mount is required because the entrypoint passes `config.ini` to `--conf`. Create
the file first with `cp config.ini.example config.ini`, or with `touch config.ini` when
every value comes from `.env`. If the file is missing, Docker creates a directory at
`$(pwd)/config.ini` and the bot exits because it cannot read the config file. Replace
`$(pwd)/config.ini` with the actual path if it lives elsewhere.
