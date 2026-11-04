import os
bind = os.getenv('GUNICORN_BIND', '127.0.0.1:8000')
workers = int(os.getenv('GUNICORN_WORKERS', '3'))
worker_class = 'gthread'
threads = int(os.getenv('GUNICORN_THREADS', '8'))
timeout = 90
graceful_timeout = 30
keepalive = 5
max_requests = 2000
max_requests_jitter = 100
accesslog = '-'
errorlog = '-'
# U deliberately excludes query strings containing private session metadata.
access_log_format = '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(L)s'
forwarded_allow_ips = '127.0.0.1'
