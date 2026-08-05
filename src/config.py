"""Central, reviewable runtime configuration for the chatbot."""

# The assignment permits models of at most 10B parameters.  Keep this explicit
# in source (rather than in .env) so the selected model is auditable.
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.2-3b-instruct"
MODEL_PARAMETER_SIZE = "3B"
OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
