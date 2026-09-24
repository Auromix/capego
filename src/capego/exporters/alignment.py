"""Bounded nearest-neighbor alignment without interpolation."""

import numpy as np


def nearest(times, targets, tolerance_ns):
    times, targets = np.asarray(times, dtype=np.int64), np.asarray(targets, dtype=np.int64)
    if not len(times):
        return np.zeros(len(targets), dtype=np.int64), np.zeros(len(targets), dtype=bool)
    upper = np.searchsorted(times, targets).clip(0, len(times) - 1)
    lower = (upper - 1).clip(0)
    indices = np.where(abs(times[lower] - targets) <= abs(times[upper] - targets), lower, upper)
    return indices, abs(times[indices] - targets) <= tolerance_ns
