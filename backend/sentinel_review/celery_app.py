import logging
import os

from celery import Celery

from sentinel_review.logging_filters import MappingArgsFilter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sentinel_review.settings")

app = Celery("sentinel_review")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Celery's trace logger emits mapping-style messages with the context dict
# wrapped in a tuple (record.args = (dict,)), which Python logging cannot
# render (TypeError: format requires a mapping). Attach the normalizing
# filter at logger level so it runs before ANY handler (Django console,
# pytest capture, JSON formatter) formats the record.
for _logger_name in ("celery", "celery.app.trace"):
    logging.getLogger(_logger_name).addFilter(MappingArgsFilter())

app.conf.task_routes = {
    "sentinel_review.workers.review_worker.*": {"queue": "reviews"},
    "sentinel_review.workers.feedback_worker.*": {"queue": "feedback"},
}
