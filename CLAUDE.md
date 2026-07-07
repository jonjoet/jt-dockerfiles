# Brief general description
This repository holds various dockerfiles, devcontainer specification folders, background services, and standalone browser tools for various purposes. I've categorized them into five categories: CLI tools, meant to be run with docker run; webservers, meant to expose an interactive webpage/app on a forwarded port; devcontainers, which are devcontainer specification folders (devcontainer.json plus optional scripts and dockerfiles); services, which are long-running or scheduled background jobs meant to run unattended on a VM (e.g. as a systemd service/timer, shipping a setup guide in place of a Dockerfile); and standalone HTML, single-file JavaScript apps that run in the browser without installation.

# Coding guidelines

## Test file locations for docker test runs
- Don't map /tmp to docker containers for testing. In fact, don't map anything outside the directory you're working in. Instead, create test folders within the current directory and map those. You can make persistent test files or just make temporary ones and then clear them, whichever seems most appropriate for a given project.