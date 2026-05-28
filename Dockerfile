FROM nginx:alpine

RUN apk add --no-cache python3

COPY app /app
COPY public /usr/share/nginx/html
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD wget -qO- http://127.0.0.1/healthz || exit 1

ENTRYPOINT ["/entrypoint.sh"]
