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

"""Multipass Provider."""

import logging
import shutil
import subprocess
import sys

from craft_providers.errors import details_from_called_process_error

from . import errors
from .multipass import Multipass

logger = logging.getLogger(__name__)


def install() -> str:
    """Install Multipass.

    :returns: Multipass version.

    :raises MultipassInstallationError: on error.
    """
    if sys.platform == "darwin":
        _install_darwin()
    elif sys.platform == "linux":
        _install_linux()
    elif sys.platform == "win32":
        _install_windows()
    else:
        raise errors.MultipassInstallationError(
            f"unsupported platform {sys.platform!r}"
        )

    multipass_version, _ = Multipass().wait_until_ready()
    return multipass_version


def _install_darwin() -> None:
    try:
        subprocess.run(["brew", "install", "multipass"], check=True)
    except subprocess.CalledProcessError as error:
        raise errors.MultipassInstallationError(
            "error during brew installation",
            details=details_from_called_process_error(error),
        ) from error


def _install_linux() -> None:
    try:
        subprocess.run(["sudo", "snap", "install", "multipass"], check=True)
    except subprocess.CalledProcessError as error:
        raise errors.MultipassInstallationError(
            "error during snap installation",
            details=details_from_called_process_error(error),
        ) from error


def _install_windows() -> None:
    raise errors.MultipassInstallationError(
        "automated installation not yet supported for Windows"
    )


def is_installed() -> bool:
    """Check if Multipass is installed (and found on PATH).

    :returns: Bool if multipass is installed.
    """
    return not shutil.which("multipass") is None
