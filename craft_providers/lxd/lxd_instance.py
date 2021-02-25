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

"""LXD Instance."""
import logging
import os
import pathlib
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from craft_providers import actions

from .. import Executor
from .lxc import LXC

logger = logging.getLogger(__name__)


class LXDInstance(Executor):
    """LXD Instance Lifecycle."""

    def __init__(
        self,
        *,
        name: str,
        project: str = "default",
        remote: str = "local",
        lxc: Optional[LXC] = None,
    ):
        super().__init__()

        self.name = name
        self.project = project
        self.remote = remote
        if lxc is None:
            self.lxc = LXC()
        else:
            self.lxc = lxc

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

        :param destination: Path to file.
        :param content: Contents of file.
        :param file_mode: File mode string (e.g. '0644').
        :param group: File owner group ID.
        :param user: Filer owner user ID.
        """
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(content)
            temp_file.flush()

        self.lxc.file_push(
            instance_name=self.name,
            source=pathlib.Path(temp_file.name),
            destination=destination,
            mode=file_mode,
            project=self.project,
            remote=self.remote,
        )

        # We don't use gid/uid for file_push() in case we don't know the
        # user/group IDs in advance.  Just chown it.
        self.execute_run(
            ["chown", f"{user}:{group}", destination.as_posix()],
            check=True,
        )

        os.unlink(temp_file.name)

    def delete(self, force: bool = True) -> None:
        """Delete instance.

        :param force: Delete even if running.
        """
        return self.lxc.delete(
            instance_name=self.name,
            project=self.project,
            remote=self.remote,
            force=force,
        )

    def execute_popen(self, command: List[str], **kwargs) -> subprocess.Popen:
        """Execute process in instance using subprocess.Popen().

        :param command: Command to execute.
        :param kwargs: Additional keyword arguments for subprocess.Popen().

        :returns: Popen instance.
        """
        return self.lxc.exec(
            instance_name=self.name,
            command=self._formulate_command(
                command=command, env=kwargs.pop("env", None)
            ),
            project=self.project,
            remote=self.remote,
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
        return self.lxc.exec(
            instance_name=self.name,
            command=self._formulate_command(
                command=command, env=kwargs.pop("env", None)
            ),
            project=self.project,
            remote=self.remote,
            runner=subprocess.run,
            **kwargs,
        )

    def exists(self) -> bool:
        """Check if instance exists.

        :returns: True if instance exists.
        """
        return self.get_state() is not None

    def _formulate_command(
        self,
        *,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """Formulate command to run."""
        final_cmd = []

        if env is not None:
            env_args = [f"{k}={v}" for k, v in env.items()]
            final_cmd += ["env", *env_args]

        final_cmd += command

        return final_cmd

    def get_state(self) -> Optional[Dict[str, Any]]:
        """Get state configuration for instance.

        :returns: State information parsed from lxc if instance exists, else
            None.
        """
        instances = self.lxc.list(
            instance_name=self.name, project=self.project, remote=self.remote
        )

        # lxc returns a filter instances starting with instance name rather
        # than the exact instance.  Find the exact match...
        for instance in instances:
            if instance["name"] == self.name:
                return instance

        return None

    def is_mounted(self, *, host_source: pathlib.Path, target: pathlib.Path) -> bool:
        """Check if path is mounted at target.

        :param host_source: Host path to check.
        :param target: Instance path to check.

        :returns: True if host_source is mounted at target.
        """
        devices = self.lxc.config_device_show(
            instance_name=self.name, project=self.project, remote=self.remote
        )
        disks = [d for d in devices.values() if d.get("type") == "disk"]

        return any(
            disk.get("path") == target.as_posix()
            and disk.get("source") == host_source.as_posix()
            for disk in disks
        )

    def is_running(self) -> bool:
        """Check if instance is running.

        :returns: True if instance is running.
        """
        state = self.get_state()
        if state is None:
            return False

        return state.get("status") == "Running"

    def launch(
        self,
        *,
        image: str,
        image_remote: str,
        uid: str = str(os.getuid()),
        ephemeral: bool = True,
    ) -> None:
        """Launch instance.

        :param image: Image name to launch.
        :param image_remote: Image remote name.
        :param uid: Host user ID to map to instance root.
        :param ephemeral: Flag to enable ephemeral instance.
        """
        config_keys = dict()
        config_keys["raw.idmap"] = f"both {uid!s} 0"

        if self._host_supports_mknod():
            config_keys["security.syscalls.intercept.mknod"] = "true"

        self.lxc.launch(
            config_keys=config_keys,
            ephemeral=ephemeral,
            instance_name=self.name,
            image=image,
            image_remote=image_remote,
            project=self.project,
            remote=self.remote,
        )

    def mount(self, *, host_source: pathlib.Path, target: pathlib.Path) -> None:
        """Mount host source directory to target mount point.

        Checks first to see if already mounted.

        :param source: Host path to mount.
        :param destination: Instance path to mount to.
        """
        if self.is_mounted(host_source=host_source, target=target):
            return

        self.lxc.config_device_add_disk(
            instance_name=self.name,
            source=host_source,
            destination=target,
            project=self.project,
            remote=self.remote,
        )

    def _host_supports_mknod(self) -> bool:
        """Check if host supports mknod in container.

        See: https://actions.linuxcontainers.org/lxd/docs/master/syscall-interception

        :returns: True if mknod is supported.
        """
        cfg = self.lxc.info(project=self.project, remote=self.remote)
        env = cfg.get("environment", dict())
        kernel_features = env.get("kernel_features", dict())
        seccomp_listener = kernel_features.get("seccomp_listener", "false")

        return seccomp_listener == "true"

    def pull(self, *, source: pathlib.Path, destination: pathlib.Path) -> None:
        """Copy source file/directory from environment to host destination.

        Standard "cp -r" rules apply:

            - if source is directory, copy happens recursively.

            - if destination exists, source will be copied into destination.

        Providing this as an abstract method allows the provider to implement
        the most performant option available.

        :param source: Target directory to copy from.
        :param destination: Host destination directory to copy to.
        """
        logger.info("Syncing env:%s -> host:%s...", source, destination)
        # TODO: check if mount makes source == destination, skip if so.
        if actions.linux.is_target_file(executor=self, target=source):
            self.lxc.file_pull(
                instance_name=self.name,
                source=source,
                destination=destination,
                project=self.project,
                remote=self.remote,
                create_dirs=True,
            )
        else:
            raise FileNotFoundError(f"Source {source} not found.")

    def push(self, *, source: pathlib.Path, destination: pathlib.Path) -> None:
        """Copy host source file/directory into environment at destination.

        Standard "cp -r" rules apply:
        - if source is directory, copy happens recursively.
        - if destination exists, source will be copied into destination.

        Providing this as an abstract method allows the provider to implement
        the most performant option available.

        :param source: Host directory to copy.
        :param destination: Target destination directory to copy to.
        """
        # TODO: check if mounted, skip sync if source == destination
        logger.info("Syncing host:%s -> env:%s...", source, destination)
        if source.is_file():
            self.lxc.file_push(
                instance_name=self.name,
                source=source,
                destination=destination,
                project=self.project,
                remote=self.remote,
                gid=0,
                uid=0,
            )
        else:
            raise FileNotFoundError(f"Source {source} not found.")

    def start(self) -> None:
        """Start instance."""
        self.lxc.start(
            instance_name=self.name, project=self.project, remote=self.remote
        )

    def stop(self) -> None:
        """Stop instance."""
        self.lxc.stop(instance_name=self.name, project=self.project, remote=self.remote)

    def supports_mount(self) -> bool:
        """Check if instance supports mounting from host.

        :returns: True if mount is supported.
        """
        return self.remote == "local"
