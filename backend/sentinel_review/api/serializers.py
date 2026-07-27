from rest_framework import serializers

from sentinel_review.models.comment import Comment
from sentinel_review.models.feedback import Feedback
from sentinel_review.models.installation import Installation
from sentinel_review.models.pull_request import PullRequest
from sentinel_review.models.repo import Repo
from sentinel_review.models.review import Review


class InstallationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Installation
        fields = ["id", "github_installation_id", "account_login", "created_at"]


class RepoSerializer(serializers.ModelSerializer):
    installation = InstallationSerializer(read_only=True)

    class Meta:
        model = Repo
        fields = [
            "id", "installation", "github_repo_id", "full_name",
            "is_private", "config", "created_at",
        ]


class PullRequestSerializer(serializers.ModelSerializer):
    repo = RepoSerializer(read_only=True)

    class Meta:
        model = PullRequest
        fields = [
            "id", "repo", "github_pr_number", "title",
            "author_login", "status", "created_at",
        ]


class CommentSerializer(serializers.ModelSerializer):
    upvotes = serializers.SerializerMethodField()
    downvotes = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            "id", "review", "github_comment_id", "file_path",
            "line_number", "category", "severity", "content",
            "suggested_fix", "created_at", "upvotes", "downvotes",
        ]

    def get_upvotes(self, obj) -> int:
        return obj.feedback.filter(reaction="thumbs_up").count()

    def get_downvotes(self, obj) -> int:
        return obj.feedback.filter(reaction="thumbs_down").count()


class ReviewSerializer(serializers.ModelSerializer):
    pull_request = PullRequestSerializer(read_only=True)
    comments = CommentSerializer(many=True, read_only=True)

    class Meta:
        model = Review
        fields = [
            "id", "pull_request", "github_review_id",
            "triggered_by", "status", "latency_ms",
            "token_cost", "findings_count", "error_message",
            "created_at", "comments",
        ]


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = ["id", "comment", "reaction", "reactor_login", "created_at"]


class RepoConfigSerializer(serializers.Serializer):
    """Serializer for updating repo configuration."""
    enabled_categories = serializers.ListField(
        child=serializers.ChoiceField(choices=["bug", "style", "security", "suggestion"]),
        required=False,
    )
    max_comments = serializers.IntegerField(min_value=1, max_value=100, required=False)
    private_repo_opt_in = serializers.BooleanField(required=False)
