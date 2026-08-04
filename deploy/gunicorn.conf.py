"""
Gunicorn yapılandırması (Oracle Ampere A1, 2 OCPU / 12 GB).

nginx ile Unix soketi üzerinden konuşuyoruz; uygulama TCP portu açmıyor.
Bu sayede Gunicorn'a dışarıdan doğrudan erişmek mümkün değil.
"""

import multiprocessing

bind = "unix:/run/halisaha/gunicorn.sock"
umask = 0o007  # sokete yalnızca halisaha ve www-data erişebilsin

# 2 OCPU için 5 işçi. Üst sınır koyuyoruz: Oracle ARM kotasını düşürürse
# makine küçüldüğünde yapılandırmayı elle değiştirmek gerekmesin.
workers = min(2 * multiprocessing.cpu_count() + 1, 9)
worker_class = "sync"
threads = 2

# Sohbet 6 saniyede bir yoklama yapıyor; istekler kısa. Uzun zaman aşımına
# gerek yok, ama fotoğraf yüklemesi (8 MB'a kadar) için pay bırakıyoruz.
timeout = 60
graceful_timeout = 30
keepalive = 5

# Sızıntı olursa işçiyi periyodik yenile.
max_requests = 1000
max_requests_jitter = 100

# journalctl toplasın diye stdout/stderr'e yazıyoruz.
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms'

# Sokete yalnızca nginx erişebildiği için vekil başlıklarına güvenebiliriz.
forwarded_allow_ips = "*"

proc_name = "halisaha"
