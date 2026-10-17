"""Gunicorn untuk API publik (Bagian 9.2)."""

bind = "127.0.0.1:8000"
workers = 2
worker_class = "sync"

# Satu model, dibagi antar-worker lewat copy-on-write. Tanpa ini setiap worker
# menambah ~600 MB penuh.
preload_app = True

timeout = 60
graceful_timeout = 30

# Proses Python yang memegang tensor cenderung merambat naik pemakaian
# memorinya. Daur ulang worker untuk layanan yang hidup berbulan-bulan.
max_requests = 2000
max_requests_jitter = 200      # jangan sampai semua worker restart bersamaan

accesslog = "-"
errorlog = "-"
