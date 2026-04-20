"""
UpQuest â Grok prompt builder & response parser
Produces the god-tier weekly schedule JSON.
"""

import json
import re
from typing import Any, Dict, List, Optional


SYSTEM_PERSONA = """
You are UpQuest AI â a world-class AI health caretaker combining the expertise of a
board-certified physician, registered dietitian, NSCA-certified strength coach, and
licensed therapist. You create hyper-personalized, science-backed weekly health routines
that users can actually follow. Your schedules are motivational, specific, and realistic.
DISCLAIMER: Always include: "Not medical advice â consult your doctor before making
health changes."
"""


def build_schedule_prompt(
    stats: Dict[str, Any],
    goals: List[str],
    bloodwork: Optional[Dict[str, Any]],
    week_start: str,
    health_data: Optional[str] = None,
        routine_data: Optional[str] = None,
) -> str:
    """
    Build the master UpQuest prompt for Grok.
    Returns a string prompt that produces a structured JSON schedule.
    """

    bloodwork_section = ""
    if bloodwork and len(bloodwork) > 0:
        bloodwork_section = f"""
BLOODWORK & LAB VALUES (use these to personalize nutrition and training):
{json.dumps(bloodwork, indent=2)}

Interpret out-of-range values (e.g., high triglycerides â reduce refined carbs/sugar;
low testosterone â prioritize sleep, zinc, vitamin D, resistance training;
high LDL â Mediterranean diet, soluble fiber, omega-3s).
"""
    else:
        bloodwork_section = "No bloodwork provided. Generate a general optimized schedule."

    goals_readable = ", ".join(goals).replace("_", " ")

    prompt = f"""
{SYSTEM_PERSONA}

USER STATS:
{json.dumps(stats, indent=2)}

USER GOALS: {goals_readable}

WEEK START DATE: {week_start}

{bloodwork_section}

TASK: Generate a complete, god-tier 7-day weekly health schedule for this user starting
{week_start}. The schedule should be hyper-personalized to their stats, goals, location
(if provided), and lab values.

OUTPUT FORMAT: Respond with ONLY a valid JSON object matching this EXACT structure:

{{
  "week_summary": "2-3 sentence overview of this week's focus and why",
  "days": {{
    "Monday": {{
      "date": "YYYY-MM-DD",
      "theme": "e.g. Push Day + Meal Prep",
      "schedule": {{
        "6:00 AM": "Wake up. Drink 16oz Water with lemon. 5-min deep breathing.",
        "6:30 AM": "..."
      }},
      "meals": {{
        "breakfast": {{"name": "...", "ingredients": ["..."], "macros": {{"protein_g": 0, "carbs_g": 0, "fat_g": 0, "calories": 0}}}},
        "lunch": {{"name": "...", "ingredients": ["..."], "macros": {{"protein_g": 0, "carbs_g": 0, "fat_g": 0, "calories": 0}}}},
        "dinner": {{"name": "...", "ingredients": ["..."], "macros": {{"protein_g": 0, "carbs_g": 0, "fat_g": 0, "calories": 0}}}},
        "snacks": ["..."]
      }},
      "workout": {{"type": "...", "duration_minutes": 45, "exercises": [{{"name": "...", "sets": 4, "reps": "8-10", "rest_seconds": 90}}]}},
      "habits": ["Take vitamin D3 (5000 IU)", "Journal 3 gratitudes"],
      "skin_routine": {{"morning": "...", "evening": "..."}},
      "daily_tip": "Science-backed tip personalized to their goals/labs"
    }}
  }},
  "shopping_list": {{"produce": ["..."], "proteins": ["..."]}},
  "meal_prep_instructions": ["..."],
  "supplement_stack": [{{"name": "Vitamin D3", "dose": "5000 IU", "timing": "Morning with fat", "reason": "..."}}],
  "weekly_targets": {{"calories_avg": 0, "protein_g_avg": 0, "water_oz_daily": 0, "sleep_hours": 0, "workout_days": 0}},
  "notifications": [{{"label": "Morning Wake-Up", "time": "6:00 AM", "days": ["Monday"], "message": "Time to forge your best self!"}}],
  "disclaimer": "Not medical advice â consult your doctor before making health changes."
}}

Be extremely specific with foods, exercises, and times. Personalize every detail.
"""
    if health_data:
        prompt += f"\n\n## Real-Time Apple Health & Watch Data\nThe following was synced from the user's iPhone/Apple Watch seconds ago:\n{health_data}\n\nUse this data to personalize the plan: low HRV or high resting HR = add recovery. Sleep < 6h = reduce intensity. VO2 Max = calibrate cardio zones. High step count = already active baseline."
    if routine_data:
        prompt += f"\n\n## User's Weekly Routine & Lifestyle\nThe following describes how the user lives their life this week:\n{routine_data}\n\nSchedule workouts around their work days and commute. Respect their wake/bedtime for scheduling. Account for high-stress or energy-depleted weeks with reduced intensity. Keep appointment and travel days lighter."
    return prompt.strip()


def parse_schedule_response(raw: str) -> Dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"error": "Could not parse schedule JSON.", "raw": raw[:2000], "days": {}, "shopping_list": {}, "meal_prep_instructions": [], "supplement_stack": [], "notifications": []}
