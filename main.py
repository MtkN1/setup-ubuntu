from __future__ import annotations

import argparse
import functools
import getpass
import io
import locale
import os
import os.path
import platform
import shlex
import shutil
import string
import subprocess
import sys
import tarfile
import tomllib
import urllib.parse
import urllib.request
from enum import StrEnum
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from http.client import HTTPResponse


class _Task(StrEnum):
    MAIN = "main"

    PREPARE_DOTFILES = "prepare_dotfiles"
    PREPARE_DOCKER = "prepare_docker"
    INSTALL_MISE = "install_mise"


class _Argument(TypedDict):
    operand: str
    options: Sequence[str]


class Config(TypedDict):
    apt: Sequence[str]
    snap: Sequence[str]
    snap_classic: Sequence[str]
    mise_core: Sequence[str]
    mise: Sequence[str]
    uv_python: Sequence[str]
    uv_tool: Sequence[str | _Argument]
    docker_apt: Sequence[str]
    docker_image: Sequence[str]
    setup: Sequence[str]


def _parse_args() -> _Task:
    parser = argparse.ArgumentParser()
    name = "task"
    parser.add_argument(name, nargs="?", default=_Task.MAIN.value)
    args = parser.parse_args()
    return _Task(getattr(args, name))


def _prepare_clean_env() -> Mapping[str, str]:
    path = os.pathsep.join(
        [
            os.path.expanduser("~/.local/share/mise/shims"),
            os.path.expanduser("~/.local/bin"),
            os.defpath,
        ]
    )
    home = os.path.expanduser("~")

    return {"PATH": path, "HOME": home}


def _load_config() -> Config:
    config_path = Path(__file__).with_name("config.toml")
    with config_path.open("rb") as f:
        raw = tomllib.load(f)

    return Config(**raw)


def _ensure_argument(str_or_argument: str | _Argument, /) -> _Argument:
    return (
        _Argument(operand=str_or_argument, options=[])
        if isinstance(str_or_argument, str)
        else str_or_argument
    )


def _check_call(*args: str, env: Mapping[str, str]) -> None:
    ansi_green, ansi_reset = "\033[32m", "\033[0m"
    shell_prefix = "#" if os.geteuid() == 0 else "$"
    shell_string = f"{shell_prefix} {shlex.join(args)}"
    print(f"{ansi_green}{shell_string}{ansi_reset}")

    subprocess.run(args, env=env, check=True)


def _prepare_dotfiles() -> None:
    home = Path.home()
    home.joinpath(".bashrc.d").mkdir(parents=True, exist_ok=True)
    home.joinpath(".config").mkdir(parents=True, exist_ok=True)

    local = home.joinpath(".local")
    local.joinpath("bin").mkdir(parents=True, exist_ok=True)
    local.joinpath("share/bash-completion/completions").mkdir(
        parents=True, exist_ok=True
    )

    shutil.copytree("/etc/skel", home, dirs_exist_ok=True)

    dotfiles_path = Path(__file__).with_name("dotfiles")
    shutil.copytree(dotfiles_path, home, dirs_exist_ok=True)


def _prepare_docker() -> None:
    os_release = platform.freedesktop_os_release()

    gpg_path = Path("/etc/apt/keyrings/docker.asc")
    template = string.Template("https://download.docker.com/linux/${ID}/gpg")
    gpg_url = template.substitute(os_release)

    response: HTTPResponse
    with (
        urllib.request.urlopen(gpg_url) as response,
        gpg_path.open("wb") as wf,
    ):
        read_func = functools.partial(response.read, io.DEFAULT_BUFFER_SIZE)
        for chunk in iter(read_func, b""):
            wf.write(chunk)

    deb822_path = Path("/etc/apt/sources.list.d/docker.sources")
    deb822_lines = [
        "Types: deb",
        "URIs: https://download.docker.com/linux/${ID}",
        "Suites: ${VERSION_CODENAME}",
        "Components: stable",
        f"Signed-By: {os.fspath(gpg_path)}",
        "",
    ]

    template = string.Template("\n".join(deb822_lines))
    deb822_content = template.substitute(os_release)
    deb822_path.write_text(deb822_content, encoding=locale.getencoding())


def _install_mise() -> None:
    latest_release_url = "https://github.com/jdx/mise/releases/latest"
    response: HTTPResponse = urllib.request.urlopen(latest_release_url)
    response.close()

    split_result = urllib.parse.urlsplit(response.url)
    path = PurePosixPath(split_result.path)
    parts = path.parts

    match parts:
        case [str(), str(), str(), "releases", "tag", str() as _tag]:
            tag = _tag
        case _:
            raise ValueError(path)

    uname = platform.uname()
    match uname.system:
        case "Linux":
            system = "linux"
        case _:
            raise ValueError(uname.system)
    match uname.machine:
        case "x86_64":
            machine = "x64"
        case "aarch64":
            machine = "arm64"
        case _:
            raise ValueError(uname.machine)

    name = f"mise-{tag}-{system}-{machine}.tar.gz"

    download_url = "https://github.com/jdx/mise/releases/download"
    tarball_url = f"{download_url}/{tag}/{name}"

    with TemporaryDirectory() as tmpdir:
        with (
            urllib.request.urlopen(tarball_url) as response,
            tarfile.open(fileobj=response, mode="r|gz") as tar,
        ):
            tar.extractall(tmpdir, filter="data")

        src = Path(tmpdir).joinpath("mise/bin/mise")
        dst = Path.home().joinpath(".local/bin/mise")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        src = Path(tmpdir).joinpath("mise/man/man1/mise.1")
        dst = Path.home().joinpath(".local/share/man/man1/mise.1")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def main() -> None:
    task = _parse_args()

    match task:
        case _Task.PREPARE_DOTFILES:
            _prepare_dotfiles()
        case _Task.PREPARE_DOCKER:
            _prepare_docker()
        case _Task.INSTALL_MISE:
            _install_mise()
        case _Task.MAIN:
            config = _load_config()
            env = _prepare_clean_env()
            user = getpass.getuser()

            # dotfiles
            _check_call(
                sys.executable,
                __file__,
                _Task.PREPARE_DOTFILES.value,
                env=env,
            )

            # Docker repository
            need_docker = shutil.which("docker", path=env["PATH"]) is None
            if need_docker:
                _check_call(
                    "sudo",
                    sys.executable,
                    __file__,
                    _Task.PREPARE_DOCKER.value,
                    env=env,
                )

            # APT
            _check_call("sudo", "apt-get", "update", env=env)

            _check_call("sudo", "apt-get", "-y", "dist-upgrade", env=env)

            operands = [*config["apt"]]
            if need_docker:
                operands.extend(config["docker_apt"])
            if operands:
                _check_call(
                    "sudo",
                    "apt-get",
                    "-y",
                    "install",
                    "--",
                    *operands,
                    env=env,
                )
            if need_docker:
                _check_call("sudo", "usermod", "-aG", "docker", user, env=env)

            _check_call("sudo", "apt-get", "-y", "autopurge", env=env)

            _check_call("sudo", "apt-get", "-y", "autoclean", env=env)

            # Snap
            _check_call("sudo", "snap", "refresh", env=env)

            if config["snap"]:
                _check_call("sudo", "snap", "install", "--", *config["snap"], env=env)

            for operand in config["snap_classic"]:
                _check_call(
                    "sudo",
                    "snap",
                    "install",
                    "--classic",
                    "--",
                    operand,
                    env=env,
                )

            # Mise
            need_mise = shutil.which("mise", path=env["PATH"]) is None
            if need_mise:
                _check_call(sys.executable, __file__, _Task.INSTALL_MISE.value, env=env)
            else:
                _check_call("mise", "self-update", "-y", env=env)

                _check_call("mise", "upgrade", "--bump", env=env)

            if config["mise_core"]:
                _check_call("mise", "use", "-g", "--", *config["mise_core"], env=env)

            if config["mise"]:
                _check_call("mise", "use", "-g", "--", *config["mise"], env=env)

            # uv
            _check_call("uv", "python", "upgrade", env=env)

            if config["uv_python"]:
                _check_call(
                    "uv", "python", "install", "--", *config["uv_python"], env=env
                )

            _check_call("uv", "tool", "upgrade", "--all", env=env)

            for item in config["uv_tool"]:
                argument = _ensure_argument(item)
                _check_call(
                    "uv",
                    "tool",
                    "install",
                    *argument["options"],
                    "--",
                    argument["operand"],
                    env=env,
                )

            # Docker image
            for operand in config["docker_image"]:
                _check_call("sudo", "docker", "pull", "--", operand, env=env)

            # Setup script
            for command in config["setup"]:
                _check_call("/bin/sh", "-c", command, env=env)
        case _:
            raise ValueError(task)


if __name__ == "__main__":
    main()
