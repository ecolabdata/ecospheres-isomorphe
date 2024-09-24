web: gunicorn -w 4 -b 0.0.0.0:5000 'isomorphe.app:app'
worker: rq worker --url $REDIS_URL
