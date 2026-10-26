"""Small synthetic source fixture. It contains no project code or real vectors."""


def base_weight(quantity=1):
    """Compute a synthetic weight for API-free integration tests."""
    return quantity * 2


class SyntheticBox:
    """Provide an explicit synthetic method/containment example."""

    def total(self, quantity):
        """Delegate a synthetic total to the local helper."""
        return base_weight(quantity)


def unchanged(value):
    """Return an unrelated value for incremental cache tests."""
    return value
