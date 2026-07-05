#!/usr/bin/env bash
# One-liner dry-run demo. Runs Front Desk + Scout on the bundled synthetic
# targets, with zero API keys required. Skips Drafter/Outbox.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m outreach_desk.pipeline --target-type academic --limit 3 --dry-run
