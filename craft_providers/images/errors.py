# Copyright (C) 2021 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Image errors."""

from craft_providers.errors import ProviderError


class CompatibilityError(ProviderError):
    """Compatibility error.

    :param reason: Reason for incompatibility.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason

        brief = f"Incompatible image used: {reason}"
        resolution = "Clean incompatible image/instance and try again."

        super().__init__(brief=brief, resolution=resolution)

    def __repr__(self) -> str:
        """Return representation."""
        return f"CompatibilityError(reason={self.reason})"

    def __str__(self) -> str:
        """Return string representation."""
        return self.reason
