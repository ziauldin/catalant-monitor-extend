# Playwright already bundles Chromium + all required system deps
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy your code
COPY . /app

# (Optional but recommended) Ensure Playwright browsers are present
# The base image usually has them, but this makes it bulletproof.
RUN python -m playwright install --with-deps chromium

# Run your worker
CMD ["python", "script_clean_single.py"]
