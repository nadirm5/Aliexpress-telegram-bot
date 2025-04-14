
FROM python:3.11.2-slim
RUN mkdir -p /app/cache
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY --chown=appuser:appgroup . .

RUN chown appuser:appgroup /app/cache
USER appuser

CMD ["python", "app.py"]