"""End-to-end engine test: 4 parallel agents run, findings merge + de-dupe."""
from engine import run_review


SAMPLE_DIFF = """diff --git a/app.py b/app.py
@@ -1,5 +1,6 @@
 def handler(req):
-    pass
+    password = 'hunter2'
+    global counter
+    try:
+        process(req)
+    except:
+        pass
     return 'ok'
"""


async def test_run_review_offline_produces_merged_result():
    result = await run_review(SAMPLE_DIFF)
    assert result.comments, "expected at least one finding"
    # security agent should flag the hard-coded password
    security = [c for c in result.comments if c.category.value == "security"]
    assert security, "security agent should have flagged the password"
    assert any(
        ("password" in c.body.lower()) or ("credential" in c.body.lower())
        for c in security
    )
    assert result.summary


async def test_run_review_dedupes_identical_comments():
    dup = "diff --git a/x.py b/x.py\n@@\n+except:\n+    pass\n"
    r1 = await run_review(dup)
    # no duplicate (file/line/body) entries
    seen = set()
    for c in r1.comments:
        key = (c.file_path, c.line, c.body.strip().lower())
        assert key not in seen, "duplicate comment survived merge"
        seen.add(key)
