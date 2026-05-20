"""create core tables

Revision ID: 20260520_0001
Revises:
Create Date: 2026-05-20 22:43:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260520_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("preferred_language", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_patients_phone"), "patients", ["phone"], unique=True)

    op.create_table(
        "doctor_schedule",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("doctor_name", sa.String(length=200), nullable=False),
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_doctor_schedule_available_from"), "doctor_schedule", ["available_from"], unique=False)
    op.create_index(op.f("ix_doctor_schedule_available_to"), "doctor_schedule", ["available_to"], unique=False)
    op.create_index(op.f("ix_doctor_schedule_doctor_name"), "doctor_schedule", ["doctor_name"], unique=False)

    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doctor_name", sa.String(length=200), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_appointments_doctor_name"), "appointments", ["doctor_name"], unique=False)
    op.create_index(op.f("ix_appointments_end_time"), "appointments", ["end_time"], unique=False)
    op.create_index(op.f("ix_appointments_patient_id"), "appointments", ["patient_id"], unique=False)
    op.create_index(op.f("ix_appointments_start_time"), "appointments", ["start_time"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_appointments_start_time"), table_name="appointments")
    op.drop_index(op.f("ix_appointments_patient_id"), table_name="appointments")
    op.drop_index(op.f("ix_appointments_end_time"), table_name="appointments")
    op.drop_index(op.f("ix_appointments_doctor_name"), table_name="appointments")
    op.drop_table("appointments")

    op.drop_index(op.f("ix_doctor_schedule_doctor_name"), table_name="doctor_schedule")
    op.drop_index(op.f("ix_doctor_schedule_available_to"), table_name="doctor_schedule")
    op.drop_index(op.f("ix_doctor_schedule_available_from"), table_name="doctor_schedule")
    op.drop_table("doctor_schedule")

    op.drop_index(op.f("ix_patients_phone"), table_name="patients")
    op.drop_table("patients")

