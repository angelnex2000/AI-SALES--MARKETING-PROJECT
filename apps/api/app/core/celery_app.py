from celery import Celery

from app.core.config import settings

celery_app = Celery("ai_sales_teammate", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.task_default_queue = "default"