#!/bin/sh
# GIT_ASKPASS helper: git asks for the password on stdin-less prompts and gets
# the fine-grained PAT from the run's environment file. The token is never
# written to a remote URL, a config file, or the journal.
echo "${GH_PAT:?GH_PAT is not set — add it to the file named by SCOUT_PRODUCTION_ENV (see deploy/local/scout-production.env.example)}"
