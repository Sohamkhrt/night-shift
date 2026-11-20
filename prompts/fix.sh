#!/usr/bin/env bash
# usage: prompts/fix.sh <logname> "<prompt>"  -- runs Kiro (file tools only), then the test suite
K="/c/Users/soham/AppData/Local/Kiro-Cli/run/chat-cli-2.21.4.exe"
timeout 590 "$K" chat --no-interactive --trust-tools=fs_read,fs_write "$2" > "prompts/log-$1.txt" 2>&1
echo "kiro exit $?"; tail -12 "prompts/log-$1.txt"
uv run pytest -q -p no:cacheprovider > .test-output.txt 2>&1
tail -6 .test-output.txt
