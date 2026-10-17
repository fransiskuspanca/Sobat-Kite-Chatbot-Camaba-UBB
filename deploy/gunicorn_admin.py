"""Gunicorn untuk admin panel (Bagian 3).

Satu worker: reindex dan pencarian di admin tidak boleh menyita worker yang
sedang melayani camaba.
"""

bind = "127.0.0.1:8001"
workers = 1
worker_class = "sync"
preload_app = True

timeout = 300                  # reindex bisa 20-40 detik, beri kelonggaran
graceful_timeout = 30

accesslog = "-"
errorlog = "-"
