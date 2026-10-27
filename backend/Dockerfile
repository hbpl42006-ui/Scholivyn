FROM python:3.12-slim
WORKDIR /app
RUN groupadd --system --gid 10001 scholivyn && useradd --system --uid 10001 --gid 10001 --home-dir /home/scholivyn --create-home --shell /usr/sbin/nologin scholivyn
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
