#!/bin/bash
# entrypoint.sh

# 1. Start a new detached tmux session named 'auto-session'
tmux new-session -d -s auto-session

# 2. Split the window vertically to create the second pane
# 'auto-session:0' refers to the session, and the first window (index 0)
tmux split-window -v -t auto-session:0

# 3. Send the command for the first pane (top/left pane: index 0.0)
# 'C-m' is the key sequence for 'Enter'
tmux send-keys -t auto-session:0.0 "python3 /primer3plus/server/server.py" C-m

# 4. Send the command for the second pane (bottom/right pane: index 0.1)
tmux send-keys -t auto-session:0.1 "cd /primer3plus/client && npm run dev" C-m

# 5. Detach the session. The container process will remain running
# as long as the tmux session (and the commands within it) are active.
# This prevents the container from exiting immediately.
tmux detach -s auto-session

echo "TMUX session 'auto-session' started and detached. Container is now running in the background."

# This final command is essential. It keeps the entrypoint.sh script (and thus the
# container's main process) running indefinitely in the background so Docker doesn't
# immediately shut down the container after the script finishes.
# You can use 'tail -f /dev/null' or 'sleep infinity' if available.
# We'll use a long sleep to ensure the container stays alive.
sleep infinity