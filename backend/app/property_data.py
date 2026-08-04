"""Chooses which property-data provider answers a lookup.

ATTOM was hard-wired into every call site, so adding a second provider meant
either duplicating the try/except at each one or putting the choice in one
place. This is that place: callers ask for property evidence and match on the
provider-neutral errors, and the returned dict is the same shape either way.

Preference order is deliberate. ATTOM stays first so existing deployments keep
their current provider without configuration changes; Smarty answers only when
ATTOM is absent, unless PROPERTY_DATA_PROVIDER names one explicitly.
"""

from __future__ import annotations

import os
from typing import Awaitable, Callable

from .attom_adapter import lookup_attom_property
from .provider_errors import PropertyDataConfigurationError, PropertyDataLookupError
from .smarty_adapter import lookup_smarty_property

__all__ = [
    "PROPERTY_DATA_CREDENTIALS",
    "PropertyDataConfigurationError",
    "PropertyDataLookupError",
    "configured_property_provider",
    "lookup_property",
    "property_data_configured",
]

Adapter = Callable[[str, str], Awaitable[dict]]

# Every variable a provider needs, so a half-configured provider is never
# mistaken for a usable one. Smarty needs two, which is precisely the case a
# flat any-of list of variable names would get wrong.
PROPERTY_DATA_CREDENTIALS: dict[str, tuple[str, ...]] = {
    "attom": ("ATTOM_API_KEY",),
    "smarty": ("SMARTY_AUTH_ID", "SMARTY_AUTH_TOKEN"),
}

_ADAPTERS: dict[str, Adapter] = {
    "attom": lookup_attom_property,
    "smarty": lookup_smarty_property,
}

_PREFERENCE = ("attom", "smarty")


def _configured(provider: str) -> bool:
    names = PROPERTY_DATA_CREDENTIALS.get(provider, ())
    return bool(names) and all((os.getenv(name) or "").strip() for name in names)


def property_data_configured() -> bool:
    """Whether a provider this build can actually call is fully configured.

    The readiness gates used to accept PROPSTREAM_API_KEY, which no adapter has
    ever implemented, so a PropStream-only deployment reported property data
    ready while every lookup failed. Deriving the gates from the adapters that
    exist keeps the claim and the capability in step; re-add a provider here the
    moment it has an adapter.
    """
    return any(_configured(provider) for provider in PROPERTY_DATA_CREDENTIALS)


def configured_property_provider() -> str | None:
    """The provider that can answer right now, or None.

    An explicit PROPERTY_DATA_PROVIDER is returned even when its credentials are
    missing, so the adapter raises a precise configuration error instead of this
    silently falling back to a provider the operator did not choose.
    """
    explicit = (os.getenv("PROPERTY_DATA_PROVIDER") or "").strip().lower()
    if explicit:
        return explicit
    for provider in _PREFERENCE:
        if _configured(provider):
            return provider
    return None


async def lookup_property(address1: str, address2: str) -> dict:
    provider = configured_property_provider()
    if provider is None:
        raise PropertyDataConfigurationError(
            "No property-data provider is configured. Set ATTOM_API_KEY, "
            "or SMARTY_AUTH_ID and SMARTY_AUTH_TOKEN."
        )
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise PropertyDataConfigurationError(
            f"PROPERTY_DATA_PROVIDER is set to '{provider}', which has no adapter. "
            f"Supported providers: {', '.join(sorted(_ADAPTERS))}."
        )
    return await adapter(address1, address2)
