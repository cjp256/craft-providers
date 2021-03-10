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

"""Multipass Instance."""
import io
import logging
import os
import pathlib
import subprocess
import sys
from typing import Any, Dict, List, Optional

from craft_providers.actions import linux

from .. import Executor
from .errors import MultipassError
from .multipass import Multipass

logger = logging.getLogger(__name__)


def _get_host_uid():
    if sys.platform == "win32":
        return 0
    else:
        return os.getuid()


def _get_host_gid():
    if sys.platform == "win32":
        return 0
    else:
        return os.getgid()


class MultipassInstance(Executor):
    """Multipass Instance Lifecycle.

    :param name: Name of multipass instance.
    """

    def __init__(
        self,
        *,
        name: str,
        multipass: Optional[Multipass] = None,
    ):
        super().__init__()

        self.name = name

        if multipass is not None:
            self._multipass = multipass
        else:
            self._multipass = Multipass()

    def create_file(
        self,
        *,
        destination: pathlib.Path,
        content: bytes,
        file_mode: str,
        group: str = "root",
        user: str = "root",
    ) -> None:
        """Create file with content and file mode.

        Multipass transfers data as "ubuntu" user, forcing us to first copy a
        file to a temporary location before moving to a (possibly) root-owned
        location and with appropriate permissions.

        :param destination: Path to file.
        :param content: Contents of file.
        :param file_mode: File mode string (e.g. '0644').
        :param group: File group owner/id.
        :param user: Filer usedr owner/id.
        """
        stream = io.BytesIO(content)

        tmp_file_path = "/".join(["/tmp", destination.as_posix().replace("/", "_")])

        self._multipass.transfer_source_io(
            source=stream,
            destination=f"{self.name}:{tmp_file_path}",
        )

        self.execute_run(
            ["sudo", "chown", f"{user}:{group}", tmp_file_path],
            check=True,
        )

        self.execute_run(
            ["sudo", "chmod", file_mode, tmp_file_path],
            check=True,
        )

        self.execute_run(
            ["sudo", "mv", tmp_file_path, destination.as_posix()],
            check=True,
        )

    def delete(self, purge: bool = True) -> None:
        """Delete instance.

        :param purge: Purge instances immediately.
        """
        return self._multipass.delete(
            instance_name=self.name,
            purge=purge,
        )

    def execute_popen(self, command: List[str], **kwargs) -> subprocess.Popen:
        """Execute process in instance using subprocess.Popen().

        :param command: Command to execute.
        :param kwargs: Additional keyword arguments for subprocess.Popen().

        :returns: Popen instance.
        """
        return self._multipass.exec(
            instance_name=self.name,
            command=self._formulate_command(
                command=command, env=kwargs.pop("env", None)
            ),
            runner=subprocess.Popen,
            **kwargs,
        )

    def execute_run(self, command: List[str], **kwargs) -> subprocess.CompletedProcess:
        """Execute command using subprocess.run().

        :param command: Command to execute.
        :param check: Raise exception on failure.
        :param kwargs: Keyword args to pass to subprocess.run().

        :returns: Completed process.

        :raises subprocess.CalledProcessError: if command fails and check is
            True.
        """
        return self._multipass.exec(
            instance_name=self.name,
            command=self._formulate_command(
                command=command, env=kwargs.pop("env", None)
            ),
            runner=subprocess.run,
            **kwargs,
        )

    def _formulate_command(
        self,
        *,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """Formulate command to run."""
        final_cmd = ["sudo", "-H", "--"]

        if env is not None:
            env_args = [f"{k}={v}" for k, v in env.items()]
            final_cmd += ["env", *env_args]

        final_cmd += command

        return final_cmd

    def exists(self) -> bool:
        """Check if instance exists.

        :returns: True if instance exists.
        """
        return self.get_info() is not None

    def get_info(self) -> Optional[Dict[str, Any]]:
        """Get configuration and state for instance.

        :returns: State information parsed from multipass if instance exists,
            else None.

        :raises MultipassError: If unable to parse VM info.
        """
        instance_config = self._multipass.info(instance_name=self.name)
        if instance_config is None:
            return None

        return instance_config.get("info", dict()).get(self.name)

    def is_mounted(self, *, host_source: pathlib.Path, target: pathlib.Path) -> bool:
        """Check if path is mounted at target.

        :param host_source: Host path to check.
        :param target: Instance path to check.

        :returns: True if host_source is mounted at target.
        """
        info = self.get_info()
        if info is None:
            raise MultipassError(brief=f"VM {self.name!r} was deleted.")

        mounts = info.get("mounts", dict())

        for mount_point, mount_config in mounts.items():
            if mount_point == target.as_posix() and mount_config.get(
                "source_path"
            ) == str(host_source):
                return True

        return False

    def is_running(self) -> bool:
        """Check if instance is running.

        :returns: True if instance is running.
        """
        info = self.get_info()
        if info is None:
            return False

        return info.get("state") == "Running"

    def launch(
        self,
        *,
        image: str,
        cpus: int = 2,
        disk_gb: int = 256,
        mem_gb: int = 2,
    ) -> None:
        """Launch instance.

        :param image: Name of image to create the instance with.
        :param instance_cpus: Number of CPUs.
        :param instance_disk_gb: Disk allocation in gigabytes.
        :param instance_mem_gb: Memory allocation in gigabytes.
        :param instance_name: Name of instance to use/create.
        :param instance_stop_time_mins: Stop time delay in minutes.
        """
        self._multipass.launch(
            instance_name=self.name,
            image=image,
            cpus=str(cpus),
            disk=f"{disk_gb!s}G",
            mem=f"{mem_gb!s}G",
        )

    def mount(
        self,
        *,
        host_source: pathlib.Path,
        target: pathlib.Path,
        host_uid: Optional[int] = None,
        host_gid: Optional[int] = None,
    ) -> None:
        """Mount host host_source directory to target mount point.

        Checks first to see if already mounted.

        :param host_source: Host path to mount.
        :param target: Instance path to mount to.
        """
        if self.is_mounted(host_source=host_source, target=target):
            return

        if host_uid is None:
            host_uid = _get_host_uid()

        uid_map = {str(host_uid): "0"}

        if host_gid is None:
            host_gid = _get_host_gid()

        gid_map = {str(host_gid): "0"}

        self._multipass.mount(
            source=host_source,
            target=f"{self.name}:{target.as_posix()}",
            uid_map=uid_map,
            gid_map=gid_map,
        )

    def pull_file(self, *, source: pathlib.Path, destination: pathlib.Path) -> None:
        """Copy a file from the environment to host.

        :param source: Environment file to copy.
        :param destination: Host file path to copy to.  Parent directory
            (destination.parent) must exist.

        :raises FileNotFoundError: If source file or destination's parent
            directory does not exist.
        :raises ProviderError: On error copying file.
        """
        logger.debug("Syncing env:%s -> host:%s...", source, destination)

        if not linux.is_target_file(executor=self, target=source):
            raise FileNotFoundError(f"File not found: {str(source)!r}")

        if not destination.parent.is_dir():
            raise FileNotFoundError(f"Directory not found: {str(destination.parent)!r}")

        self._multipass.transfer(
            source=f"{self.name}:{source!s}", destination=str(destination)
        )

    def push_file(self, *, source: pathlib.Path, destination: pathlib.Path) -> None:
        """Copy a file from the host into the environment.

        :param source: Host file to copy.
        :param destination: Target environment file path to copy to.  Parent
            directory (destination.parent) must exist.

        :raises FileNotFoundError: If source file or destination's parent
            directory does not exist.
        :raises ProviderError: On error copying file.
        """
        if not source.is_file():
            raise FileNotFoundError(f"File not found: {str(source)!r}")

        if not linux.is_target_directory(executor=self, target=destination.parent):
            raise FileNotFoundError(f"Directory not found: {str(destination.parent)!r}")

        self._multipass.transfer(
            source=str(source),
            destination=f"{self.name}:{destination!s}",
        )

    def start(self) -> None:
        """Start instance."""
        self._multipass.start(instance_name=self.name)

    def stop(self, delay_mins: int = 0) -> None:
        """Stop instance.

        :param delay_mins: Delay shutdown for specified minutes.
        """
        self._multipass.stop(instance_name=self.name, delay_mins=delay_mins)

    def supports_mount(self) -> bool:
        """Check if instance supports mounting from host.

        :returns: True if mount is supported.
        """
        return True
