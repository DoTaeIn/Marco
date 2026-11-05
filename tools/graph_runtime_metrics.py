"""Generic host resource measurement around one callable.

No files, logs, subprocesses, network or domain logic. Caller owns artifacts.
"""

import sys
import time

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX hosts
    resource = None

PEAK_RSS_SCOPE = "whole-process-high-water-not-stage-delta"


def _rss_multiplier(platform):
    if platform == "darwin":
        return 1
    if platform.startswith("linux"):
        return 1024
    raise ValueError("unsupported platform for ru_maxrss units: %r" % (platform,))


def measure(callable_, *args, **kwargs):
    """Call once; return the original value plus process-level metrics.

    peak_rss_bytes is the whole-process high-water mark (RUSAGE_SELF,
    children excluded), not memory attributable to this call.
    """
    platform = sys.platform
    multiplier = _rss_multiplier(platform)
    if resource is None:
        raise ValueError("resource module unavailable on %r" % (platform,))
    before = resource.getrusage(resource.RUSAGE_SELF)
    start = time.perf_counter()
    value = callable_(*args, **kwargs)
    end = time.perf_counter()
    after = resource.getrusage(resource.RUSAGE_SELF)
    metrics = {
        "wall_seconds": float(max(0.0, end - start)),
        "cpu_user_seconds": float(max(0.0, after.ru_utime - before.ru_utime)),
        "cpu_system_seconds": float(max(0.0, after.ru_stime - before.ru_stime)),
        "peak_rss_bytes": int(after.ru_maxrss) * multiplier,
        "peak_rss_scope": PEAK_RSS_SCOPE,
        "platform": platform,
    }
    return {"value": value, "metrics": metrics}
