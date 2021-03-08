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

"""Craft provider errors."""
import shlex
import subprocess
from typing import Optional


def details_from_called_process_error(
    error: subprocess.CalledProcessError,
) -> str:
    """Create a consistent ProviderError from command errors.

    :param error: CalledProcessError.

    :returns: Details string.
    """
    cmd_string = shlex.join(error.cmd)
    details = [
        f"* Command that failed: {cmd_string}",
        f"* Command exit code: {error.returncode}",
    ]

    if error.stdout:
        details.append(f"* Command output: {error.stdout}")

    if error.stderr:
        details.append(f"* Command standard error output: {error.stderr}")

    return "\n".join(details)


class ProviderError(Exception):
    """Unexpected error.

    :param brief: Brief description of error.
    :param details: Detailed information.
    :param resolution: Recommendation, if any.
    """

    def __init__(
        self,
        brief: str,
        details: Optional[str] = None,
        resolution: Optional[str] = None,
    ):
        super().__init__()

        self.brief = brief
        self.details = details
        self.resolution = resolution

    def __str__(self) -> str:
        return self.brief

    @classmethod
    def from_called_process_error(
        cls,
        brief: str,
        error: subprocess.CalledProcessError,
        resolution: Optional[str] = None,
    ) -> "ProviderError":
        """Create a consistent ProviderError from command errors.

        :param brief: Brief description of error.
        :param error: CalledProcessError.
        :param resolution: Recommendation, if any.
        """
        details = details_from_called_process_error(error)

        return cls(brief=brief, details=details, resolution=resolution)
