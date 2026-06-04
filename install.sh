#!/usr/bin/env sh
set -eu

repo_url="${MAM_REPO_URL:-https://github.com/lkhung09/mcp-agent-manager.git}"
install_dir="${MAM_INSTALL_DIR:-$HOME/.local/share/mcp-agent-manager}"
branch="${MAM_BRANCH:-main}"
required_packages="bash git python3 jq zip ruby"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'mcp-agent-manager install: missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

need_cmd sh

install_missing_packages() {
  missing=""
  for cmd in git python3 jq zip ruby bash; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing="$missing $cmd"
    fi
  done

  if [ -z "$missing" ]; then
    return 0
  fi

  if command -v apt-get >/dev/null 2>&1; then
    printf 'mcp-agent-manager install: installing missing packages:%s\n' "$missing"
    if [ "$(id -u)" = "0" ]; then
      apt-get update
      apt-get install -y $required_packages
    elif command -v sudo >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y $required_packages
    else
      printf 'mcp-agent-manager install: sudo not found. Run as root or install manually:\n' >&2
      printf '  apt-get update && apt-get install -y%s\n' " $required_packages" >&2
      exit 1
    fi
    return 0
  fi

  printf 'mcp-agent-manager install: missing required commands:%s\n' "$missing" >&2
  printf 'Install dependencies manually, then rerun this installer.\n' >&2
  exit 1
}

install_missing_packages
need_cmd git

parent_dir="$(dirname "$install_dir")"
mkdir -p "$parent_dir"

if [ -d "$install_dir/.git" ]; then
  printf 'mcp-agent-manager install: updating %s\n' "$install_dir"
  git -C "$install_dir" fetch --quiet origin "$branch"
  git -C "$install_dir" checkout --quiet "$branch"
  git -C "$install_dir" pull --ff-only --quiet origin "$branch"
elif [ -e "$install_dir" ]; then
  printf 'mcp-agent-manager install: install dir exists and is not a git repo: %s\n' "$install_dir" >&2
  printf 'Set MAM_INSTALL_DIR to another path or move the existing directory.\n' >&2
  exit 1
else
  printf 'mcp-agent-manager install: cloning %s\n' "$repo_url"
  git clone --quiet --branch "$branch" "$repo_url" "$install_dir"
fi

if [ ! -x "$install_dir/bin/mcp-agent-manager" ]; then
  printf 'mcp-agent-manager install: CLI not found after clone: %s\n' "$install_dir/bin/mcp-agent-manager" >&2
  exit 1
fi

"$install_dir/bin/mcp-agent-manager" install --apply

printf '\nmcp-agent-manager install: done\n'
printf 'If this terminal cannot find the command yet, run:\n'
printf '  source "$HOME/.bashrc"  # bash on Ubuntu\n'
printf '  source "$HOME/.zshrc"   # zsh on macOS\n'
printf '  mcp-agent-manager doctor\n'
