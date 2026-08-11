"""logger.py — file + stdout logger for the Lyra services.

Replaces the bare module-level open() in cerebro_maestro.py whose handle was
never closed (file descriptor leak). close() is registered with atexit so the
handle is always released on process exit.
"""

import atexit


class Logger:
    """Callable logger: writes each message to a file and to stdout.

    Why a class and not logging.Logger: the project logs are read live by the
    launcher (tail on maestro.log) and need line-buffered plain text with zero
    formatting — stdlib logging adds handlers/formatters we don't want, and
    the previous bare-function approach leaked the file descriptor.
    """

    def __init__(self, path: str):
        self._f = open(path, "w", encoding="utf-8")
        atexit.register(self.close)  # guaranteed cleanup on process exit

    def __call__(self, msg: object = "") -> None:
        """Write msg to the log file and stdout with immediate flush."""
        try:
            self._f.write(str(msg) + "\n")
            self._f.flush()
        except ValueError:
            pass  # file already closed during interpreter shutdown
        try:
            print(msg, flush=True)
        except Exception:
            pass  # console may reject non-encodable chars on Windows

    def close(self) -> None:
        """Close the underlying file handle. Idempotent."""
        if not self._f.closed:
            self._f.close()
