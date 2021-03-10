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

import pathlib
from unittest import mock

import pytest

from craft_providers.multipass import MultipassInstallerError, multipass_installer

EXAMPLE_VERSION = """\
multipass  1.6.2
multipassd 1.6.2
"""


@mock.patch("pathlib.Path.exists", side_effect=[None, True])
@mock.patch(
    "craft_providers.util.path.which",
    side_effect=[None, pathlib.Path("/usr/local/bin/multipass")],
)
def test_install_darwin(mock_exists, mock_which, fake_process):
    fake_process.register_subprocess(["brew", "cask", "install", "multipass"])
    fake_process.register_subprocess(
        ["/usr/local/bin/multipass", "version"], stdout=EXAMPLE_VERSION
    )

    multipass_installer.install(platform="darwin")

    assert list(fake_process.calls) == [
        ["brew", "cask", "install", "multipass"],
        ["/usr/local/bin/multipass", "version"],
    ]


@mock.patch("pathlib.Path.exists", side_effect=[None, True])
@mock.patch(
    "craft_providers.util.path.which",
    side_effect=[None, pathlib.Path("/snap/bin/multipass")],
)
def test_install_linux(mock_exists, mock_which, fake_process):
    fake_process.register_subprocess(["sudo", "snap", "install", "multipass"])
    fake_process.register_subprocess(
        ["/snap/bin/multipass", "version"], stdout=EXAMPLE_VERSION
    )

    multipass_installer.install(platform="linux")

    assert list(fake_process.calls) == [
        ["sudo", "snap", "install", "multipass"],
        ["/snap/bin/multipass", "version"],
    ]


@mock.patch("pathlib.Path.exists", side_effect=[None, True])
@mock.patch(
    "craft_providers.util.path.which",
    side_effect=[None, pathlib.Path("/snap/bin/multipass")],
)
def test_install_windows(mock_exists, mock_which, fake_process):
    with pytest.raises(MultipassInstallerError) as exc_info:
        multipass_installer.install(platform="win32")

    assert str(exc_info.value) == (
        "Failed to install Multipass: Windows not yet supported.\n"
        "Please visit https://multipass.run/ for instructions on installing Multipass for your operating system."
    )
