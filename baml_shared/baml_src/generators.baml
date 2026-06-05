// Generator configuration for the shared BAML contracts.
// Outputs type-safe Python client code to baml_shared/baml_client/.
//
// The TypeScript generator (output to ../../baml_client_ts) was removed
// per the ADR-0017 inversion: the frontend now ADVERTISES the archetypes
// it can render via cortex-ui/src/registry/frontendCapabilities.ts and
// cortex-bff's /register_frontend_capabilities. The backend no longer
// pushes enum definitions over the wire, so the TS client became
// write-only. cortex-ui's SemanticInterpreter.tsx maintains its own
// archetype switch and does not import from BAML. If you ever need a
// TypeScript service to talk BAML again (e.g. a Node-based gateway),
// re-add the typescript generator block here and re-run baml-cli
// generate.

generator target {
  output_type "python/pydantic"
  output_dir "../baml_client"
  version "0.219.0"
}
