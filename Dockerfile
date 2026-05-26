# Build the dashboard frontend first
FROM node:20-bullseye-slim AS frontend-builder
WORKDIR /workspace
COPY ocis/dashboard/package*.json ocis/dashboard/
RUN cd ocis/dashboard && npm install
COPY ocis/dashboard/src ocis/dashboard/src
COPY ocis/dashboard/index.html ocis/dashboard/index.html
RUN cd ocis/dashboard && npm run build

# Final Python runtime image
FROM python:3.14-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
COPY --from=frontend-builder /workspace/ocis/dashboard/dist ./ocis/dashboard/dist

EXPOSE 8001
ENV OCIS_HOST=0.0.0.0
ENV OCIS_PORT=8001

CMD ["uvicorn", "ocis.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
