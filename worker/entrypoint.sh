#!/usr/bin/env bash
set -e
# Start RQ worker that imports worker.process_case
rq worker -u ${REDIS_URL:-redis://redis:6379/0}
