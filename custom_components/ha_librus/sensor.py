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
        for subject_name in coordinator.data.grades_by_subject:
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
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._entry = entry


class LibrusStudentSensor(LibrusBaseSensor):
    """Sensor showing student info."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, "student", "Librus - Uczen", "mdi:account-school")

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
    """Sensor showing all grades summary."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(
            coordinator, entry, "all_grades", "Librus - Oceny wszystkie", "mdi:format-list-bulleted"
        )

    @property
    def native_value(self) -> str | None:
        """Return all grades text."""
        if self.coordinator.data is None:
            return None
        text = self.coordinator.data.all_grades_text
        # HA state max 255 chars - truncate if needed
        if len(text) > 255:
            return text[:252] + "..."
        return text

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full grades as attribute (no limit)."""
        if self.coordinator.data is None:
            return {}
        attrs: dict[str, Any] = {
            "pelne_oceny": self.coordinator.data.all_grades_text,
            "semestr": self.coordinator.data.semester,
        }
        # Add per-subject grade strings as attributes
        for sub_name, grades in self.coordinator.data.grades_by_subject.items():
            grade_str = " ".join(g["grade"] for g in grades)
            attrs[sub_name] = grade_str
        return attrs


class LibrusLastGradeSensor(LibrusBaseSensor):
    """Sensor showing the most recent grade."""

    def __init__(self, coordinator: LibrusCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(
            coordinator, entry, "last_grade", "Librus - Ostatnia ocena", "mdi:star"
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
        super().__init__(
            coordinator, entry, "lucky_number", "Librus - Szczesliwy numerek", "mdi:clover"
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


class LibrusSubjectSensor(LibrusBaseSensor):
    """Dynamic per-subject grade sensor."""

    def __init__(
        self,
        coordinator: LibrusCoordinator,
        subject_name: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        entity_suffix = _sanitize_entity_id(subject_name)
        super().__init__(
            coordinator,
            entry,
            f"grades_{entity_suffix}",
            f"Librus - {subject_name}",
            "mdi:school",
        )
        self._subject_name = subject_name

    @property
    def native_value(self) -> str | None:
        """Return grades for this subject."""
        if self.coordinator.data is None:
            return None
        grades = self.coordinator.data.grades_by_subject.get(self._subject_name, [])
        if not grades:
            return None
        return " ".join(g["grade"] for g in grades)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional grade details."""
        if self.coordinator.data is None:
            return {}
        grades = self.coordinator.data.grades_by_subject.get(self._subject_name, [])
        if not grades:
            return {}
        last = grades[-1]
        return {
            "przedmiot": self._subject_name,
            "ostatnia_ocena": last["grade"],
            "data_ostatniej": last["date"],
            "kategoria": last["category"],
            "liczba_ocen": len(grades),
            "icon": "mdi:school",
        }
