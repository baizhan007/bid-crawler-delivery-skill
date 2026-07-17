"""Domain-specific errors used by the CLI."""


class FactoryError(RuntimeError):
    """A user-actionable crawler factory error."""


class FixtureError(FactoryError):
    """A fixture bundle is missing data or has an invalid shape."""


class NetworkAccessBlocked(FactoryError):
    """Replay code attempted to access the network."""


class ValidationFailed(FactoryError):
    """Validation completed and found acceptance failures."""
