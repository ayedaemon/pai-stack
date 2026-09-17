#!/bin/bash
set -e

# Tool input is passed via TOOL_INPUT env var as JSON
input_json="$TOOL_INPUT"

task_prompt=$(echo "$input_json" | jq -r '.task_prompt')
worktree_dir=$(echo "$input_json" | jq -r '.worktree_dir')
session_id=$(echo "$input_json" | jq -r '.session_id')
is_resume=$(echo "$input_json" | jq -r '.is_resume')

# Default is_resume to false if null
if [ "$is_resume" = "null" ]; then
    is_resume="false"
fi

# Construct the opencode command
if [ "$is_resume" = "true" ]; then
    SESSION_FLAG="--session"
else
    SESSION_FLAG="--title"
fi

echo "Delegating task to OpenCode..."
echo "Worktree: $worktree_dir"
echo "Session: $session_id"
echo "Prompt: $task_prompt"

# Execute in the opencode container
# We use docker exec from the MCP server container since it has /var/run/docker.sock mounted
docker exec -w "$worktree_dir" opencode opencode run "$task_prompt" $SESSION_FLAG "$session_id" --auto

echo "OpenCode task completed."
