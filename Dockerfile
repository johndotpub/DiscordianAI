# Use Python 3.12 slim image (project targets Python 3.12+)
FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user for security
RUN groupadd -r appgroup && useradd -r -g appgroup appuser && chown -R appuser:appgroup /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN if [ -f config.ini ]; then rm config.ini; fi

# Ensure appuser owns the copied files after optional removal
RUN chown -R appuser:appgroup /app

USER appuser
ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--conf", "config.ini"]

# Ask the same health endpoint used by docker-compose.yml. The slim image has
# no curl, so use Python's standard library and fail on unhealthy responses or
# connection errors.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import sys, urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5); sys.exit(0 if response.status == 200 else 1)" || exit 1
