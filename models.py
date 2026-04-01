"""
UpQuest – Pydantic request/response models
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class UserStats(BaseModel):
    age: int = Field(..., ge=13, le=120, description="User age in years")
    height_inches: float = Field(..., description="Height in inches")
    weight_lbs: float = Field(..., description="Weight in pounds")
    sex: str = Field(..., description="'male' or 'female'")
    location: Optional[str] = Field(None, description="City, State (for climate-aware tips)")
    activity_level: Optional[str] = Field(
        "moderate",
        description="sedentary | light | moderate | active | very_active",
    )
    medical_notes: Optional[str] = Field(None, description="Any conditions or medications")


class ProfileUpdateRequest(BaseModel):
    stats: UserStats
    goals: List[str] = Field(..., description="List of goal keys from GOALS constant")


class ScheduleRequest(BaseModel):
    stats: UserStats
    goals: List[str]
    week_start: Optional[str] = Field(None, description="ISO date, e.g. '2026-04-06'")
    bloodwork_summary: Optional[Dict[str, Any]] = Field(
        None, description="Extracted lab values (premium only)"
    )


class ProgressEntry(BaseModel):
    weight_lbs: Optional[float] = None
    smoke_free_days: Optional[int] = None
    bench_press_lbs: Optional[float] = None
    squat_lbs: Optional[float] = None
    deadlift_lbs: Optional[float] = None
    notes: Optional[str] = None
    custom: Optional[Dict[str, Any]] = Field(
        None, description="Any additional metrics the user wants to track"
    )
