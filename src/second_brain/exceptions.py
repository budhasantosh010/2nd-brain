"""Domain exceptions used by the Global Second Brain."""


class BrainError(Exception):
    """Base exception for expected brain failures."""


class ConfigurationError(BrainError):
    """Configuration is invalid or incomplete."""


class SecurityViolation(BrainError):
    """An operation violates security or egress policy."""


class IntegrityError(BrainError):
    """Canonical content failed an integrity check."""


class TransactionError(BrainError):
    """A canonical write transaction could not be safely completed."""


class UnsupportedSourceError(BrainError):
    """No parser is available for the supplied source."""
