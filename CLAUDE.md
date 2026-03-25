# Brief general description
This repository holds various dockerfiles and devcontainer specification folders for various purposes. I've categorized them into three categories: CLI tools, meant to be run with docker run; webservers, meant to expose an interactive webpage/app on a forwarded port; and devcontainers, which are devcontainer specification folders (devcontainer.json plus optional scripts and dockerfiles).

# Coding guidelines

## Test file locations for docker test runs
- Don't map /tmp to docker containers for testing. In fact, don't map anything outside the directory you're working in. Instead, create test folders within the current directory and map those. You can make persistent test files or just make temporary ones and then clear them, whichever seems most appropriate for a given project.