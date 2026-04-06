"""DataUpdateCoordinator for Librus Synergia integration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.persistent_notification import async_create

from .api import LibrusAPI, LibrusApiError, LibrusAuthError
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


def _sanitize_entity_id(name: str) -> str:
    """Convert Polish subject name to a valid entity ID suffix."""
    replacements = {
        "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
        "ó": "o", "ś": "s", "ż": "z", "ź": "z",
        "Ą": "A", "Ć": "C", "Ę": "E", "Ł": "L", "Ń": "N",
        "Ó": "O", "Ś": "S", "Ż": "Z", "Ź": "Z",
    }
    result = name.lower()
    for pl_char, ascii_char in replacements.items():
        result = result.replace(pl_char, ascii_char)
    # Replace non-alphanumeric with underscore
    result = "".join(c if c.isalnum() else "_" for c in result)
    # Collapse multiple underscores, strip leading/trailing
    while "__" in result:
        result = result.replace("__", "_")
    return result.strip("_")


def _detect_semester(classes_data: dict[str, Any]) -> int:
    """Detect current semester from Classes API data."""
    try:
        class_info = classes_data.get("Class", {})
        end_first = class_info.get("EndFirstSemester")
        if end_first:
            end_date = datetime.strptime(end_first, "%Y-%m-%d").date()
            today = datetime.now().date()
            return 1 if today <= end_date else 2
    except (ValueError, KeyError, TypeError):
        pass
    return 2  # Default to semester 2


class LibrusData:
    """Processed Librus data."""

    def __init__(self) -> None:
        """Initialize."""
        self.student_name: str = ""
        self.student_id: str = ""  # Librus account Login (e.g. "7375597"), used in entity IDs
        self.student_class: str = ""
        self.semester: int = 2
        self.lucky_number: int | None = None
        self.lucky_number_date: str | None = None
        # Grades per subject, per semester: {subject_name: [grade_entries]}
        self.grades_sem1: dict[str, list[dict[str, Any]]] = {}
        self.grades_sem2: dict[str, list[dict[str, Any]]] = {}
        self.last_grade_date: str = ""
        self.last_grade_value: str = ""
        self.last_grade_subject: str = ""
        self.last_grade_category: str = ""
        self.subject_entity_map: dict[str, str] = {}  # subject_name -> entity_suffix
        self.announcements: list[dict[str, Any]] = []
        self.all_grade_ids: list[int] = []
        # Behaviour grades
        self.behaviour_sem1: str = ""  # e.g. "wzorowe"
        self.behaviour_sem2: str = ""
        self.behaviour_sem1_proposal: str = ""
        self.behaviour_sem2_proposal: str = ""


class LibrusCoordinator(DataUpdateCoordinator[LibrusData]):
    """Coordinator for fetching Librus data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: LibrusAPI,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name="Librus Synergia",
            update_interval=timedelta(minutes=scan_interval),
        )
        self.api = api
        self._previous_grade_ids: set[int] = set()
        self._first_run = True

    async def _async_update_data(self) -> LibrusData:
        """Fetch data from Librus API."""
        try:
            # Fetch all data in parallel
            results = await asyncio.gather(
                self.api.get_me(),
                self.api.get_grades(),
                self.api.get_subjects(),
                self.api.get_grade_categories(),
                self.api.get_grade_comments(),
                self.api.get_classes(),
                self.api.get_lucky_number(),
                self.api.get_school_notices(),
                self.api.get_behaviour_grades(),
                self.api.get_behaviour_types(),
                return_exceptions=True,
            )

            # Check for auth errors (fail hard)
            for r in results:
                if isinstance(r, LibrusAuthError):
                    raise UpdateFailed(f"Librus authentication failed: {r}") from r

            # Unpack results (treat API errors as empty data)
            me_data = results[0] if not isinstance(results[0], Exception) else {}
            grades_data = results[1] if not isinstance(results[1], Exception) else {}
            subjects_data = results[2] if not isinstance(results[2], Exception) else {}
            categories_data = results[3] if not isinstance(results[3], Exception) else {}
            comments_data = results[4] if not isinstance(results[4], Exception) else {}
            classes_data = results[5] if not isinstance(results[5], Exception) else {}
            lucky_data = results[6] if not isinstance(results[6], Exception) else {}
            notices_data = results[7] if not isinstance(results[7], Exception) else {}
            behaviour_data = results[8] if not isinstance(results[8], Exception) else {}
            behaviour_types = results[9] if not isinstance(results[9], Exception) else {}

            data = LibrusData()

            # Student info
            me = me_data.get("Me", {})
            account = me.get("Account", {})
            data.student_name = f"{account.get('FirstName', '')} {account.get('LastName', '')}".strip()
            data.student_id = str(account.get("Login", account.get("Id", "")))

            # Class info & semester
            class_info = classes_data.get("Class", {})
            class_number = class_info.get("Number", "")
            class_symbol = class_info.get("Symbol", "")
            data.student_class = f"{class_number}{class_symbol}"
            data.semester = _detect_semester(classes_data)

            # Build lookup maps
            subject_map: dict[int, str] = {}
            for s in subjects_data.get("Subjects", []):
                subject_map[s["Id"]] = s["Name"]

            category_map: dict[int, str] = {}
            for c in categories_data.get("Categories", []):
                category_map[c["Id"]] = c.get("Name", "")

            comment_map: dict[int, str] = {}
            for c in comments_data.get("Comments", []):
                comment_map[c["Id"]] = c.get("Text", "")

            # Process grades — both semesters
            grades_sem1: dict[str, list[dict[str, Any]]] = {}
            grades_sem2: dict[str, list[dict[str, Any]]] = {}
            all_grade_ids: list[int] = []
            last_date = "1970-01-01 00:00:00"
            last_grade = ""
            last_subject = ""
            last_category = ""

            for g in grades_data.get("Grades", []):
                sem = g.get("Semester", 0)
                sub_id = g.get("Subject", {}).get("Id")
                sub_name = subject_map.get(sub_id, "Nieznany")

                target = grades_sem1 if sem == 1 else grades_sem2
                if sub_name not in target:
                    target[sub_name] = []

                grade_str = str(g.get("Grade", ""))
                if g.get("IsConstituent") is False or g.get("IsSemester"):
                    grade_str = f"({grade_str})"
                if g.get("Improvement"):
                    grade_str = f"[{grade_str}]"

                cat_id = g.get("Category", {}).get("Id") if g.get("Category") else None
                cat_name = category_map.get(cat_id, "") if cat_id else ""

                comment_text = ""
                if g.get("Comments"):
                    first_comment_id = g["Comments"][0].get("Id")
                    if first_comment_id:
                        comment_text = comment_map.get(first_comment_id, "")

                grade_entry = {
                    "grade": grade_str,
                    "date": g.get("AddDate", ""),
                    "category": cat_name,
                    "comment": comment_text,
                    "id": g.get("Id"),
                    "semester": sem,
                }
                target[sub_name].append(grade_entry)
                all_grade_ids.append(g.get("Id"))

                add_date = g.get("AddDate", "")
                if add_date > last_date:
                    last_date = add_date
                    last_grade = str(g.get("Grade", ""))
                    last_subject = sub_name
                    last_category = cat_name

            data.grades_sem1 = grades_sem1
            data.grades_sem2 = grades_sem2
            data.all_grade_ids = all_grade_ids
            data.last_grade_date = last_date if last_date != "1970-01-01 00:00:00" else ""
            data.last_grade_value = last_grade
            data.last_grade_subject = last_subject
            data.last_grade_category = last_category

            # Entity suffix map — all subjects from both semesters
            all_subjects = set(grades_sem1.keys()) | set(grades_sem2.keys())
            for sub_name in all_subjects:
                data.subject_entity_map[sub_name] = _sanitize_entity_id(sub_name)

            # Behaviour grades
            btype_map: dict[str, str] = {}
            for bt in behaviour_types.get("Types", []):
                btype_map[str(bt["Id"])] = bt.get("Name", "")

            for bg in behaviour_data.get("Grades", []):
                sem = str(bg.get("Semester", ""))
                type_id = str(bg.get("GradeType", {}).get("Id", ""))
                grade_name = btype_map.get(type_id, "")
                is_proposal = str(bg.get("IsProposal", "0")) == "1"

                if sem == "1":
                    if is_proposal:
                        data.behaviour_sem1_proposal = grade_name
                    else:
                        data.behaviour_sem1 = grade_name
                elif sem == "2":
                    if is_proposal:
                        data.behaviour_sem2_proposal = grade_name
                    else:
                        data.behaviour_sem2 = grade_name

            # Lucky number
            lucky = lucky_data.get("LuckyNumber", {})
            data.lucky_number = lucky.get("LuckyNumber")
            data.lucky_number_date = lucky.get("LuckyNumberDay")

            # Announcements
            for notice in notices_data.get("SchoolNotices", []):
                data.announcements.append({
                    "subject": notice.get("Subject", ""),
                    "content": notice.get("Content", ""),
                    "date": notice.get("StartDate", ""),
                    "author": notice.get("AddedBy", {}).get("Id", ""),
                })

            # New grade detection & notification
            current_ids = set(all_grade_ids)
            if self._first_run:
                self._previous_grade_ids = current_ids
                self._first_run = False
            else:
                new_ids = current_ids - self._previous_grade_ids
                if new_ids:
                    self._send_new_grade_notifications(data, new_ids)
                self._previous_grade_ids = current_ids

            return data

        except LibrusAuthError as err:
            raise UpdateFailed(f"Librus auth failed: {err}") from err
        except LibrusApiError as err:
            raise UpdateFailed(f"Librus API error: {err}") from err
        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.exception("Unexpected error in Librus coordinator")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def _send_new_grade_notifications(
        self, data: LibrusData, new_ids: set[int]
    ) -> None:
        """Send HA persistent notifications for new grades."""
        notifications: list[str] = []
        # Check both semesters
        all_grades = {}
        for sub, grades in data.grades_sem1.items():
            all_grades.setdefault(sub, []).extend(grades)
        for sub, grades in data.grades_sem2.items():
            all_grades.setdefault(sub, []).extend(grades)
        for sub_name in sorted(all_grades.keys()):
            for g in all_grades[sub_name]:
                if g["id"] in new_ids:
                    line = f"{sub_name}: **{g['grade']}**"
                    if g["category"]:
                        line += f" ({g['category']})"
                    notifications.append(line)

        if notifications:
            count = len(notifications)
            title = (
                "Librus - nowa ocena"
                if count == 1
                else f"Librus - nowe oceny ({count})"
            )
            message = "\n".join(notifications)
            _LOGGER.info("New grades detected: %s", message)

            # Send persistent notification
            async_create(
                self.hass,
                message,
                title=title,
                notification_id=f"librus_new_grades_{int(datetime.now().timestamp())}",
            )

            # Fire event for automations
            self.hass.bus.async_fire(
                "librus_new_grade",
                {
                    "count": count,
                    "grades": notifications,
                    "title": title,
                    "message": message,
                },
            )
