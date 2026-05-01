# Deploy notes for reg.ru (89.108.81.151)

The "Звук вокруг" / "Вокруг" features stream raw PCM audio over long-lived
HTTP requests. nginx in front of gunicorn buffers both responses and request
bodies by default — this kills realtime streaming.

## 1. Nginx site config

Put this **inside the `server { ... }` block** that proxies to gunicorn (do
not duplicate the whole server block — just add/adjust the locations and the
listen 80 part):

```nginx
server {
    listen 80;
    server_name 89.108.81.151;

    client_max_body_size 50m;

    # Default proxy → gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_read_timeout  3600s;
        proxy_send_timeout  3600s;
    }

    # Realtime audio: parent download stream
    location ~ ^/api/children/[0-9]+/around-audio/live/stream/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering           off;
        proxy_cache               off;
        chunked_transfer_encoding on;
        proxy_read_timeout        3600s;
        proxy_send_timeout        3600s;
        gzip                      off;
    }

    # Realtime audio: child upload stream
    location = /api/around-audio/live/upload/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_request_buffering   off;
        proxy_buffering           off;
        client_max_body_size      0;
        proxy_read_timeout        3600s;
        proxy_send_timeout        3600s;
    }

    # WebRTC signaling poll (HTTP long-poll-ish)
    location ~ ^/api/monitor/signal/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering   off;
        proxy_read_timeout 60s;
    }
}
```

Apply:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 2. Gunicorn

Gunicorn must use a worker class that supports streaming + many concurrent
long-lived requests. Use `gthread` with multiple threads, e.g.:

```bash
gunicorn config.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 3 \
    --worker-class gthread \
    --threads 8 \
    --timeout 0 \
    --keep-alive 75 \
    --access-logfile -
```

`--timeout 0` is **mandatory**. Otherwise gunicorn kills the worker after
30s of "no progress" (which is exactly what a streaming upload looks like
to gunicorn's heuristic) and you get either 504 on the parent or the child
upload silently aborts mid-stream. The classic symptom is "ждал 2–3 минуты
и вышло 504" — that's gunicorn killing the upload worker, not nginx.

## 2.1 Sanity check

After applying the config and restarting, from the server itself run:

```bash
# 1. Verify nginx is forwarding chunked POST without buffering.
curl -v -N -X POST \
    -H 'Authorization: Token <child_token>' \
    -H 'Transfer-Encoding: chunked' \
    --data-binary @- \
    "http://127.0.0.1/api/around-audio/live/upload/?session_token=test123" \
    < /dev/zero

# Within ~1s gunicorn's access log should show the request landing
# (not waiting for the upload to finish). If it only shows up after
# Ctrl+C, request buffering is still on.
```

```bash
# 2. Verify the parent stream flushes immediately.
curl -v -N \
    -H 'Authorization: Token <parent_token>' \
    "http://127.0.0.1/api/children/<child_id>/around-audio/live/stream/?session_token=test123"

# You should see the silence keep-alive frame land within ~1s and then
# every 5s. If nothing arrives for 60s, response buffering is still on.
```

## 3. Django env

`pythonanywhere_wsgi.py` no longer forces SSL redirect / HSTS, because the
client uses plain `http://89.108.81.151`. If/when you add a real TLS cert
(e.g. via Let's Encrypt on a domain), flip those flags back to `True` AND
update `lib/core/services/api_client.dart` to use `https://your.domain`.
