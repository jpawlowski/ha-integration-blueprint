"""Every state a user can see has a translation, and every language file carries the same keys."""

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.ha_integration_domain.const import DOMAIN
from homeassistant.const import (
    ATTR_ASSUMED_STATE,
    ATTR_ATTRIBUTION,
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_PICTURE,
    ATTR_FRIENDLY_NAME,
    ATTR_ICON,
    ATTR_SUPPORTED_FEATURES,
    ATTR_UNIT_OF_MEASUREMENT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations

TRANSLATIONS = Path(__file__).parent.parent / "custom_components" / DOMAIN / "translations"

# Attributes every entity can carry; the frontend names them itself.
GENERIC_ATTRIBUTES = frozenset(
    {
        ATTR_ASSUMED_STATE,
        ATTR_ATTRIBUTION,
        ATTR_DEVICE_CLASS,
        ATTR_ENTITY_PICTURE,
        ATTR_FRIENDLY_NAME,
        ATTR_ICON,
        ATTR_SUPPORTED_FEATURES,
        ATTR_UNIT_OF_MEASUREMENT,
    }
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _key_paths(node: dict[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in node.items():
        path = f"{prefix}{key}"
        paths |= _key_paths(value, f"{path}.") if isinstance(value, dict) else {path}
    return paths


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_every_option_has_a_state_translation(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    init_integration: MockConfigEntry,
) -> None:
    """Each option of an enum sensor or a select is translated, so no raw code reaches the UI."""
    entity_translations = (await hass.async_add_executor_job(_load, TRANSLATIONS / "en.json")).get("entity", {})
    entries = er.async_entries_for_config_entry(entity_registry, init_integration.entry_id)
    checked = [
        (entry, option)
        for entry in entries
        if (state := hass.states.get(entry.entity_id)) is not None
        for option in state.attributes.get("options") or []
    ]

    missing = [
        f"entity.{entry.domain}.{entry.translation_key}.state.{option}"
        for entry, option in checked
        if option not in entity_translations.get(entry.domain, {}).get(entry.translation_key, {}).get("state", {})
    ]

    assert checked, "no entity with options was found — the test no longer checks anything"
    assert not missing, f"missing in en.json: {missing}"


async def _platform_attributes(hass: HomeAssistant, domains: set[str]) -> set[tuple[str, str]]:
    """Return the (domain, attribute) pairs Home Assistant's entity platforms translate themselves."""
    keys = await async_get_translations(hass, "en", "entity_component", domains)
    return {
        (key.split(".")[1], key.split(".")[-2]) for key in keys if ".state_attributes." in key and key.endswith(".name")
    }


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_every_attribute_has_a_display_name(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    init_integration: MockConfigEntry,
) -> None:
    """Each attribute the integration adds has a translated display name, not the raw key."""
    entity_translations = (await hass.async_add_executor_job(_load, TRANSLATIONS / "en.json")).get("entity", {})
    entries = er.async_entries_for_config_entry(entity_registry, init_integration.entry_id)
    platform_attributes = await _platform_attributes(hass, {entry.domain for entry in entries})

    missing = [
        f"entity.{entry.domain}.{entry.translation_key}.state_attributes.{attribute}.name"
        for entry in entries
        if (state := hass.states.get(entry.entity_id)) is not None
        for attribute in state.attributes
        if attribute not in GENERIC_ATTRIBUTES
        and (entry.domain, attribute) not in platform_attributes
        and "name"
        not in entity_translations.get(entry.domain, {})
        .get(entry.translation_key, {})
        .get("state_attributes", {})
        .get(attribute, {})
    ]

    assert not missing, f"missing in en.json: {missing}"


def test_language_files_carry_the_same_keys() -> None:
    """A language file neither lacks a key of en.json nor has one en.json does not."""
    reference = _key_paths(_load(TRANSLATIONS / "en.json"))

    differences = {
        path.name: {
            "missing": sorted(reference - keys),
            "extra": sorted(keys - reference),
        }
        for path in sorted(TRANSLATIONS.glob("*.json"))
        if (keys := _key_paths(_load(path))) != reference
    }

    assert not differences, json.dumps(differences, indent=2)
