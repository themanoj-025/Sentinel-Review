import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sentinel_review.settings")

app = Celery("sentinel_review")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.task_routes = {
    "sentinel_review.workers.review_worker.*": {"queue": "reviews"},
    "sentinel_review.workers.feedback_worker.*": {"queue": "feedback"},
}
