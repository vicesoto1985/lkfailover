# LK Failover

Microservicio Docker con Nginx + watcher Python para failover activo por JSON.

## Qué hace

Cuando un usuario entra al dominio, por ejemplo `mmm.cl`, el contenedor revisa los destinos configurados por prioridad:

1. IP o servidor principal.
2. IP o servidor alternativo.
3. Si ambos fallan, deriva al fallback local o a un microservicio de respaldo.

Por defecto trabaja en modo **proxy inverso**, es decir, el navegador sigue viendo el mismo dominio. También se puede configurar modo `redirect` si más adelante quieres enviar al navegador con 302 a otra URL.

## Levantar

```bash
docker compose up -d --build
```

## Reconstrucción limpia

```bash
docker compose down --rmi all --volumes --remove-orphans && docker compose up -d --pull always --force-recreate --build
```

## Estado del failover

```bash
curl http://127.0.0.1:8080/__failover_status
```

## Configuración rápida

La configuración se entrega por variable `FAILOVER_CONFIG_JSON`.

Ejemplo:

```json
{
  "server_name": "mmm.cl",
  "listen_port": 80,
  "routing_mode": "proxy",
  "check_interval_seconds": 5,
  "connect_timeout_seconds": 2,
  "read_timeout_seconds": 20,
  "fail_threshold": 2,
  "recover_threshold": 1,
  "targets": [
    {
      "name": "principal-ip-1",
      "proxy_url": "http://1.1.1.1",
      "health_url": "http://1.1.1.1/",
      "host_header": "mmm.cl",
      "priority": 1
    },
    {
      "name": "alternativa-ip-2",
      "proxy_url": "http://2.2.2.2",
      "health_url": "http://2.2.2.2/",
      "host_header": "mmm.cl",
      "priority": 2
    }
  ],
  "fallback": {
    "type": "proxy",
    "name": "microservicio-respaldo",
    "proxy_url": "http://fallback:80",
    "host_header": "mmm.cl"
  }
}
```

## Campos importantes

- `server_name`: dominio que atiende Nginx, por ejemplo `mmm.cl`.
- `routing_mode`: `proxy` mantiene el dominio original; `redirect` responde con 302.
- `check_interval_seconds`: cada cuántos segundos revisa las IPs.
- `connect_timeout_seconds`: tiempo máximo para considerar que un destino responde.
- `fail_threshold`: fallos consecutivos para marcar un destino como caído.
- `recover_threshold`: éxitos consecutivos para volver a marcarlo como sano.
- `targets[].proxy_url`: a dónde se enviará el tráfico si ese destino está sano.
- `targets[].health_url`: URL que se consulta para saber si responde.
- `targets[].host_header`: cabecera `Host` enviada al backend. Útil cuando apuntas directo a una IP pero el sitio espera el dominio.
- `fallback.type`: `proxy`, `redirect` o `static`.

## Fallback

Hay dos alternativas:

### 1. Fallback como microservicio

```json
"fallback": {
  "type": "proxy",
  "name": "microservicio-respaldo",
  "proxy_url": "http://fallback:80",
  "host_header": "mmm.cl"
}
```

### 2. Fallback como HTML local

```json
"fallback": {
  "type": "static",
  "name": "html-local"
}
```

## Producción con HTTPS

La forma más limpia es dejar este contenedor escuchando en un puerto interno, por ejemplo `8080:80`, y que el Nginx/Certbot del host termine HTTPS y haga proxy hacia este contenedor.

Ejemplo en el Nginx del host:

```nginx
server {
    listen 443 ssl;
    server_name mmm.cl;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
