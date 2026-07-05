"""Centralized model IDs and other constants.

Keeping model IDs in one place makes it easy to bump versions without
hunting through the pipeline stages. The source project used the Claude
Haiku 4.5 family for the cheap fact-check validator call and Claude Sonnet
for the higher-quality drafting call -- that split is preserved here.
"""

# Used for the per-target personalization draft (higher quality, one call
# per target).
DRAFT_MODEL = "claude-sonnet-4-6"

# Used for the cheap, fast affiliation fact-check validator that runs after
# every draft attempt.
VALIDATOR_MODEL = "claude-haiku-4-5-20251001"

# Max tokens for each call.
DRAFT_MAX_TOKENS = 500
VALIDATOR_MAX_TOKENS = 80

# Retry budget for the drafter's quality-filter loop.
DEFAULT_MAX_RETRIES = 3
