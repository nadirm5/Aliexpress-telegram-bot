FROM python:3.11.2-slim


RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

RUN mkdir -p /app/cache

RUN chown -R appuser:appgroup /app

WORKDIR /app

COPY --chown=appuser:appgroup requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appgroup . .

USER appuser


CMD ["python", "app.py"]