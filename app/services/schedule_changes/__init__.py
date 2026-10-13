"""Teacher-to-teacher schedule-change (class handover) requests.

A cohort's teacher asks another active teacher to cover one class session; the
recipient accepts or rejects it in the app. An accepted request is the covering
assignment — the session then shows on the recipient's schedule as
``covering`` and the sender's schedule is left as it was. Contract:
docs/schedule_change_api_v1.md.
"""
from .decisions import accept, cancel, reject  # noqa: F401
from .eligible import eligible_teachers  # noqa: F401
from .requests import create, get, list_requests  # noqa: F401
from .schedule import covering_sessions, my_sessions  # noqa: F401
