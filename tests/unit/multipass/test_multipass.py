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
import json
import pathlib
import subprocess

import pytest

from craft_providers.multipass import Multipass
from craft_providers.multipass.errors import MultipassError

EXAMPLE_INFO = """\
{
    "errors": [
    ],
    "info": {
        "flowing-hawfinch": {
            "disks": {
                "sda1": {
                    "total": "5019643904",
                    "used": "1339375616"
                }
            },
            "image_hash": "c5f2f08c6a1adee1f2f96d84856bf0162d33ea182dae0e8ed45768a86182d110",
            "image_release": "20.04 LTS",
            "ipv4": [
                "10.114.154.206"
            ],
            "load": [
                0.29,
                0.08,
                0.02
            ],
            "memory": {
                "total": 1028894720,
                "used": 152961024
            },
            "mounts": {
            },
            "release": "Ubuntu 20.04.2 LTS",
            "state": "Running"
        }
    }
}
"""

EXAMPLE_LIST = """\
{
    "list": [
        {
            "ipv4": [
            ],
            "name": "manageable-snipe",
            "release": "20.04 LTS",
            "state": "Starting"
        },
        {
            "ipv4": [
                "10.114.154.206"
            ],
            "name": "flowing-hawfinch",
            "release": "20.04 LTS",
            "state": "Running"
        }
    ]
}
"""


def test_delete(fake_process):
    fake_process.register_subprocess(["multipass", "delete", "test-instance"])

    Multipass().delete(instance_name="test-instance", purge=False)

    assert len(fake_process.calls) == 1


def test_delete_purge(fake_process):
    fake_process.register_subprocess(
        ["multipass", "delete", "test-instance", "--purge"]
    )

    Multipass().delete(instance_name="test-instance", purge=True)

    assert len(fake_process.calls) == 1


def test_delete_failure(fake_process):
    fake_process.register_subprocess(
        ["multipass", "delete", "test-instance", "--purge"],
        returncode=1,
    )

    with pytest.raises(MultipassError) as exc_info:
        Multipass().delete(instance_name="test-instance", purge=True)

    assert exc_info.value == MultipassError(
        brief="Failed to delete VM 'test-instance'.",
        details="* Command that failed: multipass delete test-instance --purge\n* Command exit code: 1",
    )


def test_exec(fake_process):
    fake_process.register_subprocess(
        ["multipass", "exec", "test-instance", "--", "sleep", "1"]
    )

    Multipass().exec(command=["sleep", "1"], instance_name="test-instance")

    assert len(fake_process.calls) == 1


def test_exec_failure_no_check(fake_process):
    fake_process.register_subprocess(
        ["multipass", "exec", "test-instance", "--", "false"],
        returncode=1,
    )

    proc = Multipass().exec(command=["false"], instance_name="test-instance")

    assert proc.returncode == 1


def test_exec_failure_with_check(fake_process):
    fake_process.register_subprocess(
        ["multipass", "exec", "test-instance", "--", "false"],
        returncode=1,
    )

    with pytest.raises(subprocess.CalledProcessError):
        Multipass().exec(command=["false"], instance_name="test-instance", check=True)


def test_info(fake_process):
    fake_process.register_subprocess(
        ["multipass", "info", "test-instance", "--format", "json"], stdout=EXAMPLE_INFO
    )

    data = Multipass().info(instance_name="test-instance")

    assert len(fake_process.calls) == 1
    assert data == json.loads(EXAMPLE_INFO)


def test_info_no_vm(fake_process):
    fake_process.register_subprocess(
        ["multipass", "info", "test-instance", "--format", "json"],
        stdout='info failed: The following errors occurred:\ninstance "foo" does not exist',
        returncode=1,
    )

    data = Multipass().info(instance_name="test-instance")

    assert len(fake_process.calls) == 1
    assert data == None


def test_info_failure(fake_process):
    fake_process.register_subprocess(
        ["multipass", "info", "test-instance", "--format", "json"], returncode=1
    )

    with pytest.raises(MultipassError) as exc_info:
        Multipass().info(instance_name="test-instance")

    assert len(fake_process.calls) == 1
    assert exc_info.value == MultipassError(
        brief="Failed to query info for VM 'test-instance'.",
        details="* Command that failed: multipass info test-instance --format json\n* Command exit code: 1",
    )


def test_launch(fake_process):
    fake_process.register_subprocess(
        ["multipass", "launch", "test-image", "--name", "test-instance"]
    )

    data = Multipass().launch(image="test-image", instance_name="test-instance")

    assert len(fake_process.calls) == 1


def test_launch_all_opts(fake_process):
    fake_process.register_subprocess(
        [
            "multipass",
            "launch",
            "test-image",
            "--name",
            "test-instance",
            "--cpus",
            "4",
            "--mem",
            "8G",
            "--disk",
            "80G",
        ]
    )

    data = Multipass().launch(
        image="test-image",
        instance_name="test-instance",
        cpus="4",
        mem="8G",
        disk="80G",
    )

    assert len(fake_process.calls) == 1


def test_launch_failure(fake_process):
    fake_process.register_subprocess(
        ["multipass", "launch", "test-image", "--name", "test-instance"], returncode=1
    )

    with pytest.raises(MultipassError) as exc_info:
        Multipass().launch(instance_name="test-instance", image="test-image")

    assert len(fake_process.calls) == 1
    assert exc_info.value == MultipassError(
        brief="Failed to launch VM 'test-instance'.",
        details="* Command that failed: multipass launch test-image --name test-instance\n* Command exit code: 1",
    )


def test_list(fake_process):
    fake_process.register_subprocess(
        ["multipass", "list", "--format", "json"], stdout=EXAMPLE_LIST
    )

    vm_list = Multipass().list()

    assert len(fake_process.calls) == 1
    assert vm_list == ["manageable-snipe", "flowing-hawfinch"]


def test_list_failure(fake_process):
    fake_process.register_subprocess(
        ["multipass", "list", "--format", "json"], returncode=1
    )

    with pytest.raises(MultipassError) as exc_info:
        Multipass().list()

    assert len(fake_process.calls) == 1
    assert exc_info.value == MultipassError(
        brief="Failed to query list of VMs.",
        details="* Command that failed: multipass list --format json\n* Command exit code: 1",
    )


def test_mount(fake_process):
    fake_process.register_subprocess(
        ["multipass", "mount", "/home/user/my-project", "test-instance:/mnt"]
    )

    Multipass().mount(
        source=pathlib.Path("/home/user/my-project"),
        target="test-instance:/mnt",
        uid_map=None,
        gid_map=None,
    )

    assert len(fake_process.calls) == 1


def test_mount_all_opts(fake_process):
    fake_process.register_subprocess(
        [
            "multipass",
            "mount",
            "/home/user/my-project",
            "test-instance:/mnt",
            "--uid-map",
            "1:2",
            "--gid-map",
            "3:4",
        ]
    )

    Multipass().mount(
        source=pathlib.Path("/home/user/my-project"),
        target="test-instance:/mnt",
        uid_map={"1": "2"},
        gid_map={"3": "4"},
    )

    assert len(fake_process.calls) == 1


def test_mount_failure(fake_process):
    fake_process.register_subprocess(
        ["multipass", "mount", "/home/user/my-project", "test-instance:/mnt"],
        returncode=1,
    )

    with pytest.raises(MultipassError) as exc_info:
        Multipass().mount(
            source=pathlib.Path("/home/user/my-project"),
            target="test-instance:/mnt",
        )

    assert len(fake_process.calls) == 1
    assert exc_info.value == MultipassError(
        brief="Failed to mount '/home/user/my-project' to 'test-instance:/mnt'.",
        details="* Command that failed: multipass mount /home/user/my-project test-instance:/mnt\n* Command exit code: 1",
    )
