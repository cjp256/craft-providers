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

"""Buildd image(s)."""
import enum
import logging
import pathlib
import subprocess
from textwrap import dedent
from time import sleep
from typing import Any, Dict, Final, Optional

from craft_providers import Executor, Image, actions
from craft_providers.images import errors
from craft_providers.util.os_release import parse_os_release

logger = logging.getLogger(__name__)


class BuilddImageAlias(enum.Enum):
    """Mappings for supported buildd images."""

    XENIAL = "16.04"
    BIONIC = "18.04"
    FOCAL = "20.04"


class BuilddImage(Image):
    """Support for Ubuntu minimal buildd images.

    :param alias: Image alias / version.
    :param hostname: Hostname to configure.
    :param compatibility_tag: Version of image setup used to ensure compatibility
        for re-used instances.  Any change to this version would indicate that
        prior [versioned] instances are incompatible and must be cleaned.  As
        such, any new value should be unique to old values (e.g. incrementing).
    """

    def __init__(
        self,
        *,
        alias: BuilddImageAlias,
        compatibility_tag: str = "craft-buildd-image-v0",
        hostname: str = "craft-buildd-instance",
        http_proxy: Optional[str] = None,
        https_proxy: Optional[str] = None,
    ):
        super().__init__(compatibility_tag=compatibility_tag, name=alias.value)

        self.alias: Final[BuilddImageAlias] = alias
        self.hostname: Final[str] = hostname
        self.http_proxy = http_proxy
        self.https_proxy = https_proxy
        self._craft_config_path = pathlib.Path("/etc/craft-image.conf")

        self.command_env: Dict[str, str] = dict(
            PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin"
        )

        if self.http_proxy:
            self.command_env["http_proxy"] = self.http_proxy

        if self.https_proxy:
            self.command_env["https_proxy"] = self.https_proxy

    def ensure_compatible(self, *, executor: Executor) -> None:
        """Ensure exector target is compatible with image.

        :param executor: Executor for target container.
        """
        self._ensure_image_version_compatible(executor=executor)
        self._ensure_os_compatible(executor=executor)

    def _ensure_image_version_compatible(self, *, executor: Executor) -> None:
        config = actions.craft_config.load(
            executor=executor, config_path=self._craft_config_path
        )

        # If no config has been written, assume it is compatible (likely an unfinished setup).
        if config is None:
            return

        tag = config.get("compatibility_tag")
        if tag != self.compatibility_tag:
            raise errors.CompatibilityError(
                reason=(
                    "Expected image compatibility tag "
                    f"{self.compatibility_tag!r}, found '{tag!s}'"
                )
            )

    def _ensure_os_compatible(self, *, executor: Executor) -> None:
        os_release = self._read_os_release(executor=executor)

        os_id = os_release.get("NAME")
        if os_id != "Ubuntu":
            raise errors.CompatibilityError(
                reason=f"Exepcted OS 'Ubuntu', found {os_id!r}"
            )

        compat_version_id = self.alias.value
        version_id = os_release.get("VERSION_ID")
        if version_id != compat_version_id:
            raise errors.CompatibilityError(
                reason=f"Expected OS version {compat_version_id!r}, found {version_id!r}"
            )

    def _read_os_release(self, *, executor: Executor) -> Dict[str, Any]:
        """Read & parse /etc/os-release.

        :param executor: Executor for target.

        :returns: Dictionary of parsed /etc/os-release, if present. Otherwise None.
        """
        command = ["cat", "/etc/os-release"]

        try:
            proc = executor.execute_run(
                command,
                capture_output=True,
                check=False,
                env=self.command_env,
            )
        except subprocess.CalledProcessError as error:
            raise errors.CraftEnvironmentError.from_called_process_error(
                brief="Failed to read /etc/os-release.",
                error=error,
            )

        return parse_os_release(proc.stdout.decode())

    def setup(self, *, executor: Executor) -> None:
        """Configure buildd image to minimum baseline.

        Install & wait for ready:
        - hostname
        - networking (ip & dns)
        - apt cache
        - snapd

        :param executor: Executor for target container.
        """
        self.ensure_compatible(executor=executor)
        self._setup_environment(executor=executor)
        self._setup_wait_for_system_ready(executor=executor)
        self._setup_craft_image_config(executor=executor)
        self._setup_hostname(executor=executor)
        self._setup_resolved(executor=executor)
        self._setup_networkd(executor=executor)
        self._setup_wait_for_network(executor=executor)
        self._setup_apt(executor=executor)
        self._setup_snapd(executor=executor)

    def _setup_apt(self, *, executor: Executor) -> None:
        """Configure apt & update cache.

        :param executor: Executor for target container.
        """
        executor.create_file(
            destination=pathlib.Path("/etc/apt/apt.conf.d/00no-recommends"),
            content='Apt::Install-Recommends "false";\n'.encode(),
            file_mode="0644",
        )

        try:
            executor.execute_run(
                ["apt-get", "update"],
                capture_output=True,
                check=True,
                env=self.command_env,
            )
        except subprocess.CalledProcessError as error:
            raise errors.CraftEnvironmentError.from_called_process_error(
                brief="Failed to update apt cache.",
                error=error,
            )

        try:
            executor.execute_run(
                ["apt-get", "install", "-y", "apt-utils"],
                capture_output=True,
                check=True,
                env=self.command_env,
            )
        except subprocess.CalledProcessError as error:
            raise errors.CraftEnvironmentError.from_called_process_error(
                brief="Failed to install apt-utils.",
                error=error,
            )

    def _setup_craft_image_config(self, *, executor: Executor) -> None:
        config = dict(compatibility_tag=self.compatibility_tag)

        actions.craft_config.save(
            executor=executor,
            config=config,
            config_path=self._craft_config_path,
        )

    def _setup_environment(self, *, executor: Executor) -> None:
        """Configure hostname, installing /etc/hostname.

        :param executor: Executor for target container.
        """
        content = "\n".join([f"{k}={v}" for k, v in self.command_env.items()]).encode()

        executor.create_file(
            destination=pathlib.Path("/etc/environment"),
            content=content,
            file_mode="0644",
        )

    def _setup_hostname(self, *, executor: Executor) -> None:
        """Configure hostname, installing /etc/hostname.

        :param executor: Executor for target container.
        """
        executor.create_file(
            destination=pathlib.Path("/etc/hostname"),
            content=self.hostname.encode(),
            file_mode="0644",
        )

        try:
            executor.execute_run(
                ["hostname", "-F", "/etc/hostname"],
                capture_output=True,
                check=True,
                env=self.command_env,
            )
        except subprocess.CalledProcessError as error:
            raise errors.CraftEnvironmentError.from_called_process_error(
                brief="Failed to set hostname.",
                error=error,
            )

    def _setup_networkd(self, *, executor: Executor) -> None:
        """Configure networkd and start it.

        Installs eth0 network configuration using ipv4.

        :param executor: Executor for target container.
        """
        executor.create_file(
            destination=pathlib.Path("/etc/systemd/network/10-eth0.network"),
            content=dedent(
                """
                [Match]
                Name=eth0

                [Network]
                DHCP=ipv4
                LinkLocalAddressing=ipv6

                [DHCP]
                RouteMetric=100
                UseMTU=true
                """
            ).encode(),
            file_mode="0644",
        )

        try:
            executor.execute_run(
                ["systemctl", "enable", "systemd-networkd"],
                capture_output=True,
                check=True,
                env=self.command_env,
            )

            executor.execute_run(
                ["systemctl", "restart", "systemd-networkd"],
                check=True,
                capture_output=True,
                env=self.command_env,
            )
        except subprocess.CalledProcessError as error:
            raise errors.CraftEnvironmentError.from_called_process_error(
                brief="Failed to setup systemd-networkd.",
                error=error,
            )

    def _setup_resolved(self, *, executor: Executor) -> None:
        """Configure system-resolved to manage resolve.conf.

        :param executor: Executor for target container.
        :param timeout_secs: Timeout in seconds.
        """
        try:
            executor.execute_run(
                [
                    "ln",
                    "-sf",
                    "/run/systemd/resolve/resolv.conf",
                    "/etc/resolv.conf",
                ],
                check=True,
                capture_output=True,
                env=self.command_env,
            )

            executor.execute_run(
                ["systemctl", "enable", "systemd-resolved"],
                check=True,
                capture_output=True,
                env=self.command_env,
            )

            executor.execute_run(
                ["systemctl", "restart", "systemd-resolved"],
                check=True,
                capture_output=True,
                env=self.command_env,
            )
        except subprocess.CalledProcessError as error:
            raise errors.CraftEnvironmentError.from_called_process_error(
                brief="Failed to setup systemd-resolved.",
                error=error,
            )

    def _setup_snapd(self, *, executor: Executor) -> None:
        """Install snapd and dependencies and wait until ready.

        :param executor: Executor for target container.
        :param timeout_secs: Timeout in seconds.
        """
        try:
            executor.execute_run(
                [
                    "apt-get",
                    "install",
                    "fuse",
                    "udev",
                    "--yes",
                ],
                check=True,
                capture_output=True,
                env=self.command_env,
            )

            executor.execute_run(
                ["systemctl", "enable", "systemd-udevd"],
                capture_output=True,
                check=True,
                env=self.command_env,
            )
            executor.execute_run(
                ["systemctl", "start", "systemd-udevd"],
                capture_output=True,
                check=True,
                env=self.command_env,
            )
            executor.execute_run(
                ["apt-get", "install", "snapd", "--yes"],
                capture_output=True,
                check=True,
                env=self.command_env,
            )
            executor.execute_run(
                ["systemctl", "start", "snapd.socket"],
                capture_output=True,
                check=True,
                env=self.command_env,
            )

            # Restart, not start, the service in case the environment
            # has changed and the service is already running.
            executor.execute_run(
                ["systemctl", "restart", "snapd.service"],
                capture_output=True,
                check=True,
                env=self.command_env,
            )
            executor.execute_run(
                ["snap", "wait", "system", "seed.loaded"],
                capture_output=True,
                check=True,
                env=self.command_env,
            )
        except subprocess.CalledProcessError as error:
            raise errors.CraftEnvironmentError.from_called_process_error(
                brief="Failed to setup snapd.",
                error=error,
            )

    def _setup_wait_for_network(
        self, *, executor: Executor, timeout_secs: int = 60
    ) -> None:
        """Wait until networking is ready.

        :param executor: Executor for target container.
        :param timeout_secs: Timeout in seconds.
        """
        logger.info("Waiting for networking to be ready...")
        for _ in range(timeout_secs * 2):
            proc = executor.execute_run(
                ["getent", "hosts", "snapcraft.io"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self.command_env,
            )
            if proc.returncode == 0:
                break

            sleep(0.5)
        else:
            raise errors.CraftEnvironmentError(
                brief="Timed out waiting for neworking.",
            )

    def _setup_wait_for_system_ready(
        self, *, executor: Executor, retry_count=120, retry_interval: float = 0.5
    ) -> None:
        """Wait until system is ready.

        :param executor: Executor for target container.
        :param timeout_secs: Timeout in seconds.
        """
        logger.info("Waiting for container to be ready...")
        for _ in range(retry_count):
            proc = executor.execute_run(
                ["systemctl", "is-system-running"],
                capture_output=True,
                check=False,
                env=self.command_env,
            )

            running_state = proc.stdout.decode().strip()
            if running_state in ["running", "degraded"]:
                break

            logger.debug("systemctl is-system-running status: %s", running_state)
            sleep(retry_interval)
        else:
            raise errors.CraftEnvironmentError(
                brief="Timed out waiting for environment to be ready.",
            )

    def wait_until_ready(self, *, executor: Executor) -> None:
        """Wait until system is ready.

        Ensure minimum-required boot services are running.
        """
        self._setup_wait_for_system_ready(executor=executor)
