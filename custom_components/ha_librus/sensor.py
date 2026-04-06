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
