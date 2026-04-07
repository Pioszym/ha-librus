"""Sensor platform for Librus Synergia integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from datetime import datetime, timedelta

from .coordinator import LibrusCoordinator, LibrusData, _sanitize_entity_id

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Librus sensors from a config entry."""
    coordinator: LibrusCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Track which subject sensors already exist
    known_subjects: set[str] = set()

    @callback
    def _async_add_new_sensors() -> None:
        """Add sensors for any new subjects discovered."""
        if coordinator.data is None:
            return

        new_entities: list[SensorEntity] = []
        all_subjects = set(coordinator.data.grades_sem1.keys()) | set(
            coordinator.data.grades_sem2.keys()
        )
        for subject_name in all_subjects:
            if subject_name not in known_subjects:
                known_subjects.add(subject_name)
                new_entities.append(
                    LibrusSubjectSensor(coordinator, subject_name, entry)
                )

        if new_entities:
            _LOGGER.debug("Adding %d new Librus subject sensors", len(new_entities))
            async_add_entities(new_entities)

    # Static sensors - always present
    entities: list[SensorEntity] = [
        LibrusStudentSensor(coordinator, entry),
        LibrusAllGradesSensor(coordinator, entry),
        LibrusLastGradeSensor(coordinator, entry),
        LibrusLuckyNumberSensor(coordinator, entry),
        LibrusBehaviourSensor(coordinator, entry),
        LibrusConferenceSensor(coordinator, entry),
        LibrusHomeworksSensor(coordinator, entry),
        LibrusFreeDaysSensor(coordinator, entry),
        LibrusSubstitutionsSensor(coordinator, entry),
        LibrusTimetableSensor(coordinator, entry),
    ]
    async_add_entities(entities)

    # Initial subject sensors
    _async_add_new_sensors()

    # Listen for updates to add new subject sensors dynamically
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_sensors))


class LibrusBaseSensor(CoordinatorEntity[LibrusCoordinator], SensorEntity):
    """Base class for Librus sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: LibrusCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str = "mdi:school",
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        # Use student_id in unique_id to avoid collisions between children
        student_id = ""
        if coordinator.data and coordinator.data.student_id:
            student_id = coordinator.data.student_id
        self._student_id = student_id
        self._attr_unique_id = (
            f"librus_{student_id}_{key}" if student_id else f"{entry.entry_id}_{key}"
        )
        self._attr_name = name
        self._attr_icon = icon
        self._entry = entry


class LibrusStudentSensor(LibrusBaseSensor):
    """Sensor showing student info."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator, entry, "student", f"Librus {sid} - Uczen", "mdi:account-school"
        )

    @property
    def native_value(self) -> str | None:
        """Return student name."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.student_name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if self.coordinator.data is None:
            return {}
        return {
            "klasa": self.coordinator.data.student_class,
            "semestr": self.coordinator.data.semester,
        }


class LibrusAllGradesSensor(LibrusBaseSensor):
    """Sensor showing all grades summary — both semesters."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator,
            entry,
            "all_grades",
            f"Librus {sid} - Oceny wszystkie",
            "mdi:format-list-bulleted",
        )

    @property
    def native_value(self) -> str | None:
        """Return current semester subject count."""
        if self.coordinator.data is None:
            return None
        d = self.coordinator.data
        sem = d.grades_sem2 if d.semester == 2 else d.grades_sem1
        count = len(sem)
        return f"Semestr {d.semester}: {count} przedmiotow"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return grades per subject per semester as attributes."""
        if self.coordinator.data is None:
            return {}
        d = self.coordinator.data
        attrs: dict[str, Any] = {"semestr": d.semester}

        # All subjects from both semesters
        all_subjects = sorted(set(d.grades_sem1.keys()) | set(d.grades_sem2.keys()))

        for sub_name in all_subjects:
            sem1_grades = d.grades_sem1.get(sub_name, [])
            sem2_grades = d.grades_sem2.get(sub_name, [])
            s1 = " ".join(g["grade"] for g in sem1_grades) if sem1_grades else "-"
            s2 = " ".join(g["grade"] for g in sem2_grades) if sem2_grades else "-"
            attrs[sub_name] = f"I: {s1} | II: {s2}"

        return attrs


class LibrusLastGradeSensor(LibrusBaseSensor):
    """Sensor showing the most recent grade."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator,
            entry,
            "last_grade",
            f"Librus {sid} - Ostatnia ocena",
            "mdi:star",
        )

    @property
    def native_value(self) -> str | None:
        """Return last grade info."""
        if self.coordinator.data is None:
            return None
        d = self.coordinator.data
        if not d.last_grade_value:
            return None
        return f"{d.last_grade_date} {d.last_grade_subject} {d.last_grade_value}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of last grade."""
        if self.coordinator.data is None:
            return {}
        d = self.coordinator.data
        return {
            "data": d.last_grade_date,
            "ocena": d.last_grade_value,
            "przedmiot": d.last_grade_subject,
            "kategoria": d.last_grade_category,
        }


class LibrusLuckyNumberSensor(LibrusBaseSensor):
    """Sensor showing today's lucky number."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator,
            entry,
            "lucky_number",
            f"Librus {sid} - Szczesliwy numerek",
            "mdi:clover",
        )

    @property
    def native_value(self) -> int | None:
        """Return lucky number."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.lucky_number

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return date of lucky number."""
        if self.coordinator.data is None:
            return {}
        return {
            "data": self.coordinator.data.lucky_number_date,
        }


class LibrusBehaviourSensor(LibrusBaseSensor):
    """Sensor showing behaviour/conduct grade."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator,
            entry,
            "behaviour",
            f"Librus {sid} - Zachowanie",
            "mdi:account-check",
        )

    @property
    def native_value(self) -> str | None:
        """Return current semester behaviour grade."""
        if self.coordinator.data is None:
            return None
        d = self.coordinator.data
        current = d.behaviour_sem2 if d.semester == 2 else d.behaviour_sem1
        if not current:
            # Fall back to proposal
            current = (
                d.behaviour_sem2_proposal
                if d.semester == 2
                else d.behaviour_sem1_proposal
            )
        return current or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return behaviour details for both semesters."""
        if self.coordinator.data is None:
            return {}
        d = self.coordinator.data
        return {
            "semestr_1": d.behaviour_sem1 or d.behaviour_sem1_proposal or "-",
            "semestr_1_propozycja": d.behaviour_sem1_proposal or "-",
            "semestr_2": d.behaviour_sem2 or d.behaviour_sem2_proposal or "-",
            "semestr_2_propozycja": d.behaviour_sem2_proposal or "-",
        }


class LibrusSubjectSensor(LibrusBaseSensor):
    """Dynamic per-subject grade sensor — shows both semesters."""

    def __init__(
        self,
        coordinator: LibrusCoordinator,
        subject_name: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        entity_suffix = _sanitize_entity_id(subject_name)
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator,
            entry,
            f"grades_{entity_suffix}",
            f"Librus {sid} - {subject_name}",
            "mdi:school",
        )
        self._subject_name = subject_name

    @property
    def native_value(self) -> str | None:
        """Return current semester grades for this subject."""
        if self.coordinator.data is None:
            return None
        d = self.coordinator.data
        current = d.grades_sem2 if d.semester == 2 else d.grades_sem1
        grades = current.get(self._subject_name, [])
        if not grades:
            return "Brak ocen"
        return " ".join(g["grade"] for g in grades)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return grade details for both semesters."""
        if self.coordinator.data is None:
            return {}
        d = self.coordinator.data
        sem1 = d.grades_sem1.get(self._subject_name, [])
        sem2 = d.grades_sem2.get(self._subject_name, [])

        s1_str = " ".join(g["grade"] for g in sem1) if sem1 else "Brak ocen"
        s2_str = " ".join(g["grade"] for g in sem2) if sem2 else "Brak ocen"

        # Last grade from any semester
        all_grades = sem1 + sem2
        last = all_grades[-1] if all_grades else None

        attrs: dict[str, Any] = {
            "przedmiot": self._subject_name,
            "semestr_1": s1_str,
            "semestr_2": s2_str,
            "liczba_ocen_sem1": len(sem1),
            "liczba_ocen_sem2": len(sem2),
        }
        if last:
            attrs["ostatnia_ocena"] = last["grade"]
            attrs["data_ostatniej"] = last["date"]
            attrs["kategoria"] = last["category"]

        return attrs


class LibrusConferenceSensor(LibrusBaseSensor):
    """Sensor showing next parent-teacher conference (zebranie/wywiadówka)."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator,
            entry,
            "conference",
            f"Librus {sid} - Zebranie",
            "mdi:account-group",
        )

    @property
    def native_value(self) -> str | None:
        """Return next conference date or 'Brak'."""
        if self.coordinator.data is None:
            return None
        conf = self.coordinator.data.next_conference
        if not conf:
            return "Brak"
        date = conf.get("date", "")
        time = conf.get("time", "")
        return f"{date} {time}".strip() if date else "Brak"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return conference details."""
        if self.coordinator.data is None:
            return {}
        d = self.coordinator.data
        attrs: dict[str, Any] = {}

        # Next conference details
        if d.next_conference:
            attrs["temat"] = d.next_conference.get("topic", "")
            attrs["data"] = d.next_conference.get("date", "")
            attrs["godzina"] = d.next_conference.get("time", "")
            attrs["miejsce"] = d.next_conference.get("place", "")

        # All conferences
        attrs["liczba_zebran"] = len(d.conferences)
        for i, conf in enumerate(d.conferences, 1):
            date = conf.get("date", "")
            topic = conf.get("topic", "")
            attrs[f"zebranie_{i}"] = f"{date} - {topic}" if topic else date

        return attrs


class LibrusHomeworksSensor(LibrusBaseSensor):
    """Sensor showing upcoming homework assignments (sprawdziany, kartkówki)."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator,
            entry,
            "homeworks",
            f"Librus {sid} - Sprawdziany",
            "mdi:clipboard-text",
        )

    @property
    def native_value(self) -> str | None:
        """Return count of upcoming homeworks."""
        if self.coordinator.data is None:
            return None
        count = len(self.coordinator.data.homeworks)
        if count == 0:
            return "Brak"
        return f"{count} nadchodzacych"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return homework details as attributes."""
        if self.coordinator.data is None:
            return {}
        d = self.coordinator.data
        attrs: dict[str, Any] = {
            "liczba": len(d.homeworks),
            # JSON list for n8n to parse
            "items": d.homeworks,
        }
        # Also human-readable list
        for i, hw in enumerate(d.homeworks[:20], 1):
            time_str = hw.get("hour_from", "")
            if time_str:
                time_str = f" {time_str}"
            attrs[f"sprawdzian_{i}"] = (
                f"{hw['date']}{time_str} - {hw['subject']}: {hw['content'][:100]}"
            )
        return attrs


class LibrusFreeDaysSensor(LibrusBaseSensor):
    """Sensor showing school free days."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator,
            entry,
            "free_days",
            f"Librus {sid} - Dni wolne",
            "mdi:calendar-remove",
        )

    @property
    def native_value(self) -> str | None:
        """Return count of free days."""
        if self.coordinator.data is None:
            return None
        count = len(self.coordinator.data.free_days)
        return f"{count} dni wolnych"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return free days details."""
        if self.coordinator.data is None:
            return {}
        d = self.coordinator.data
        attrs: dict[str, Any] = {
            "liczba": len(d.free_days),
            "items": d.free_days,
        }
        for i, fd in enumerate(d.free_days, 1):
            date_range = fd["date_from"]
            if fd["date_to"] != fd["date_from"]:
                date_range += f" - {fd['date_to']}"
            attrs[f"wolne_{i}"] = f"{date_range}: {fd['name']}"
        return attrs


class LibrusSubstitutionsSensor(LibrusBaseSensor):
    """Sensor showing lesson substitutions and cancellations."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator,
            entry,
            "substitutions",
            f"Librus {sid} - Zastepstwa",
            "mdi:swap-horizontal",
        )

    @property
    def native_value(self) -> str | None:
        """Return count of upcoming substitutions."""
        if self.coordinator.data is None:
            return None
        count = len(self.coordinator.data.substitutions)
        if count == 0:
            return "Brak"
        return f"{count} zmian"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return substitution details."""
        if self.coordinator.data is None:
            return {}
        d = self.coordinator.data
        attrs: dict[str, Any] = {
            "liczba": len(d.substitutions),
            "items": d.substitutions,
        }
        for i, sub in enumerate(d.substitutions[:20], 1):
            time_str = sub.get("hour_from", "")
            if time_str:
                time_str = f" {time_str}"
            if sub["is_cancelled"]:
                label = f"ODWOLANA {sub['org_subject']}"
            elif sub["new_subject"] and sub["new_subject"] != sub["org_subject"]:
                label = f"{sub['org_subject']} -> {sub['new_subject']}"
            else:
                label = f"Zastepstwo {sub['org_subject']}"
            if sub.get("note"):
                label += f" ({sub['note']})"
            attrs[f"zmiana_{i}"] = f"{sub['date']}{time_str} - {label}"
        return attrs


class LibrusTimetableSensor(LibrusBaseSensor):
    """Sensor showing base timetable (plan lekcji) from TimetableEntries."""

    # Day names for attributes
    _DAY_NAMES = ["poniedzialek", "wtorek", "sroda", "czwartek", "piatek"]

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        sid = coordinator.data.student_id if coordinator.data else ""
        super().__init__(
            coordinator,
            entry,
            "timetable",
            f"Librus {sid} - Plan lekcji",
            "mdi:calendar-clock",
        )

    def _get_weekday_lessons(self, weekday: int) -> list[dict[str, Any]]:
        """Get sorted lessons for a weekday (0=Mon) from base timetable."""
        if self.coordinator.data is None:
            return []
        day = self.coordinator.data.base_timetable.get(weekday, {})
        lessons = []
        for lno in sorted(day.keys(), key=lambda x: int(x) if x.isdigit() else 99):
            tt = day[lno]
            if not tt.get("subject"):
                continue
            lessons.append({
                "nr": lno,
                "subject": tt["subject"],
                "hour_from": tt.get("hour_from", ""),
                "hour_to": tt.get("hour_to", ""),
                "teacher": tt.get("teacher", ""),
                "classroom": tt.get("classroom", ""),
            })
        return lessons

    def _get_day_lessons_with_overrides(self, date_str: str, weekday: int) -> list[dict[str, Any]]:
        """Get lessons for a date: use Timetables (current week) if available, else base."""
        if self.coordinator.data is None:
            return []
        # Current week data has real-time info (cancellations, substitutions)
        day = self.coordinator.data.timetable.get(date_str)
        if day:
            lessons = []
            for lno in sorted(day.keys(), key=lambda x: int(x) if x.isdigit() else 99):
                tt = day[lno]
                if not tt.get("subject"):
                    continue
                lessons.append({
                    "nr": lno,
                    "subject": tt["subject"],
                    "hour_from": tt.get("hour_from", ""),
                    "hour_to": tt.get("hour_to", ""),
                    "teacher": tt.get("teacher", ""),
                    "classroom": tt.get("classroom", ""),
                    "is_canceled": tt.get("is_canceled", False),
                })
            return lessons
        # Fallback to base timetable
        return self._get_weekday_lessons(weekday)

    @property
    def native_value(self) -> str | None:
        """Return today's lesson count."""
        if self.coordinator.data is None:
            return None
        today = datetime.now()
        lessons = self._get_day_lessons_with_overrides(
            today.strftime("%Y-%m-%d"), today.weekday()
        )
        active = [l for l in lessons if not l.get("is_canceled")]
        if not active:
            return "Brak zajec"
        return f"{len(active)} lekcji"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full weekly timetable + today/tomorrow details."""
        if self.coordinator.data is None:
            return {}
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        tomorrow = today + timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")

        today_lessons = self._get_day_lessons_with_overrides(today_str, today.weekday())
        tomorrow_lessons = self._get_day_lessons_with_overrides(tomorrow_str, tomorrow.weekday())

        attrs: dict[str, Any] = {
            "dzisiaj": today_str,
            "jutro": tomorrow_str,
            "lekcje_dzisiaj": len([l for l in today_lessons if not l.get("is_canceled")]),
            "lekcje_jutro": len([l for l in tomorrow_lessons if not l.get("is_canceled")]),
            "items_dzisiaj": today_lessons,
            "items_jutro": tomorrow_lessons,
        }

        # Human-readable today's lessons
        for i, l in enumerate(today_lessons, 1):
            canceled = " [ODWOLANA]" if l.get("is_canceled") else ""
            room = f" s.{l['classroom']}" if l.get("classroom") else ""
            attrs[f"lekcja_{i}"] = (
                f"{l['hour_from']}-{l['hour_to']} {l['subject']}"
                f" ({l['teacher']}){room}{canceled}"
            )

        # Full weekly base timetable (Mon-Fri)
        for wd in range(5):
            day_name = self._DAY_NAMES[wd]
            day_lessons = self._get_weekday_lessons(wd)
            attrs[f"items_{day_name}"] = day_lessons
            summary = []
            for l in day_lessons:
                summary.append(f"{l['nr']}. {l['hour_from']}-{l['hour_to']} {l['subject']}")
            if summary:
                attrs[day_name] = " | ".join(summary)

        return attrs
