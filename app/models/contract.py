"""A student's training contract (сургалтын гэрээ) — one per enrollment.

Ported from the standalone ``ai-asia-contract`` service: the student checks their
details, previews the filled PDF, agrees, draws a signature, and the signed PDF is
kept. Here the PDF template is the course's uploaded ``contract_template_key`` and
the money figures come from the enrollment's ledger, not from the client.
"""
from datetime import datetime

from app.extensions import db
from app.timeutil import iso

# pending   — exists, waiting for the student's signature
# signed    — signed; final (staff may reset it back to pending)
# cancelled — the enrollment was cancelled before the contract was signed
CONTRACT_STATUSES = ("pending", "signed", "cancelled")


class StudentContract(db.Model):
    __tablename__ = "student_contracts"

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    course_id = db.Column(
        db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cohort_id = db.Column(db.Integer, db.ForeignKey("cohorts.id", ondelete="SET NULL"))
    contract_number = db.Column(db.String(40), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)

    # What the student submitted when signing (snake_case field -> value).
    form_data = db.Column(db.JSON)
    # Money as it stood at signing — the PDF says these, so they are frozen with it.
    total_due = db.Column(db.Numeric(12, 2))
    total_paid = db.Column(db.Numeric(12, 2))
    balance = db.Column(db.Numeric(12, 2))
    discount_percent = db.Column(db.Integer)

    template_key = db.Column(db.String(500))   # the course template the PDF was built from
    file_key = db.Column(db.String(500))       # signed PDF on S3
    signature_key = db.Column(db.String(500))  # signature PNG on S3

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    signed_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    enrollment = db.relationship("Enrollment")
    student = db.relationship("Student")
    course = db.relationship("Course")
    cohort = db.relationship("Cohort")

    @property
    def has_document(self) -> bool:
        return self.status == "signed" and bool(self.file_key)

    @staticmethod
    def _money(value):
        return float(value) if value is not None else None

    def to_dict(self) -> dict:
        """The list/detail shape shared by the student app and staff."""
        course, cohort = self.course, self.cohort
        return {
            "id": self.id,
            "contract_number": self.contract_number,
            "status": self.status,
            "enrollment_id": self.enrollment_id,
            "course_id": self.course_id,
            "course": {
                "id": course.id, "slug": course.slug,
                "title": {"mn": course.title_mn, "en": course.title_en},
                "level": course.level,
            } if course is not None else None,
            "cohort": {
                "id": cohort.id, "name": cohort.name,
                "start_date": iso(cohort.start_date), "end_date": iso(cohort.end_date),
            } if cohort is not None else None,
            "created_at": iso(self.created_at),
            "signed_at": iso(self.signed_at),
            "cancelled_at": iso(self.cancelled_at),
        }

    def to_staff_dict(self) -> dict:
        data = self.to_dict()
        s = self.student
        data.update({
            "student_id": self.student_id,
            "student_name": f"{s.first_name} {s.last_name or ''}".strip() if s else None,
            "form_data": self.form_data,
            "total_due": self._money(self.total_due),
            "total_paid": self._money(self.total_paid),
            "balance": self._money(self.balance),
            "discount_percent": self.discount_percent,
            "has_file": self.has_document,
        })
        return data

    def __repr__(self) -> str:
        return f"<StudentContract {self.id} {self.contract_number} {self.status}>"
