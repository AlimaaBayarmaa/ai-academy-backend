"""Course certificates: eligibility (§2.9), staff issuing, files, verification.

PDFs are generated from the course's certificate template (``generation``,
``pdf``) like ``ai-asia-contract`` did per class; ``cohort`` issues a whole class.

``certificate_status(student_id, course, enrollment)`` is the entry point the
learning service uses for the certificate summary on the module list.
"""
from .cohort import issue_for_cohort
from .eligibility import certificate_status, is_eligible, requirements
from .generation import generate
from .issuing import (
    archive,
    get_certificate,
    issue,
    list_certificates,
    student_download,
    upload_file,
)
from .mine import my_certificates
from .page import verify_page
from .verification import verify

__all__ = [
    "archive",
    "certificate_status",
    "generate",
    "get_certificate",
    "is_eligible",
    "issue",
    "issue_for_cohort",
    "list_certificates",
    "my_certificates",
    "requirements",
    "student_download",
    "upload_file",
    "verify",
    "verify_page",
]
