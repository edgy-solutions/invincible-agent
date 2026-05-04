// Generator configuration for the shared BAML contracts.
// Outputs type-safe Python client code to baml_shared/baml_client/.

generator target {
  output_type "python/pydantic"
  output_dir "../baml_client"
  version "0.219.0"
}

generator typescript_target {
  output_type "typescript"
  output_dir "../../baml_client_ts"
  version "0.219.0"
}
