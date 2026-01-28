web: gunicorn app:app \
  --worker-class gevent \
  --workers 2 \
  --worker-connections 1000 \
  --timeout 120 \
  --graceful-timeout 30 \
  --keep-alive 5 \
  --log-level info \
  --bind 0.0.0.0:$PORT
