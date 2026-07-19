FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY driver.json .
COPY intg-doorbird ./intg-doorbird

ENV UC_CONFIG_HOME=/config
ENV UC_INTEGRATION_INTERFACE=0.0.0.0
ENV UC_INTEGRATION_HTTP_PORT=9099

VOLUME ["/config"]
EXPOSE 9099

CMD ["python3", "intg-doorbird/driver.py"]
