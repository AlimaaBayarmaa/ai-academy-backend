"""Teacher-to-teacher schedule-change (class handover) requests.

A cohort's teacher asks another teacher to cover one class session. The
accepted request itself is the covering assignment: it puts the session on the
recipient's schedule as ``covering`` while the cohort's own teacher keeps it
(version 1 never swaps or removes anything). See docs/schedule_change_api_v1.md.
"""
from datetime import datetime

from app.extensions import db

# pending -> accepted | rejected | cancelled | expired; the last four are terminal.
SCHEDULE_CHANGE_STATUSES = ("pending", "accepted", "rejected", "cancelled", "expired")


class ScheduleChangeRequest(db.Model):
    __tablename__ = "schedule_change_requests"
    __table_args__ = (
        db.CheckConstraint("sender_teacher_id <> recipient_teacher_id",
                           name="ck_schedule_change_distinct_teachers"),
        # One open request per session, and at most one covering teacher.
        db.Index("uq_schedule_change_pending", "class_session_id", unique=True,
                 postgresql_where=db.text("status = 'pending'")),
        db.Index("uq_schedule_change_accepted", "class_session_id", unique=True,
                 postgresql_where=db.text("status = 'accepted'")),
    )

    id = db.Column(db.Integer, primary_key=True)
    class_session_id = db.Column(
        db.Integer, db.ForeignKey("class_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sender_teacher_id = db.Column(
        db.Integer, db.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_teacher_id = db.Column(
        db.Integer, db.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    message = db.Column(db.String(500))          # sender's optional note
    reason = db.Column(db.String(500))           # recipient's optional rejection reason
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    resolved_at = db.Column(db.DateTime)
    resolved_by_teacher_id = db.Column(
        db.Integer, db.ForeignKey("teachers.id", ondelete="SET NULL")
    )

    session = db.relationship("ClassSession")
    sender = db.relationship("Teacher", foreign_keys=[sender_teacher_id])
    recipient = db.relationship("Teacher", foreign_keys=[recipient_teacher_id])

    def __repr__(self) -> str:
        return f"<ScheduleChangeRequest {self.id} session={self.class_session_id} {self.status}>"
