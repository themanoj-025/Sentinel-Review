"""
Root conftest — sets up Django environment for all tests.
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sentinel_review.settings")
os.environ.setdefault("DJANGO_DEBUG", "False")
os.environ.setdefault("WEBHOOK_SECRET", "test-secret-key")
os.environ.setdefault("GITHUB_APP_ID", "123456")
os.environ.setdefault(
    "GITHUB_APP_PRIVATE_KEY_B64",
    "LS0tLS1CRUdJTiBSU0EgUFJJVkFURSBLRVktLS0tLQpUZXN0S2V5Cj09PT09",
)
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test0000000000000000000")
os.environ.setdefault("DATABASE_URL", "sqlite:///test_db.sqlite3")
