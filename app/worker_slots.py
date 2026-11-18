"""Coordinate peak RAM use between untrusted documents and raster rendering.

The production systemd service has MemoryMax=800M. Limiting each kind of
subprocess separately could still run both heavy jobs simultaneously.
This process-local gate is shared across both entrypoints; production uses
one Uvicorn worker. It does not implement a cross-worker/global lock.
"""
import threading

MEMORY_HEAVY_SLOT = threading.BoundedSemaphore(1)
