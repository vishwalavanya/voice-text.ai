from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PatientCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=7, max_length=30)
    preferred_language: str = Field(default="en", pattern="^(en|hi|ta)$")


class AppointmentCreate(BaseModel):
    patient: PatientCreate
    doctor_name: str = Field(min_length=2, max_length=200)
    start_time: datetime
    end_time: datetime
    reason: str | None = None
    notes: str | None = None


class AppointmentCancel(BaseModel):
    appointment_id: UUID
    reason: str | None = None


class AppointmentReschedule(BaseModel):
    appointment_id: UUID
    new_start_time: datetime
    new_end_time: datetime


class AvailabilityRequest(BaseModel):
    doctor_name: str = Field(min_length=2, max_length=200)
    start_time: datetime
    end_time: datetime


class AppointmentResponse(BaseModel):
    appointment_id: UUID
    patient_id: UUID
    doctor_name: str
    start_time: datetime
    end_time: datetime
    status: str
    reason: str | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}

