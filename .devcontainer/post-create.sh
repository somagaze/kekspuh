#!/usr/bin/env bash
set -euo pipefail

# 1. Determine script directory and resolve project root dynamically
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(dirname "${SCRIPT_DIR}")"

# 2. git workspace ownership
git config --global --add safe.directory "${WORKSPACE_DIR}"

# 3. python environment via native uv workflow
cd "${WORKSPACE_DIR}"
uv sync --all-groups

# 4. oh-my-zsh plugins
CUSTOM_PLUGIN_DIR="${HOME}/.zsh/custom/plugins"
mkdir -p "${CUSTOM_PLUGIN_DIR}"

if [ ! -d "${CUSTOM_PLUGIN_DIR}/zsh-syntax-highlighting" ]; then
    git clone --depth=1 https://github.com/zsh-users/zsh-syntax-highlighting.git \
        "${CUSTOM_PLUGIN_DIR}/zsh-syntax-highlighting"
fi

if [ ! -d "${CUSTOM_PLUGIN_DIR}/zsh-autosuggestions" ]; then
    git clone --depth=1 https://github.com/zsh-users/zsh-autosuggestions.git \
        "${CUSTOM_PLUGIN_DIR}/zsh-autosuggestions"
fi

# 5. dotfiles repository acquisition
DOTFILES_DIR="${HOME}/dotfiles"
if [ ! -d "${DOTFILES_DIR}" ]; then
    git clone https://github.com/somagaze/muhdohts.git "${DOTFILES_DIR}"
fi

# 6. clear collision targets and link
rm -f "${HOME}/.zshrc"
stow -d "${DOTFILES_DIR}" -t "${HOME}" zsh