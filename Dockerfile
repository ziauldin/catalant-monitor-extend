FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    ca-certificates \
    unzip \
    wget \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    xdg-utils \
  && rm -rf /var/lib/apt/lists/*

# ✅ Modern keyring method (works on Debian 12/13)
RUN mkdir -p /etc/apt/keyrings \
  && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
     | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg \
  && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
     > /etc/apt/sources.list.d/google-chrome.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends google-chrome-stable \
  && rm -rf /var/lib/apt/lists/*

# Install ChromeDriver matching Chrome major version
RUN CHROME_VERSION=$(google-chrome --version | awk '{print $3}') \
  && CHROME_MAJOR=$(echo $CHROME_VERSION | cut -d. -f1) \
  && echo "Chrome version: $CHROME_VERSION (major: $CHROME_MAJOR)" \
  && DRIVER_VERSION=$(curl -sS "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${CHROME_MAJOR}") \
  && echo "ChromeDriver version: $DRIVER_VERSION" \
  && curl -sS -o /tmp/chromedriver.zip "https://chromedriver.storage.googleapis.com/${DRIVER_VERSION}/chromedriver_linux64.zip" \
  && unzip /tmp/chromedriver.zip -d /usr/bin/ \
  && chmod +x /usr/bin/chromedriver \
  && rm /tmp/chromedriver.zip \
  && chromedriver --version

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app

CMD ["python", "script_clean_single.py"]
