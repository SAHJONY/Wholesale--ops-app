"""Shared error types for property-data providers.

ATTOM was the only property-data provider, so its two error classes doubled as
the vocabulary every caller matched on. A second provider means callers should
not have to know which one answered, so both adapters raise these instead and
keep their provider-specific subclasses for logging and tests.
"""

from __future__ import annotations


class PropertyDataConfigurationError(RuntimeError):
    """Credentials are missing or the provider rejected them.

    Distinct from a lookup failure because it is fixed by configuration rather
    than by retrying, and callers map it to 503 rather than 502.
    """


class PropertyDataLookupError(RuntimeError):
    """The provider was reachable and authenticated but produced no usable answer."""
