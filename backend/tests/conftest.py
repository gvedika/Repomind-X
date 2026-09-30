# On Windows, torch must initialise its DLLs before pyarrow/polars (pulled in by mteb/datasets) are imported.
try:
    import torch  # noqa: F401
except Exception:  # torch is optional for most unit tests
    pass
