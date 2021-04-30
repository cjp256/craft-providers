# Copyright 2021 Canonical Ltd.
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
import dataclasses
import shlex
import subprocess
from typing import List, Optional, Type, Union


def details_from_command_error(
    *,
    cmd: List[str],
    returncode: int,
    stdout: Optional[Union[bytes, str]] = None,
    stderr: Optional[Union[bytes, str]] = None,
) -> str:
    """Create a consistent ProviderError from command errors.

    stdout and stderr, if provided, will be stringified using its object
    representation.  This method does not decode byte strings.

    :param cmd: Command executed.
    :param returncode: Command exit code.
    :param stdout: Optional stdout to include.
    :param stderr: Optional stderr to include.

    :returns: Details string.
    """
    cmd_string = shlex.join(cmd)

    details = [
        f"* Command that failed: {cmd_string!r}",
        f"* Command exit code: {returncode}",
    ]

    if stdout:
        details.append(f"* Command output: {stdout!r}")

    if stderr:
        details.append(f"* Command standard error output: {stderr!r}")

    return "\n".join(details)


def details_from_called_process_error(
    error: subprocess.CalledProcessError,
) -> str:
    """Create a consistent ProviderError from command errors.

    :param error: CalledProcessError.

    :returns: Details string.
    """
    return details_from_command_error(
        cmd=error.cmd,
        stdout=error.stdout,
        stderr=error.stderr,
        returncode=error.returncode,
    )


def _fix_dataclass_init_docs(cls: Type) -> Type:
    """Temporary fix until sphinx autodoc supports dataclasses.

    :param cls: The class whose docstring needs fixing
    :returns: The class that was passed so this function can be used as a decorator

    .. seealso:: https://github.com/agronholm/sphinx-autodoc-typehints/issues/123
    """
    cls.__init__.__qualname__ = f"{cls.__name__}.__init__"
    return cls


@_fix_dataclass_init_docs
@dataclasses.dataclass
class ProviderError(Exception):
    """Unexpected error.

    :param brief: Brief description of error.
    :param details: Detailed information.
    :param resolution: Recommendation, if any.
    """

    brief: str
    details: Optional[str] = None
    resolution: Optional[str] = None

    def __str__(self) -> str:
        parts = [self.brief]

        if self.details:
            parts.append(self.details)

        if self.resolution:
            parts.append(self.resolution)

        return "\n".join(parts)
