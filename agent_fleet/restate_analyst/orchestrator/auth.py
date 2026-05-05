import contextvars

# Holds the JWT (Authorization header) for the current async request lifecycle
current_user_token = contextvars.ContextVar("current_user_token", default=None)

# Holds the unified Trace ID for Langfuse and downstream logs
current_trace_id = contextvars.ContextVar("current_trace_id", default=None)
