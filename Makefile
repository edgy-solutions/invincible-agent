# NOTE: `make` is not installed on the Windows dev box; run the script directly:
#   bash scripts/suite-gate.sh [pytest args]
.PHONY: gate
gate:
	bash scripts/suite-gate.sh $(PYTEST_ARGS)
