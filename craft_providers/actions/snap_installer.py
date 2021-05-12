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

"""Helpers for snap commands."""

import contextlib
import logging
import pathlib
import shlex
import subprocess
import tempfile
import urllib.parse
from typing import Iterator

import requests
import requests_unixsocket  # type: ignore

from craft_providers import Executor
from craft_providers.errors import ProviderError, details_from_called_process_error

logger = logging.getLogger(__name__)


class SnapInstallationError(ProviderError):
    """Unexpected error during snap installation."""


@contextlib.contextmanager
def _temporary_directory() -> Iterator[pathlib.Path]:
    """Create temporary directory in home directory where Multipass has access."""
    with tempfile.TemporaryDirectory(
        suffix=".tmp-craft",
        dir=pathlib.Path.home(),
    ) as tmp_dir:
        yield pathlib.Path(tmp_dir)


@contextlib.contextmanager
def _temporary_file(name: str) -> Iterator[pathlib.Path]:
    """Create temporary directory in home directory where Multipass has access."""
    with _temporary_directory() as tmp_dir:
        yield tmp_dir / name


def _download_host_snap(
    *, snap_name: str, output: pathlib.Path, chunk_size: int = 64 * 1024
) -> None:
    """Download the current host snap using snapd's APIs."""
    name = urllib.parse.quote(snap_name, safe="")
    slug = f"snaps/{name}/file"
    url = f"http+unix://%2Frun%2Fsnapd.socket/v2/{slug}"
    try:
        resp = requests_unixsocket.get(url)
    except requests.exceptions.ConnectionError as error:
        raise SnapInstallationError(
            brief="Unable to connect to snapd service."
        ) from error

    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as error:
        raise SnapInstallationError(
            brief=f"Unable to download snap {snap_name!r} from snapd."
        ) from error

    with output.open("wb") as stream:
        for chunk in resp.iter_content(chunk_size):
            stream.write(chunk)


def _pack_host_snap(*, snap_name: str, output: pathlib.Path) -> None:
    """Pack the current host snap."""
    cmd = [
        "snap",
        "pack",
        f"/snap/{snap_name}/current/",
        f"--filename={output.as_posix()}",
    ]

    logger.debug("Executing command on host: %s", shlex.join(cmd))
    subprocess.run(
        cmd,
        capture_output=True,
        check=True,
    )


@contextlib.contextmanager
def _get_host_snap(snap_name: str) -> Iterator[pathlib.Path]:
    """Get snap installed on host.

    Snapd provides an API to fetch a snap. First use that to fetch a snap.
    If the snap is installed using `snap try`, it may fail to download. In
    that case, attempt to construct the snap by packing it ourselves.

    :yields: Path to snap which will be cleaned up afterwards.
    """
    with _temporary_file(f"{snap_name}.snap") as snap_path:
        try:
            _download_host_snap(snap_name=snap_name, output=snap_path)
        except SnapInstallationError:
            logger.warning(
                "Failed to fetch snap from snapd, falling back to `snap pack` to recreate."
            )
            _pack_host_snap(snap_name=snap_name, output=snap_path)

        yield snap_path


def inject_from_host(executor: Executor, snap_name: str) -> None:
    """Inject snap from host snap.

    :raises SnapInstallationError: on unexpected error.
    """
    target_snap_path = f"/tmp/{snap_name}.snap"

    try:
        # Clean outdated snap, if exists.
        executor.execute_run(
            ["rm", "-f", target_snap_path],
            check=True,
            capture_output=True,
        )

        with _get_host_snap(snap_name) as host_snap_path:
            executor.push_file(
                source=host_snap_path,
                destination=pathlib.Path(target_snap_path),
            )

        executor.execute_run(
            ["snap", "install", "--dangerous", "--classic", target_snap_path],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as error:
        raise SnapInstallationError(
            brief=f"Failed to inject snap {snap_name!r}.",
            details=details_from_called_process_error(error),
        ) from error
    except ProviderError as error:
        raise SnapInstallationError(
            brief=f"Failed to inject snap {snap_name!r}.",
        ) from error


def install_from_store(
    *,
    executor: Executor,
    snap_name: str,
    channel: str,
    classic: bool,
) -> None:
    """Install snap from store into target.

    Perform installation using method which prevents refreshing.

    :param executor: Executor for target.
    :param snap_name: Name of snap to install.
    :param channel: Channel to install from.
    :param classic: Install in classic mode.

    :raises SnapInstallationError: on unexpected error.
    """
    try:
        executor.execute_run(
            [
                "snap",
                "download",
                snap_name,
                f"--channel={channel}",
                f"--basename={snap_name}",
                "--target-directory=/tmp",
            ],
            check=True,
            capture_output=True,
        )

        install_cmd = ["snap", "install", f"/tmp/{snap_name}.snap", "--dangerous"]
        if classic:
            install_cmd.append("--classic")

        executor.execute_run(
            install_cmd,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as error:
        raise SnapInstallationError(
            brief=f"Failed to install snap {snap_name!r}.",
            details=details_from_called_process_error(error),
        ) from error