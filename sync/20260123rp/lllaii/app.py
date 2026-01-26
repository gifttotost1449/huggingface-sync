import os
import pathlib
import signal
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request


BASE_DIR = pathlib.Path(__file__).resolve().parent
BIN_DIR = BASE_DIR / "bin"
BIN_PATH = BIN_DIR / "gpt-load"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"


def log(msg: str) -> None:
    print(f"[gpt-load] {msg}", flush=True)


def download_file(url: str, dest: pathlib.Path) -> None:
    log(f"Downloading {url}")
    with urllib.request.urlopen(url) as resp, dest.open("wb") as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def extract_tarball(tar_path: pathlib.Path, out_dir: pathlib.Path) -> None:
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=out_dir)


def ensure_binary() -> None:
    if BIN_PATH.exists():
        return

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    explicit_url = os.environ.get("GPT_LOAD_DOWNLOAD_URL")
    asset = os.environ.get("GPT_LOAD_ASSET")
    version = os.environ.get("GPT_LOAD_VERSION", "latest")

    if explicit_url:
        urls = [explicit_url]
    else:
        asset_candidates = [
            asset,
            "gpt-load_linux_amd64.tar.gz",
            "gpt-load_linux_amd64.tgz",
            "gpt-load-linux-amd64.tar.gz",
            "gpt-load-linux-amd64.tgz",
            "gpt-load_Linux_x86_64.tar.gz",
            "gpt-load_linux_amd64",
            "gpt-load-linux-amd64",
        ]
        asset_candidates = [a for a in asset_candidates if a]
        base = f"https://github.com/tbphp/gpt-load/releases/{version}/download"
        urls = [f"{base}/{name}" for name in asset_candidates]

    last_err = None
    tmp_path = None
    used_url = None
    for url in urls:
        try:
            filename = pathlib.Path(urllib.parse.urlparse(url).path).name
            if filename.endswith(".tar.gz"):
                tmp_path = BIN_DIR / "gpt-load.tar.gz"
            elif filename.endswith(".tgz"):
                tmp_path = BIN_DIR / "gpt-load.tgz"
            else:
                tmp_path = BIN_DIR / "gpt-load.bin"
            download_file(url, tmp_path)
            used_url = url
            last_err = None
            break
        except urllib.error.HTTPError as err:
            last_err = err
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()
            log(f"Download failed ({err.code}) for {url}")

    if last_err:
        raise RuntimeError(
            "Unable to download gpt-load binary. Set GPT_LOAD_DOWNLOAD_URL "
            "to a valid release asset URL."
        )

    if tmp_path and tmp_path.exists() and (
        used_url.endswith(".tar.gz") or used_url.endswith(".tgz")
    ):
        extract_tarball(tmp_path, BIN_DIR)
        tmp_path.unlink(missing_ok=True)
        candidates = [p for p in BIN_DIR.rglob("gpt-load") if p.is_file()]
        if not candidates:
            raise RuntimeError("gpt-load binary not found after extraction")
        candidates.sort(key=lambda p: len(str(p)))
        candidates[0].replace(BIN_PATH)
    else:
        tmp_path.replace(BIN_PATH)

    BIN_PATH.chmod(BIN_PATH.stat().st_mode | stat.S_IEXEC)
    log(f"Binary ready at {BIN_PATH}")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def validate_env() -> None:
    if not os.environ.get("AUTH_KEY"):
        log("AUTH_KEY is required. Set it in Space variables.")
        sys.exit(1)


def start_gpt_load() -> subprocess.Popen:
    env = os.environ.copy()
    env.setdefault("HOST", "0.0.0.0")
    env.setdefault("PORT", env.get("PORT", "7860"))

    log("Starting gpt-load...")
    return subprocess.Popen([str(BIN_PATH)], env=env)


def main() -> None:
    ensure_dirs()
    validate_env()
    ensure_binary()
    proc = start_gpt_load()

    def handle_signal(signum, _frame):
        log(f"Received signal {signum}, forwarding to gpt-load")
        try:
            proc.send_signal(signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while True:
        ret = proc.poll()
        if ret is not None:
            log(f"gpt-load exited with code {ret}")
            sys.exit(ret)
        time.sleep(1)


if __name__ == "__main__":
    main()
