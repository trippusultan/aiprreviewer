"""Celery worker package for the AI PR Reviewer.

`worker.pipeline` holds the pure async review logic (no Celery/Redis import);
`worker.tasks` wraps it as a Celery task. This module re-exports both so that
`import worker` continues to work.
"""
from worker.pipeline import process_pr  # noqa: F401
from worker.tasks import celery_app, process_pr_task  # noqa: F401
