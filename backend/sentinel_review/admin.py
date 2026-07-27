from django.contrib import admin

from sentinel_review.models.comment import Comment
from sentinel_review.models.feedback import Feedback
from sentinel_review.models.installation import Installation
from sentinel_review.models.pull_request import PullRequest
from sentinel_review.models.repo import Repo
from sentinel_review.models.review import Review


@admin.register(Installation)
class InstallationAdmin(admin.ModelAdmin):
    list_display = ["github_installation_id", "account_login", "account_type", "created_at"]
    search_fields = ["account_login"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Repo)
class RepoAdmin(admin.ModelAdmin):
    list_display = ["full_name", "installation", "is_private", "created_at"]
    list_filter = ["is_private"]
    search_fields = ["full_name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(PullRequest)
class PullRequestAdmin(admin.ModelAdmin):
    list_display = ["github_pr_number", "repo", "title", "author_login", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["title", "author_login"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["id", "pull_request", "status", "triggered_by", "findings_count", "latency_ms", "created_at"]
    list_filter = ["status", "triggered_by"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["id", "review", "file_path", "line_number", "category", "severity", "created_at"]
    list_filter = ["category", "severity"]
    search_fields = ["file_path", "content"]
    readonly_fields = ["created_at"]


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ["id", "comment", "reaction", "reactor_login", "created_at"]
    list_filter = ["reaction"]
    readonly_fields = ["created_at"]
