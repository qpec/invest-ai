#!/bin/sh
# GIT_ASKPASS helper: git asks for the password on stdin-less prompts and gets
# the fine-grained PAT from the unit's EnvironmentFile. The token is never
# written to a remote URL, a config file, or the journal.
echo "${GH_PAT:?GH_PAT is not set — fill /etc/stock-agentcy/scout.env}"
