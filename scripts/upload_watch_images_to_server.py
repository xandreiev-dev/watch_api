import argparse
import os
import posixpath
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import paramiko

from watch_api.config import settings
from watch_api.services.watch_card_service import IMAGE_STORAGE_DIR


DEFAULT_REMOTE_DIR = "/var/www/premikum.com/watch-images"


def connect_ssh() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        settings.ssh_host,
        port=settings.ssh_port,
        username=settings.ssh_user,
        password=settings.ssh_password,
        timeout=15,
    )
    return client


def run_command(client: paramiko.SSHClient, command: str, use_sudo_password: bool = False) -> None:
    stdin, stdout, stderr = client.exec_command(command)
    if use_sudo_password:
        stdin.write(settings.ssh_password + "\n")
        stdin.flush()
    exit_code = stdout.channel.recv_exit_status()
    error_text = stderr.read().decode("utf-8", errors="ignore").strip()
    if exit_code != 0:
        raise RuntimeError(error_text or f"Remote command failed with exit code {exit_code}")


def setup_remote_dir(client: paramiko.SSHClient, remote_dir: str) -> None:
    command = (
        "sudo -S -p '' "
        f"mkdir -p {shell_quote(remote_dir)} "
        f"&& sudo chown {shell_quote(settings.ssh_user)}:www {shell_quote(remote_dir)} "
        f"&& sudo chmod 775 {shell_quote(remote_dir)}"
    )
    run_command(client, command, use_sudo_password=True)


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def iter_image_files(local_dir: Path) -> list[Path]:
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    return sorted(path for path in local_dir.iterdir() if path.is_file() and path.suffix.casefold() in extensions)


def upload_files(client: paramiko.SSHClient, local_dir: Path, remote_dir: str, quiet: bool) -> int:
    uploaded = 0
    with client.open_sftp() as sftp:
        for local_path in iter_image_files(local_dir):
            remote_path = posixpath.join(remote_dir, local_path.name)
            sftp.put(str(local_path), remote_path)
            uploaded += 1
            if not quiet:
                print(f"OK {local_path.name} -> {remote_path}")
    return uploaded


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload generated watch images to the production web root.")
    parser.add_argument("--local-dir", default=str(IMAGE_STORAGE_DIR), help="Directory with generated watch images.")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help="Remote directory served by premikum.com.")
    parser.add_argument("--setup-dir", action="store_true", help="Create and chmod the remote directory with sudo.")
    parser.add_argument("--quiet", action="store_true", help="Print only the final summary.")
    args = parser.parse_args()

    local_dir = Path(args.local_dir)
    if not local_dir.exists():
        raise SystemExit(f"Local image directory not found: {local_dir}")

    client = connect_ssh()
    try:
        if args.setup_dir:
            setup_remote_dir(client, args.remote_dir)
        uploaded = upload_files(client, local_dir, args.remote_dir, args.quiet)
    finally:
        client.close()

    print(f"Done: uploaded={uploaded}, remote_dir={args.remote_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
