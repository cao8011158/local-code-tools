"""Parcel workflow with a cross-module call and lexical owners."""

from delivery import BaseParcel, deliver_parcel


def dispatch_parcel():
    """Dispatch a parcel through the imported delivery function."""
    return deliver_parcel()


class Parcel(BaseParcel):
    """Parcel with one method and an explicit imported base."""

    def inspect(self):
        """Return a fixed inspection result."""
        return "parcel"
