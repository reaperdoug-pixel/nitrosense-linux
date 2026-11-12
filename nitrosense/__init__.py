"""NitroSense for Linux - Acer Nitro control center (fan, lighting, power, monitoring)."""

__version__ = "2.0.0"

APP_ID = "io.github.napejoon.NitroSense"


def set_process_name(name: str) -> None:
    """Show `name` instead of python3 in ps/top/System Monitor (Linux PR_SET_NAME)."""
    try:
        import ctypes
        libc = ctypes.CDLL(None)
        libc.prctl(15, name.encode()[:15], 0, 0, 0)
    except (OSError, AttributeError):
        pass
