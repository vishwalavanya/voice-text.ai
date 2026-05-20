from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.db import get_db_session
from backend.schemas.appointment_schema import (
    AppointmentCancel,
    AppointmentCreate,
    AppointmentReschedule,
    AvailabilityRequest,
)
from backend.tools.appointment_tools import (
    book_appointment,
    cancel_appointment,
    check_availability,
    reschedule_appointment,
)


router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/appointments/check")
async def check_availability_endpoint(
    payload: AvailabilityRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await check_availability(
        db=db,
        doctor_name=payload.doctor_name,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )


@router.post("/appointments/book")
async def book_appointment_endpoint(
    payload: AppointmentCreate,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await book_appointment(
        db=db,
        patient_name=payload.patient.full_name,
        patient_phone=payload.patient.phone,
        preferred_language=payload.patient.preferred_language,
        doctor_name=payload.doctor_name,
        start_time=payload.start_time,
        end_time=payload.end_time,
        reason=payload.reason,
        notes=payload.notes,
    )


@router.post("/appointments/cancel")
async def cancel_appointment_endpoint(
    payload: AppointmentCancel,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await cancel_appointment(
        db=db,
        appointment_id=str(payload.appointment_id),
        reason=payload.reason,
    )


@router.post("/appointments/reschedule")
async def reschedule_appointment_endpoint(
    payload: AppointmentReschedule,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return await reschedule_appointment(
        db=db,
        appointment_id=str(payload.appointment_id),
        new_start_time=payload.new_start_time,
        new_end_time=payload.new_end_time,
    )

