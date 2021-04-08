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

"""Buildd image(s)."""
import enum
import io
import logging
import pathlib
import subprocess
import time
from textwrap import dedent
from time import sleep
from typing import Dict, Optional

from craft_providers import Base, Executor, errors

from .errors import BaseConfigurationError

logger = logging.getLogger(__name__)


def default_command_environment() -> Dict[str, Optional[str]]:
    """Provide default command environment dictionary.

    The minimum environment for the buildd image to be configured and function
    properly.  This contains the default environment found in Ubuntu's
    /etc/environment.

    :returns: Dictionary of environment key/values.
    """
    return dict(
        PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin"
    )


def _check_deadline(
    deadline: Optional[float],
    *,
    message: str = "Timed out configuring environment.",
) -> None:
    """Check deadline and raise error if passed.

    :param deadline: Optional time.time() deadline.

    :raises BaseConfigurationError: if deadline is passed.
    """
    if deadline is not None and time.time() >= deadline:
        raise BaseConfigurationError(brief=message)


class BuilddBaseAlias(enum.Enum):
    """Mappings for supported buildd images."""

    XENIAL = "16.04"
    BIONIC = "18.04"
    FOCAL = "20.04"


class BuilddBase(Base):
    """Support for Ubuntu minimal buildd images.

    :param alias: Base alias / version.
    :param hostname: Hostname to configure.
    :param command_environment: Additional environment to configure for command.
        If specifying an environment, default_command_environment() is provided
        for the minimum required environment configuration.
    """

    def __init__(
        self,
        *,
        alias: BuilddBaseAlias,
        hostname: str = "craft-buildd-instance",
        command_environment: Optional[Dict[str, Optional[str]]] = None,
    ):
        self.alias: BuilddBaseAlias = alias
        self.hostname: str = hostname

        if command_environment is not None:
            self.command_environment = command_environment
        else:
            self.command_environment = default_command_environment()

    def setup(
        self,
        *,
        executor: Executor,
        retry_wait: float = 0.25,
        timeout: Optional[float] = None,
    ) -> None:
        """Prepare base instance for use by the application.

        Wait for environment to become ready and configure it.  At completion of
        setup, the executor environment should have networking up and have all
        of the installed dependencies required for subsequent use by the
        application.

        Setup may be called more than once in a given instance to refresh/update
        the environment.

        If timeout is specified, abort operation if time has been exceeded.

        Guarantees provided by this setup:

            - configured hostname

            - networking available (IP & DNS resolution)

            - apt cache up-to-date

            - snapd configured and ready

            - system services are started and ready

        :param executor: Executor for target container.
        :param retry_wait: Duration to sleep() between status checks (if
            required).
        :param timeout: Timeout in seconds.

        :raises BaseConfigurationError: on other unexpected error.
        """
        if timeout is not None:
            deadline: Optional[float] = time.time() + timeout
            _check_deadline(deadline)
        else:
            deadline = None

        self._setup_environment(executor=executor, deadline=deadline)
        self._setup_wait_for_system_ready(
            executor=executor, deadline=deadline, retry_wait=retry_wait
        )
        self._setup_hostname(executor=executor, deadline=deadline)
        self._setup_resolved(executor=executor, deadline=deadline)
        self._setup_networkd(executor=executor, deadline=deadline)
        self._setup_wait_for_network(
            executor=executor, deadline=deadline, retry_wait=retry_wait
        )
        self._setup_apt(executor=executor, deadline=deadline)
        self._setup_snapd(executor=executor, deadline=deadline)

    def _setup_apt(self, *, executor: Executor, deadline: Optional[float]) -> None:
        """Configure apt & update cache.

        :param executor: Executor for target container.
        """
        executor.create_file(
            destination=pathlib.Path("/etc/apt/apt.conf.d/00no-recommends"),
            content=io.BytesIO('Apt::Install-Recommends "false";\n'.encode()),
            file_mode="0644",
        )

        try:
            executor.execute_run(
                ["apt-get", "update"],
                capture_output=True,
                check=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)
        except subprocess.CalledProcessError as error:
            raise BaseConfigurationError(
                brief="Failed to update apt cache.",
                details=errors.details_from_called_process_error(error),
            ) from error

        try:
            executor.execute_run(
                ["apt-get", "install", "-y", "apt-utils"],
                capture_output=True,
                check=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)
        except subprocess.CalledProcessError as error:
            raise BaseConfigurationError(
                brief="Failed to install apt-utils.",
                details=errors.details_from_called_process_error(error),
            ) from error

        _check_deadline(deadline)

    def _setup_environment(
        self, *, executor: Executor, deadline: Optional[float]
    ) -> None:
        """Configure hostname, installing /etc/hostname.

        :param executor: Executor for target container.
        """
        content = (
            "\n".join(
                [
                    f"{k}={v}"
                    for k, v in self.command_environment.items()
                    if v is not None
                ]
            )
            + "\n"
        ).encode()

        executor.create_file(
            destination=pathlib.Path("/etc/environment"),
            content=io.BytesIO(content),
            file_mode="0644",
        )
        _check_deadline(deadline)

    def _setup_hostname(self, *, executor: Executor, deadline: Optional[float]) -> None:
        """Configure hostname, installing /etc/hostname.

        :param executor: Executor for target container.
        """
        executor.create_file(
            destination=pathlib.Path("/etc/hostname"),
            content=io.BytesIO((self.hostname + "\n").encode()),
            file_mode="0644",
        )

        try:
            executor.execute_run(
                ["hostname", "-F", "/etc/hostname"],
                capture_output=True,
                check=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)
        except subprocess.CalledProcessError as error:
            raise BaseConfigurationError(
                brief="Failed to set hostname.",
                details=errors.details_from_called_process_error(error),
            ) from error

    def _setup_networkd(self, *, executor: Executor, deadline: Optional[float]) -> None:
        """Configure networkd and start it.

        Installs eth0 network configuration using ipv4.

        :param executor: Executor for target container.
        """
        executor.create_file(
            destination=pathlib.Path("/etc/systemd/network/10-eth0.network"),
            content=io.BytesIO(
                dedent(
                    """\
                [Match]
                Name=eth0

                [Network]
                DHCP=ipv4
                LinkLocalAddressing=ipv6

                [DHCP]
                RouteMetric=100
                UseMTU=true
                """
                ).encode()
            ),
            file_mode="0644",
        )

        try:
            executor.execute_run(
                ["systemctl", "enable", "systemd-networkd"],
                capture_output=True,
                check=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)

            executor.execute_run(
                ["systemctl", "restart", "systemd-networkd"],
                check=True,
                capture_output=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)
        except subprocess.CalledProcessError as error:
            raise BaseConfigurationError(
                brief="Failed to setup systemd-networkd.",
                details=errors.details_from_called_process_error(error),
            ) from error

    def _setup_resolved(self, *, executor: Executor, deadline: Optional[float]) -> None:
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
                env=self.command_environment,
            )
            _check_deadline(deadline)

            executor.execute_run(
                ["systemctl", "enable", "systemd-resolved"],
                check=True,
                capture_output=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)

            executor.execute_run(
                ["systemctl", "restart", "systemd-resolved"],
                check=True,
                capture_output=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)
        except subprocess.CalledProcessError as error:
            raise BaseConfigurationError(
                brief="Failed to setup systemd-resolved.",
                details=errors.details_from_called_process_error(error),
            ) from error

    def _setup_snapd(
        self, *, executor: Executor, deadline: Optional[float] = None
    ) -> None:
        """Install snapd and dependencies and wait until ready.

        :param executor: Executor for target container.
        :param deadline: Optional time.time() deadline.
        """
        try:
            # TODO: Is udev required for LXD? it is not for Multipass.
            executor.execute_run(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "fuse",
                    "udev",
                ],
                check=True,
                capture_output=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)

            executor.execute_run(
                ["systemctl", "enable", "systemd-udevd"],
                capture_output=True,
                check=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)

            executor.execute_run(
                ["systemctl", "start", "systemd-udevd"],
                capture_output=True,
                check=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)

            executor.execute_run(
                ["apt-get", "install", "-y", "snapd"],
                capture_output=True,
                check=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)

            executor.execute_run(
                ["systemctl", "start", "snapd.socket"],
                capture_output=True,
                check=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)

            # Restart, not start, the service in case the environment
            # has changed and the service is already running.
            executor.execute_run(
                ["systemctl", "restart", "snapd.service"],
                capture_output=True,
                check=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)

            executor.execute_run(
                ["snap", "wait", "system", "seed.loaded"],
                capture_output=True,
                check=True,
                env=self.command_environment,
            )
            _check_deadline(deadline)
        except subprocess.CalledProcessError as error:
            raise BaseConfigurationError(
                brief="Failed to setup snapd.",
                details=errors.details_from_called_process_error(error),
            ) from error

    def _setup_wait_for_network(
        self,
        *,
        executor: Executor,
        retry_wait: float = 0.25,
        deadline: Optional[float] = None,
    ) -> None:
        """Wait until networking is ready.

        :param executor: Executor for target container.
        :param retry_wait: Duration to sleep() between status checks.
        :param deadline: Optional time.time() deadline.
        """
        logger.debug("Waiting for networking to be ready...")

        while True:
            proc = executor.execute_run(
                ["getent", "hosts", "snapcraft.io"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self.command_environment,
            )
            if proc.returncode == 0:
                return

            _check_deadline(
                deadline, message="Timed out waiting for networking to be ready."
            )
            sleep(retry_wait)

    def _setup_wait_for_system_ready(
        self,
        *,
        executor: Executor,
        retry_wait: float = 0.25,
        deadline: Optional[float] = None,
    ) -> None:
        """Wait until system is ready.

        :param executor: Executor for target container.
        :param retry_wait: Duration to sleep() between status checks.
        :param deadline: Optional time.time() deadline.
        """
        logger.debug("Waiting for environment to be ready...")

        while True:
            proc = executor.execute_run(
                ["systemctl", "is-system-running"],
                capture_output=True,
                check=False,
                env=self.command_environment,
                text=True,
            )

            running_state = proc.stdout.strip()
            if running_state in ["running", "degraded"]:
                return

            logger.debug("systemctl is-system-running status: %s", running_state)

            _check_deadline(
                deadline, message="Timed out waiting for environment to be ready."
            )
            sleep(retry_wait)

    def wait_until_ready(
        self,
        *,
        executor: Executor,
        retry_wait: float = 0.25,
        timeout: Optional[float] = None,
    ) -> None:
        """Wait until base instance is ready.

        Ensure minimum-required boot services are running.  This would be used
        when starting an environment's container/VM after already [recently]
        running setup(), e.g. rebooting the instance.  Allows the environment to
        be used without the cost incurred by re-executing the steps
        unnecessarily.

        If timeout is specified, abort operation if time has been exceeded.

        Guarantees provided by this wait:

            - networking available (IP & DNS resolution)

            - system services are started and ready

        :param executor: Executor for target container.
        :param retry_wait: Duration to sleep() between status checks (if
            required).
        :param timeout: Timeout in seconds.

        :raises ProviderError: on timeout or unexpected error.
        """
        if timeout is not None:
            deadline: Optional[float] = time.time() + timeout
            _check_deadline(deadline)
        else:
            deadline = None

        self._setup_wait_for_system_ready(
            executor=executor,
            retry_wait=retry_wait,
            deadline=deadline,
        )
        self._setup_wait_for_network(
            executor=executor,
            retry_wait=retry_wait,
            deadline=deadline,
        )