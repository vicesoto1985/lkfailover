FROM nginx:alpine

ENV PORT=8080
ENV FAILOVER_CONFIG_JSON='{"listen_port":8080,"server_name":"_","routing_mode":"proxy","check_interval_seconds":10,"connect_timeout_seconds":2,"read_timeout_seconds":20,"fail_threshold":1,"recover_threshold":1,"fallback_title":"Servicio temporalmente no disponible","fallback_message":"Estamos mostrando una pagina de respaldo mientras vuelve el servicio principal.","targets":[{"name":"placeholder","priority":1,"proxy_url":"http://127.0.0.1:65535","health_url":"http://127.0.0.1:65535/healthz"}],"fallback":{"type":"static","name":"html-local"}}'

RUN apk add --no-cache python3

COPY app /app
COPY public /usr/share/nginx/html
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD wget -qO- http://127.0.0.1:${PORT}/healthz || exit 1

ENTRYPOINT ["/entrypoint.sh"]
