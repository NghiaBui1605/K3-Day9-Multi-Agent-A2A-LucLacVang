"""Central, reviewable runtime configuration for the chatbot."""

# The assignment permits models of at most 10B parameters.  Keep this explicit
# in source (rather than in .env) so the selected model is auditable.
DEFAULT_OPENROUTER_MODEL = "qwen/qwen3-8b"
MODEL_PARAMETER_SIZE = "8.2B"
OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
