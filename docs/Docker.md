# Run in container

To run the bot in a container, you will need to check out this repository, rename the `config.ini.example` to `config.ini` and fill it in appropriately.
Then, run the following commands:

```bash
docker build . -t discordianai:latest
docker run --restart always -v $(pwd)/config.ini:/app/config.ini discordianai:latest
```
This will execute forever, unless manually stopped. The `discordian.sh` launcher is the recommended entrypoint because it handles setup and process management consistently with local runs.

The repository also includes a `docker-compose.yml` for compose-based deployments. The `-v` option above mounts the `config.ini` file from your current directory on the host machine to `/app/config.ini` inside the container. Replace `$(pwd)/config.ini` with the actual path if it lives elsewhere.
