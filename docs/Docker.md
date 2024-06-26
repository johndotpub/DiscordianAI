# Run in container

To run the bot in a container, you will need to check out this repository, rename the `config.ini.example` to `config.ini` and fill it in appropriately.
Then, run the following commands:

```bash
docker build . -t discordianai:latest
docker run --restart always -v $(pwd)/config.ini:/app/config.ini discordianai:latest
```
This will execute forever, unless manually stopped. The `-v` option is used to mount the `config.ini` file from your current directory on the host machine to the `/app/config.ini` file in the Docker container. Replace `$(pwd)/config.ini` with the actual path to your `config.ini` file if it’s not in your current directory. Remember to include the trailing slash in the path. This ensures that Docker treats this as a file and not as a directory.