# Use Python 3.12 slim bullseye image for better compatibility and smaller size
FROM python:3.12-slim-bullseye

# Set the working directory to /app for better organization
WORKDIR /app

# Copy requirements.txt to the container first
# This allows Docker to cache the installed dependencies for faster builds
# when your code changes but your dependencies do not
COPY requirements.txt .

# Install the Python dependencies
# The --no-cache-dir option is used to keep the image size small
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code into the container, excluding config.ini
# Doing this after installing the dependencies allows Docker to cache the
# installed dependencies separately from your code
COPY . .
RUN rm config.ini

# Set the command to run the bot
# The ENTRYPOINT instruction allows the container to be run as an executable
# The CMD instruction provides default arguments that can be overridden
ENTRYPOINT ["python", "bot.py"]
CMD ["--conf", "config.ini"]