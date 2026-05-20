from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Appointment, AppointmentStatus, DoctorSchedule, Patient


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _find_or_create_patient(
    db: AsyncSession,
    full_name: str,
    phone: str,
    preferred_language: str = "en",
) -> Patient:
    existing = await db.execute(select(Patient).where(Patient.phone == phone))
    patient = existing.scalar_one_or_none()
    if patient:
        patient.full_name = full_name
        patient.preferred_language = preferred_language
        return patient

    patient = Patient(
        full_name=full_name,
        phone=phone,
        preferred_language=preferred_language,
    )
    db.add(patient)
    await db.flush()
    return patient


async def _is_within_doctor_schedule(
    db: AsyncSession,
    doctor_name: str,
    start_time: datetime,
    end_time: datetime,
) -> bool:
    result = await db.execute(
        select(DoctorSchedule).where(DoctorSchedule.doctor_name == doctor_name)
    )
    schedules = result.scalars().all()
    if not schedules:
        return True

    for row in schedules:
        if row.available_from <= start_time and row.available_to >= end_time:
            return True
    return False


async def _get_overlaps(
    db: AsyncSession,
    doctor_name: str,
    start_time: datetime,
    end_time: datetime,
    exclude_appointment_id: UUID | None = None,
) -> list[Appointment]:
    conditions = [
        Appointment.doctor_name == doctor_name,
        Appointment.status != AppointmentStatus.CANCELLED.value,
        or_(
            and_(Appointment.start_time <= start_time, Appointment.end_time > start_time),
            and_(Appointment.start_time < end_time, Appointment.end_time >= end_time),
            and_(Appointment.start_time >= start_time, Appointment.end_time <= end_time),
        ),
    ]
    if exclude_appointment_id is not None:
        conditions.append(Appointment.id != exclude_appointment_id)

    result = await db.execute(select(Appointment).where(and_(*conditions)))
    return list(result.scalars().all())


async def check_availability(
    db: AsyncSession,
    doctor_name: str,
    start_time: str | datetime,
    end_time: str | datetime,
) -> dict[str, Any]:
    start_dt = _parse_datetime(start_time)
    end_dt = _parse_datetime(end_time)
    if start_dt >= end_dt:
        return {"available": False, "reason": "Invalid time range: start_time must be before end_time."}

    within_schedule = await _is_within_doctor_schedule(db, doctor_name, start_dt, end_dt)
    if not within_schedule:
        return {
            "available": False,
            "reason": "Requested slot is outside doctor schedule.",
        }

    overlaps = await _get_overlaps(db, doctor_name, start_dt, end_dt)
    return {
        "available": len(overlaps) == 0,
        "reason": "Slot is available." if len(overlaps) == 0 else "Doctor already has an appointment in this slot.",
        "conflicts": [
            {
                "appointment_id": str(item.id),
                "start_time": item.start_time.isoformat(),
                "end_time": item.end_time.isoformat(),
                "status": item.status,
            }
            for item in overlaps
        ],
    }


async def book_appointment(
    db: AsyncSession,
    patient_name: str,
    patient_phone: str,
    doctor_name: str,
    start_time: str | datetime,
    end_time: str | datetime,
    preferred_language: str = "en",
    reason: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    start_dt = _parse_datetime(start_time)
    end_dt = _parse_datetime(end_time)
    if start_dt >= end_dt:
        return {"success": False, "message": "Invalid time range: start_time must be before end_time."}

    availability = await check_availability(db, doctor_name, start_dt, end_dt)
    if not availability["available"]:
        return {"success": False, "message": availability["reason"], "details": availability}

    patient = await _find_or_create_patient(
        db=db,
        full_name=patient_name,
        phone=patient_phone,
        preferred_language=preferred_language,
    )

    appointment = Appointment(
        patient_id=patient.id,
        doctor_name=doctor_name,
        start_time=start_dt,
        end_time=end_dt,
        status=AppointmentStatus.SCHEDULED.value,
        reason=reason,
        notes=notes,
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    return {
        "success": True,
        "message": "Appointment booked successfully.",
        "appointment": {
            "appointment_id": str(appointment.id),
            "patient_id": str(appointment.patient_id),
            "doctor_name": appointment.doctor_name,
            "start_time": appointment.start_time.isoformat(),
            "end_time": appointment.end_time.isoformat(),
            "status": appointment.status,
            "reason": appointment.reason,
            "notes": appointment.notes,
        },
    }


async def cancel_appointment(
    db: AsyncSession,
    appointment_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    result = await db.execute(select(Appointment).where(Appointment.id == UUID(appointment_id)))
    appointment = result.scalar_one_or_none()
    if not appointment:
        return {"success": False, "message": "Appointment not found."}

    if appointment.status == AppointmentStatus.CANCELLED.value:
        return {"success": True, "message": "Appointment already cancelled."}

    appointment.status = AppointmentStatus.CANCELLED.value
    if reason:
        appointment.notes = f"{appointment.notes or ''}\nCancellation reason: {reason}".strip()
    await db.commit()
    await db.refresh(appointment)

    return {
        "success": True,
        "message": "Appointment cancelled successfully.",
        "appointment_id": str(appointment.id),
        "status": appointment.status,
    }


async def reschedule_appointment(
    db: AsyncSession,
    appointment_id: str,
    new_start_time: str | datetime,
    new_end_time: str | datetime,
) -> dict[str, Any]:
    result = await db.execute(select(Appointment).where(Appointment.id == UUID(appointment_id)))
    appointment = result.scalar_one_or_none()
    if not appointment:
        return {"success": False, "message": "Appointment not found."}

    new_start_dt = _parse_datetime(new_start_time)
    new_end_dt = _parse_datetime(new_end_time)
    if new_start_dt >= new_end_dt:
        return {"success": False, "message": "Invalid time range: start_time must be before end_time."}

    within_schedule = await _is_within_doctor_schedule(
        db,
        appointment.doctor_name,
        new_start_dt,
        new_end_dt,
    )
    if not within_schedule:
        return {
            "success": False,
            "message": "Requested reschedule slot is outside doctor schedule.",
        }

    overlaps = await _get_overlaps(
        db,
        appointment.doctor_name,
        new_start_dt,
        new_end_dt,
        exclude_appointment_id=appointment.id,
    )
    if overlaps:
        return {
            "success": False,
            "message": "Reschedule conflict: doctor already booked in this slot.",
            "conflicts": [
                {
                    "appointment_id": str(item.id),
                    "start_time": item.start_time.isoformat(),
                    "end_time": item.end_time.isoformat(),
                }
                for item in overlaps
            ],
        }

    appointment.start_time = new_start_dt
    appointment.end_time = new_end_dt
    appointment.status = AppointmentStatus.RESCHEDULED.value
    await db.commit()
    await db.refresh(appointment)

    return {
        "success": True,
        "message": "Appointment rescheduled successfully.",
        "appointment": {
            "appointment_id": str(appointment.id),
            "doctor_name": appointment.doctor_name,
            "start_time": appointment.start_time.isoformat(),
            "end_time": appointment.end_time.isoformat(),
            "status": appointment.status,
        },
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check whether a doctor is available for a requested time slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_name": {"type": "string"},
                    "start_time": {"type": "string", "description": "ISO-8601 datetime"},
                    "end_time": {"type": "string", "description": "ISO-8601 datetime"},
                },
                "required": ["doctor_name", "start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book a patient appointment with a doctor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string"},
                    "patient_phone": {"type": "string"},
                    "doctor_name": {"type": "string"},
                    "start_time": {"type": "string", "description": "ISO-8601 datetime"},
                    "end_time": {"type": "string", "description": "ISO-8601 datetime"},
                    "preferred_language": {"type": "string", "enum": ["en", "hi", "ta"]},
                    "reason": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": [
                    "patient_name",
                    "patient_phone",
                    "doctor_name",
                    "start_time",
                    "end_time",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Cancel an existing appointment by appointment id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["appointment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": "Reschedule an existing appointment to another slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "new_start_time": {"type": "string", "description": "ISO-8601 datetime"},
                    "new_end_time": {"type": "string", "description": "ISO-8601 datetime"},
                },
                "required": ["appointment_id", "new_start_time", "new_end_time"],
            },
        },
    },
]

