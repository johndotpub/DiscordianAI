# Use Python 3.12 slim image (project targets Python 3.12+)
FROM python:3.12-slim-bookworm

# Set the working directory to /app for better organization
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy requirements separately to leverage Docker layer caching
COPY requirements.txt ./

# Install the Python dependencies
# The --no-cache-dir option is used to keep the image size small
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code into the container, excluding config.ini
# Doing this after installing dependencies allows caching for faster builds
COPY . .
RUN if [ -f config.ini ]; then rm config.ini; fi

# Set the command to run the bot
# Use the unified entrypoint module
ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--conf", "config.ini"]