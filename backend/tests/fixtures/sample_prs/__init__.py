"""
Planted-bug fixture diffs for the evaluation set.

Each fixture is a (diff, known_issues) pair covering a specific
vulnerability category. These serve as unit test fixtures AND as
the security-testing artifact required by the project spec.
"""

from __future__ import annotations

from typing import Any

# ─── Fixture 1: SQL Injection ────────────────────────────────────────────

SQL_INJECTION_DIFF = """diff --git a/users.py b/users.py
--- a/users.py
+++ b/users.py
@@ -5,7 +5,8 @@
 def get_user(email):
-    query = "SELECT * FROM users WHERE email = %s" % email
+    query = f"SELECT * FROM users WHERE email = '{email}'"
     cursor.execute(query)
     return cursor.fetchone()

+def delete_user(user_id):
+    db.execute("DELETE FROM users WHERE id = " + str(user_id))
"""

SQL_INJECTION_KNOWN_ISSUES: list[dict[str, Any]] = [
    {
        "file_path": "users.py",
        "line_number": 6,
        "category": "security",
        "severity": "blocking",
        "description": "SQL injection via f-string interpolation with user-controlled email",
    },
    {
        "file_path": "users.py",
        "line_number": 10,
        "category": "security",
        "severity": "blocking",
        "description": "SQL injection via string concatenation with user_id",
    },
]

# ─── Fixture 2: Hardcoded Secret ─────────────────────────────────────────

HARDCODED_SECRET_DIFF = """diff --git a/config.py b/config.py
--- a/config.py
+++ b/config.py
@@ -1,2 +1,5 @@
 DEBUG = True
+API_SECRET = "sk-live-abcdef1234567890"
+DB_PASSWORD = "password123"
+SECRET_KEY = "super-secret-key-12345"
"""

HARDCODED_SECRET_KNOWN_ISSUES: list[dict[str, Any]] = [
    {
        "file_path": "config.py",
        "line_number": 2,
        "category": "security",
        "severity": "blocking",
        "description": "Hardcoded API secret key committed to source code",
    },
    {
        "file_path": "config.py",
        "line_number": 3,
        "category": "security",
        "severity": "blocking",
        "description": "Hardcoded database password committed to source code",
    },
    {
        "file_path": "config.py",
        "line_number": 4,
        "category": "security",
        "severity": "blocking",
        "description": "Hardcoded Django SECRET_KEY committed to source code",
    },
]

# ─── Fixture 3: Unsafe Deserialization ──────────────────────────────────

UNSAFE_DESERIALIZATION_DIFF = """diff --git a/api.py b/api.py
--- a/api.py
+++ b/api.py
@@ -1,4 +1,7 @@
 import pickle
+import base64
+
+def load_session(data):
+    return pickle.loads(base64.b64decode(data))

 def load_config(path):
     with open(path) as f:
"""

UNSAFE_DESERIALIZATION_KNOWN_ISSUES: list[dict[str, Any]] = [
    {
        "file_path": "api.py",
        "line_number": 5,
        "category": "security",
        "severity": "blocking",
        "description": "Unsafe deserialization with pickle.loads on untrusted input — can lead to RCE",
    },
]

# ─── Fixture 4: Off-by-One / Null-Pointer Bug ────────────────────────────

OFF_BY_ONE_DIFF = """diff --git a/processor.py b/processor.py
--- a/processor.py
+++ b/processor.py
@@ -7,8 +7,9 @@
 def process_items(items):
-    for i in range(1, len(items)):
+    for i in range(1, len(items) + 1):
         item = items[i]
         result = transform(item)
+        if item is None:
+            continue
         results.append(result)
     return results
"""

OFF_BY_ONE_KNOWN_ISSUES: list[dict[str, Any]] = [
    {
        "file_path": "processor.py",
        "line_number": 9,
        "category": "bug",
        "severity": "blocking",
        "description": "Off-by-one error: range(1, len(items) + 1) causes IndexError on last iteration",
    },
    {
        "file_path": "processor.py",
        "line_number": 10,
        "category": "bug",
        "severity": "warning",
        "description": "Potentially accessing items[i] when i is out of bounds (see off-by-one above)",
    },
]

# ─── Fixture 5: Clean Diff (No Issues) ───────────────────────────────────

CLEAN_DIFF = """diff --git a/utils.py b/utils.py
--- a/utils.py
+++ b/utils.py
@@ -1,4 +1,4 @@
-def format_name(first, last):
-    return first + ' ' + last
+def format_name(first_name, last_name):
+    return first_name + ' ' + last_name
 """

CLEAN_DIFF_KNOWN_ISSUES: list[dict[str, Any]] = []

# ─── Fixture 6: Missing Test / Logic Error ──────────────────────────────

MISSING_TEST_DIFF = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,7 +1,10 @@
 def divide(a, b):
+    return a / b
+```
+
+```python
+def divide(a, b):
     if b == 0:
         return None
     return a / b
-
-def add(a, b):
-    return a + b
 """

MISSING_TEST_KNOWN_ISSUES: list[dict[str, Any]] = [
    {
        "file_path": "calculator.py",
        "line_number": 2,
        "category": "bug",
        "severity": "blocking",
        "description": "Division function lacks zero-division check — will raise ZeroDivisionError",
    },
]

# ─── Master List ─────────────────────────────────────────────────────────

FIXTURES: list[dict[str, Any]] = [
    {
        "id": "sql_injection",
        "diff": SQL_INJECTION_DIFF,
        "known_issues": SQL_INJECTION_KNOWN_ISSUES,
        "description": "SQL injection via f-string and string concatenation",
    },
    {
        "id": "hardcoded_secret",
        "diff": HARDCODED_SECRET_DIFF,
        "known_issues": HARDCODED_SECRET_KNOWN_ISSUES,
        "description": "Hardcoded API secrets, database passwords, and secret keys",
    },
    {
        "id": "unsafe_deserialization",
        "diff": UNSAFE_DESERIALIZATION_DIFF,
        "known_issues": UNSAFE_DESERIALIZATION_KNOWN_ISSUES,
        "description": "Unsafe pickle.loads on user-controlled data",
    },
    {
        "id": "off_by_one",
        "diff": OFF_BY_ONE_DIFF,
        "known_issues": OFF_BY_ONE_KNOWN_ISSUES,
        "description": "Off-by-one index error and potential null pointer",
    },
    {
        "id": "clean",
        "diff": CLEAN_DIFF,
        "known_issues": CLEAN_DIFF_KNOWN_ISSUES,
        "description": "Clean rename — should produce zero findings (false positive check)",
    },
    {
        "id": "missing_test",
        "diff": MISSING_TEST_DIFF,
        "known_issues": MISSING_TEST_KNOWN_ISSUES,
        "description": "Missing zero-division guard in calculator function",
    },
]
