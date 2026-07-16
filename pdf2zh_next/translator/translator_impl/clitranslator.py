import hashlib
import logging
import os
import shlex
import subprocess
from pathlib import Path
from shutil import which

from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.config.translate_engine_model import CLISettings
from pdf2zh_next.translator.base_rate_limiter import BaseRateLimiter
from pdf2zh_next.translator.base_translator import BaseTranslator
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential

logger = logging.getLogger(__name__)

# Flags whose following argv value is a local file that affects translation.
_CACHE_FILE_FLAGS = ("--glossary", "--proper-nouns")


def _file_content_fingerprint(path: str) -> str:
    """SHA-256 of file contents (or a stable marker if unreadable).

    Used so cache keys change when glossary/proper-nouns content changes
    even if the path (and thus the command string) stays the same.
    """
    p = Path(path)
    try:
        if not p.is_file():
            return f"missing:{path}"
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return f"{path}:{h.hexdigest()}"
    except OSError as e:
        return f"error:{path}:{type(e).__name__}"


def _collect_cache_file_paths(
    cli_settings: CLISettings, command_parts: list[str]
) -> list[str]:
    """Glossary / proper-nouns paths from settings fields and/or argv flags."""
    seen: set[str] = set()
    paths: list[str] = []

    def _add(raw: str | None) -> None:
        if not raw:
            return
        path = raw.strip()
        if not path or path in seen:
            return
        seen.add(path)
        paths.append(path)

    _add(cli_settings.clitranslator_glossary)
    _add(cli_settings.clitranslator_proper_nouns)

    # Legacy full command / extra_args may pass the same flags.
    i = 0
    while i < len(command_parts):
        part = command_parts[i]
        if part in _CACHE_FILE_FLAGS and i + 1 < len(command_parts):
            _add(command_parts[i + 1])
            i += 2
            continue
        for flag in _CACHE_FILE_FLAGS:
            prefix = f"{flag}="
            if part.startswith(prefix):
                _add(part[len(prefix) :])
                break
        i += 1

    return paths


class CLITranslatorTranslator(BaseTranslator):
    """CLI translator that calls an external tool via stdin → stdout.

    Prefer decomposed CLISettings fields (program, script, glossary, urls, …)
    so the GUI can show them like other engines. A legacy full
    ``clitranslator_command`` string still overrides when set.

    Example (deeplx adapter)::

        program: python3
        script: /root/.config/pdf2zh/deeplx/deeplx.py
        glossary: /root/.config/pdf2zh/glossaries/sextips.csv
        proper_nouns: /root/.config/pdf2zh/glossaries/proper_nouns.csv
        urls: one DeepLX endpoint per line
    """

    name = "clitranslator"

    def __init__(
        self,
        settings: SettingsModel,
        rate_limiter: BaseRateLimiter,
    ):
        super().__init__(settings, rate_limiter)
        cli_settings = settings.translate_engine_settings
        if not isinstance(cli_settings, CLISettings):
            raise TypeError(
                f"Expected CLISettings, got {type(cli_settings).__name__}"
            )

        try:
            command_parts = cli_settings.build_command_parts()
        except ValueError as e:
            raise ValueError(f"Invalid CLI translator settings: {e}") from e
        if not command_parts:
            raise ValueError(
                "CLI program is required. Fill program/script (or full command)."
            )

        self.command_string = cli_settings.build_command_string()
        self.command = command_parts[0]
        self.args = command_parts[1:]
        self.timeout = cli_settings.resolved_timeout()
        self.postprocess_command_string = cli_settings.clitranslator_postprocess_command
        self.postprocess_command = None
        if self.postprocess_command_string:
            try:
                postprocess_parts = shlex.split(self.postprocess_command_string)
            except ValueError as e:
                raise ValueError(
                    f"Invalid clitranslator_postprocess_command: {e}"
                ) from e
            if not postprocess_parts:
                raise ValueError("clitranslator_postprocess_command cannot be empty")
            self.postprocess_command = postprocess_parts

        # Cache distinguishes command line + timeout + glossary file *contents*
        # (path-only keys miss updates when CSV content changes in place).
        self.add_cache_impact_parameters("clitranslator_command", self.command_string)
        self.add_cache_impact_parameters("clitranslator_timeout", self.timeout)
        if self.postprocess_command_string:
            self.add_cache_impact_parameters(
                "clitranslator_postprocess_command", self.postprocess_command_string
            )
        for path in _collect_cache_file_paths(cli_settings, command_parts):
            fp = _file_content_fingerprint(path)
            self.add_cache_impact_parameters(f"clitranslator_file:{path}", fp)
            logger.debug("CLITranslator cache file fingerprint %s -> %s", path, fp)

        # Best-effort availability check (does not assume --version support).
        self._test_command(self.command, label="CLI")
        if self.postprocess_command:
            self._test_command(self.postprocess_command[0], label="Postprocess")

        logger.info(
            "CLITranslator ready: cmd=%r timeout=%ss",
            self.command_string,
            self.timeout,
        )

    def _test_command(self, command: str, label: str):
        """Validate that the command is executable or discoverable on PATH."""
        cmd_path = Path(command)
        if cmd_path.is_absolute() or cmd_path.parent != Path():
            if not cmd_path.exists():
                raise ValueError(
                    f"{label} command '{command}' not found. "
                    f"Please ensure it's installed and in your PATH."
                )
            if not os.access(cmd_path, os.X_OK):
                raise ValueError(
                    f"{label} command '{command}' is not executable. "
                    f"Please check permissions."
                )
            return

        resolved = which(command)
        if not resolved:
            raise ValueError(
                f"{label} command '{command}' not found. "
                f"Please ensure it's installed and in your PATH."
            )

    @retry(
        retry=retry_if_exception_type(
            (subprocess.CalledProcessError, subprocess.TimeoutExpired)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_translate(self, text, rate_limit_params: dict = None) -> str:
        """Execute translation using the configured CLI tool"""

        cmd = [self.command] + self.args

        try:
            logger.debug(f"Executing CLI command: {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            stdout, stderr = process.communicate(input=text, timeout=self.timeout)

            if process.returncode != 0:
                logger.error(
                    "CLI command failed (exit %s): %s", process.returncode, stderr
                )
                raise subprocess.CalledProcessError(
                    process.returncode,
                    cmd,
                    output=stdout,
                    stderr=stderr,
                )

            output = stdout
            if self.postprocess_command:
                output = self._run_postprocess(output)

            return output.strip()

        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise

    def _run_postprocess(self, output: str) -> str:
        """Run postprocess command on CLI output."""
        if not self.postprocess_command:
            return output

        try:
            process = subprocess.Popen(
                self.postprocess_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            stdout, stderr = process.communicate(input=output, timeout=self.timeout)
            if process.returncode != 0:
                logger.error(
                    "Postprocess command failed (exit %s): %s",
                    process.returncode,
                    stderr,
                )
                raise subprocess.CalledProcessError(
                    process.returncode,
                    self.postprocess_command,
                    output=stdout,
                    stderr=stderr,
                )
            return stdout
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
