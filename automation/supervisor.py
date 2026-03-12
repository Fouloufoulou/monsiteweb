#!/usr/bin/env python3
"""Supervisor orchestrating Flowbird scenarios with retries and notifications.

The supervisor retains the behaviour of the legacy script while introducing a
clearer structure, stronger logging and safer locking primitives.  Scenarios are
executed sequentially and each run reports its status both locally and through
Telegram (when configured).
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import logging
import os
import shlex
import subprocess
import sys
import textwrap
import time
from collections import deque
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

LOCAL_TZ = dt.datetime.now().astimezone().tzinfo or dt.timezone.utc
DEFAULT_BASE_DIR = Path(os.environ.get("FLOWBIRD_BASE_DIR", "/root/scenario"))
DEFAULT_LOG_FILE = "supervisor.log"
DEFAULT_SCENARIO_GLOB = "*3"
DEFAULT_DISPLAY = os.environ.get("DISPLAY", ":99")
TAIL_LINES = 25
EXIT_OK = 0
RETRY_DELAY = dt.timedelta(seconds=3)
LOCK_STALE_AFTER = dt.timedelta(minutes=30)
TELEGRAM_CHUNK = 3500  # Stay well below Telegram limits


@dataclasses.dataclass(frozen=True)
class ScenarioPaths:
    """Convenience wrapper exposing key files within a scenario directory."""

    scenario_dir: Path

    @property
    def flowbird(self) -> Path:
        return self.scenario_dir / "flowbird.py"

    @property
    def logs_dir(self) -> Path:
        return self.scenario_dir / "logs"

    @property
    def next_run_txt(self) -> Path:
        return self.logs_dir / "next_run.txt"

    @property
    def next_run_json(self) -> Path:
        return self.logs_dir / "next_run.json"

    @property
    def lock_file(self) -> Path:
        return self.scenario_dir / ".supervisor.lock"

    @property
    def chrome_profile(self) -> Path:
        return self.scenario_dir / "chrome_profile"

    @property
    def config(self) -> Path:
        return self.scenario_dir / "scenario.conf"


class TelegramNotifier:
    """Tiny wrapper around the notify_telegram helper script."""

    def __init__(self, base_dir: Path, python: str, enabled: bool = True) -> None:
        self._notify_script = base_dir / "notify_telegram.py"
        self._conf_path = base_dir / "telegram.conf"
        self._python = python
        self._enabled = enabled and self._notify_script.is_file() and self._conf_path.is_file()
        if not self._enabled:
            logging.info(
                "Telegram notifications disabled (script or config missing in %s)",
                base_dir,
            )

    def send(self, message: str) -> None:
        if not self._enabled:
            return
        for chunk in _chunk_message(message, TELEGRAM_CHUNK):
            try:
                subprocess.run(
                    [self._python, str(self._notify_script), str(self._conf_path), chunk],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                logging.exception(
                    "Telegram notification failed with exit code %s: %s",
                    exc.returncode,
                    exc.stderr,
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logging.exception("Unexpected Telegram failure: %s", exc)


def _chunk_message(message: str, size: int) -> Iterator[str]:
    message = message or ""
    if len(message) <= size:
        yield message
        return
    for start in range(0, len(message), size):
        yield message[start : start + size]


class FileLock:
    """Minimal file-based lock with stale detection."""

    def __init__(self, path: Path, stale_after: dt.timedelta) -> None:
        self._path = path
        self._stale_after = stale_after
        self._acquired = False

    def acquire(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            stat = None
        except OSError as exc:
            logging.warning("Unable to stat lock %s: %s", self._path, exc)
            return False

        if stat is not None:
            age = now - stat.st_mtime
            if age > self._stale_after.total_seconds():
                logging.warning("Removing stale lock %s (age %.0fs)", self._path, age)
                try:
                    self._path.unlink()
                except OSError as exc:
                    logging.error("Unable to unlink stale lock %s: %s", self._path, exc)
                    return False
            else:
                return False

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(self._path, flags)
        except FileExistsError:
            return False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(f"{os.getpid()}\n{dt.datetime.now(dt.timezone.utc).isoformat()}\n")
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        self._acquired = True
        return True

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logging.error("Unable to remove lock %s: %s", self._path, exc)
        finally:
            self._acquired = False

    def __enter__(self) -> "FileLock":
        if not self.acquire():
            raise RuntimeError("Unable to acquire scenario lock")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


@dataclasses.dataclass
class RunResult:
    returncode: int
    log_tail: str
    log_path: Optional[Path]

    @property
    def ok(self) -> bool:
        return self.returncode == EXIT_OK


class ScenarioRunner:
    """Handle the execution lifecycle of a single scenario."""

    def __init__(
        self,
        paths: ScenarioPaths,
        python: str,
        display: str = DEFAULT_DISPLAY,
        tail_lines: int = TAIL_LINES,
    ) -> None:
        self.paths = paths
        self.python = python
        self.display = display
        self.tail_lines = tail_lines
        self.lock = FileLock(paths.lock_file, LOCK_STALE_AFTER)

    @property
    def name(self) -> str:
        return self.paths.scenario_dir.name

    # ------------------------------------------------------------------
    # Reading schedule information
    # ------------------------------------------------------------------
    def next_run(self) -> Optional[dt.datetime]:
        json_dt = self._read_next_run_json()
        if json_dt:
            return json_dt
        return self._read_next_run_txt()

    def _read_next_run_json(self) -> Optional[dt.datetime]:
        path = self.paths.next_run_json
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logging.error("[%s] Invalid JSON in %s: %s", self.name, path, exc)
            return None
        epoch = data.get("epoch")
        if epoch in (None, "", 0):
            return None
        try:
            epoch_f = float(epoch)
        except (TypeError, ValueError):
            logging.error("[%s] Invalid epoch value in %s: %r", self.name, path, epoch)
            return None
        if epoch_f <= 0:
            return None
        return dt.datetime.fromtimestamp(epoch_f, tz=dt.timezone.utc).astimezone(LOCAL_TZ)

    def _read_next_run_txt(self) -> Optional[dt.datetime]:
        path = self.paths.next_run_txt
        if not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            logging.error("[%s] Unable to read %s: %s", self.name, path, exc)
            return None
        content = content.replace("\ufeff", "").strip()
        if not content:
            return None
        for parser in (self._parse_isoformat, self._parse_default):
            parsed = parser(content)
            if parsed:
                return parsed
        logging.error("[%s] Unable to parse timestamp %r in %s", self.name, content, path)
        return None

    def _parse_isoformat(self, value: str) -> Optional[dt.datetime]:
        try:
            return _ensure_tz(dt.datetime.fromisoformat(value))
        except ValueError:
            return None

    def _parse_default(self, value: str) -> Optional[dt.datetime]:
        try:
            naive = dt.datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        return _ensure_tz(naive)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run(self, notifier: TelegramNotifier) -> None:
        if not self.paths.flowbird.is_file():
            logging.info("[%s] flowbird.py missing, skipping", self.name)
            return

        schedule = self.next_run()
        if schedule and dt.datetime.now(LOCAL_TZ) < schedule:
            logging.info("[%s] Next run scheduled at %s, skipping", self.name, schedule)
            return

        if not self.lock.acquire():
            logging.info("[%s] Lock present, skipping", self.name)
            return

        try:
            first = self._execute_once()
            if first.ok:
                self._handle_success(notifier, first, retry=False)
                return

            logging.warning("[%s] Initial run failed (code %s), retrying once", self.name, first.returncode)
            time.sleep(RETRY_DELAY.total_seconds())
            second = self._execute_once()
            if second.ok:
                self._handle_success(notifier, second, retry=True)
                return

            self._handle_failure(notifier, first, second)
        finally:
            self.lock.release()

    def _execute_once(self) -> RunResult:
        env = os.environ.copy()
        env.setdefault("DISPLAY", self.display)
        cmd: Sequence[str] = (
            self.python,
            str(self.paths.flowbird),
            "--headed",
            "--profile-dir",
            str(self.paths.chrome_profile),
            "--config",
            str(self.paths.config),
        )
        cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
        logging.info("[%s] Launching: %s", self.name, cmd_str)
        completed = subprocess.run(cmd, cwd=self.paths.scenario_dir, env=env)
        log_path = self._latest_flowbird_log()
        tail = self._tail_log(log_path)
        return RunResult(completed.returncode, tail, log_path)

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------
    def _latest_flowbird_log(self) -> Optional[Path]:
        try:
            logs = list(self.paths.logs_dir.glob("acheter_*.log"))
        except OSError as exc:
            logging.error("[%s] Unable to list logs: %s", self.name, exc)
            return None
        if not logs:
            return None
        return max(logs, key=lambda p: p.stat().st_mtime)

    def _tail_log(self, path: Optional[Path]) -> str:
        if not path or not path.is_file():
            return ""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                return "".join(deque(fh, maxlen=self.tail_lines))
        except OSError as exc:
            logging.error("[%s] Unable to read %s: %s", self.name, path, exc)
            return ""

    def _handle_success(self, notifier: TelegramNotifier, result: RunResult, retry: bool) -> None:
        status = "🟡" if retry else "✅"
        retry_txt = " après retry" if retry else ""
        notifier.send(f"{status} {self.name}: run OK{retry_txt} (exit=0)")
        if result.log_tail:
            self._send_log(notifier, result.log_tail, suffix=" retry" if retry else "")
        logging.info("[%s] Completed successfully%s", self.name, retry_txt)

    def _handle_failure(self, notifier: TelegramNotifier, first: RunResult, second: RunResult) -> None:
        notifier.send(
            f"❌ {self.name}: échec (exit={first.returncode} puis {second.returncode})"
        )
        tail = second.log_tail or first.log_tail
        if tail:
            self._send_log(notifier, tail, suffix=" fin")
        logging.error(
            "[%s] Failed twice (exit codes %s/%s)",
            self.name,
            first.returncode,
            second.returncode,
        )

    def _send_log(self, notifier: TelegramNotifier, content: str, suffix: str = "") -> None:
        formatted = textwrap.dedent(
            f"""
            🧾 {self.name} log{suffix}:
            ```
            {content.rstrip()}
            ```
            """
        ).strip()
        notifier.send(formatted)


class ScenarioSupervisor:
    """Discover and execute scenarios within a base directory."""

    def __init__(
        self,
        base_dir: Path,
        python: str,
        scenario_glob: str = DEFAULT_SCENARIO_GLOB,
        tail_lines: int = TAIL_LINES,
    ) -> None:
        self.base_dir = base_dir
        self.python = python
        self.scenario_glob = scenario_glob
        self.tail_lines = tail_lines
        self.notifier = TelegramNotifier(base_dir, python)

    def discover(self) -> Iterable[ScenarioRunner]:
        if not self.base_dir.is_dir():
            logging.error("Base directory %s does not exist or is not a directory", self.base_dir)
            return []
        paths = sorted(p for p in self.base_dir.glob(self.scenario_glob) if p.is_dir())
        return [
            ScenarioRunner(ScenarioPaths(path), python=self.python, tail_lines=self.tail_lines)
            for path in paths
        ]

    def run(self) -> int:
        runners = list(self.discover())
        if not runners:
            logging.warning("No scenario found under %s using glob %r", self.base_dir, self.scenario_glob)
            return 0
        for runner in runners:
            try:
                runner.run(self.notifier)
            except Exception:  # pragma: no cover - defensive logging
                logging.exception("Unhandled error while processing %s", runner.name)
        return 0


# ----------------------------------------------------------------------
# Helper functions and CLI
# ----------------------------------------------------------------------

def _ensure_tz(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def _configure_logging(log_file: Path, verbose: bool) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(log_file, encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supervisor for Flowbird scenarios")
    parser.add_argument("--base-dir", default=DEFAULT_BASE_DIR, type=Path, help="Root directory containing scenarios")
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE, type=Path, help="Supervisor log filename")
    parser.add_argument("--scenario-glob", default=DEFAULT_SCENARIO_GLOB, help="Glob used to discover scenarios")
    parser.add_argument("--tail-lines", type=int, default=TAIL_LINES, help="Number of log lines to forward")
    parser.add_argument("--python", default=sys.executable or "python3", help="Python executable to run scenarios")
    parser.add_argument("--verbose", action="store_true", help="Also log to stdout")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    base_dir = args.base_dir
    if not base_dir.is_absolute():
        base_dir = (Path.cwd() / base_dir).resolve()
    log_file = args.log_file
    if not log_file.is_absolute():
        log_file = (base_dir / log_file).resolve()
    _configure_logging(log_file, verbose=args.verbose)
    logging.info("Starting supervisor in %s (glob=%s)", base_dir, args.scenario_glob)
    supervisor = ScenarioSupervisor(
        base_dir=base_dir,
        python=args.python,
        scenario_glob=args.scenario_glob,
        tail_lines=args.tail_lines,
    )
    return supervisor.run()


if __name__ == "__main__":
    sys.exit(main())
