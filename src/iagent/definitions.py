import sys
try:
    import pysqlite3
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

from dagster import Definitions, load_assets_from_modules
from .defs import agent_routers, dynamic_supervisor, dynamic_factory
from .defs import extraction_review_sensor as _ers

all_assets = load_assets_from_modules([
    agent_routers,
    dynamic_supervisor,
    dynamic_factory
])

# Load all jobs from the defs sub-package
# Note: load_from_defs_folder is also an option, but we want
# to ensure everything is explicitly wired.

defs = Definitions(
    assets=all_assets,
    jobs=[
        dynamic_supervisor.supervisor_query_job,
        _ers.start_review_job,
    ] + dynamic_factory.build_dynamic_jobs(),
    # The extraction->review sensor: canonical trigger turning a completed doc-tools
    # extraction (review.json in MinIO) into a grouped disposition review. Opt-in per
    # environment (default STOPPED); enable in the Dagster UI on the cluster.
    sensors=[_ers.extraction_review_sensor],
)
