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
#
"""LXD Errors."""
import subprocess
from typing import Optional

from craft_providers.errors import ProviderError, details_from_called_process_error


class LXDError(ProviderError):
    """Unexpected LXD error."""


class LXDInstallerError(LXDError):
    """LXD Installation Error.

    :param reason: Reason for install failure.
    :param error: Associated CalledProcessError, if available.
    """

    def __init__(
        self, reason: str, error: Optional[subprocess.CalledProcessError] = None
    ) -> None:
        brief = f"Failed to install LXD: {reason}"
        resolution = "Please visit https://linuxcontainers.org/lxd/getting-started-cli/#linux for instructions on installing LXD for your operating system."

        if error:
            details: Optional[str] = details_from_called_process_error(error)
        else:
            details = None

        super().__init__(brief=brief, details=details, resolution=resolution)
