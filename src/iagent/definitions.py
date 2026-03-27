import sys
try:
    import pysqlite3
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

from dagster import Definitions, load_assets_from_modules
from .defs import agent_routers, dynamic_supervisor, data_layer, dynamic_factory

# Load assets explicitly from modules to Ensure they are visible in the UI
all_assets = load_assets_from_modules([
    agent_routers,
    dynamic_supervisor,
    data_layer,
    dynamic_factory
])

# Load all jobs from the defs sub-package
# Note: load_from_defs_folder is also an option, but we want 
# to ensure everything is explicitly wired.

defs = Definitions(
    assets=all_assets,
    jobs=[
        dynamic_supervisor.supervisor_query_job,
    ] + dynamic_factory.build_dynamic_jobs(),
)
