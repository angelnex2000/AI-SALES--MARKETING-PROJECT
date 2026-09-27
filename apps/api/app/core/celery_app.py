from celery import Celery
from celery.signals import setup_logging

from app.core.config import settings
from app.core.logging import configure_logging

celery_app = Celery("ai_sales_teammate", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.task_default_queue = "default"

# Fail fast when the broker is down. Celery's defaults retry a connection ~100
# times with backoff, so an API request that only wants to enqueue a job hangs
# for a minute before job_service.enqueue can turn the failure into a 503.
# These are the knobs that actually bound a *publish* from the web process —
# task_publish_retry_policy alone does not, because the time is spent
# establishing the connection, not retrying the publish.
celery_app.conf.broker_connection_timeout = 2  # seconds to open a socket
celery_app.conf.broker_connection_max_retries = 1
celery_app.conf.task_publish_retry_policy = {
    "max_retries": 1,
    "interval_start": 0,
    "interval_step": 0.2,
    "interval_max": 0.5,
}
# The result backend has its own retry loop; without this a dead Redis also
# stalls here rather than surfacing quickly.
celery_app.conf.result_backend_transport_options = {"retry_policy": {"timeout": 2.0}}
celery_app.conf.redis_retry_on_timeout = False


@setup_logging.connect
def _configure_worker_logging(**_kwargs: object) -> None:
    """Celery installs its own logging config by default. Connecting to this
    signal suppresses that and gives worker output the same JSON shape as the
    API, so both land in one aggregator with the same fields."""
    configure_logging()
