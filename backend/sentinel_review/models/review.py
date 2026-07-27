from django.db import models

from .pull_request import PullRequest


class Review(models.Model):
    """A review run triggered by a pull request event."""

    class Trigger(models.TextChoices):
        OPENED = "opened", "Opened"
        SYNCHRONIZE = "synchronize", "Synchronize"
        REQUESTED = "requested", "Requested"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE, related_name="reviews")
    github_review_id = models.BigIntegerField(null=True, blank=True)
    triggered_by = models.CharField(max_length=20, choices=Trigger.choices, default=Trigger.OPENED)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    latency_ms = models.IntegerField(null=True, blank=True, help_text="LLM processing time in ms")
    token_cost = models.IntegerField(
        null=True, blank=True, help_text="Total tokens used across all LLM calls"
    )
    findings_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "review"
        verbose_name = "Review"
        verbose_name_plural = "Reviews"
        indexes = [
            models.Index(fields=["pull_request"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Review #{self.id} for PR #{self.pull_request.github_pr_number}"
