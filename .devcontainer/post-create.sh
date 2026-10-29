#!/usr/bin/env bash
set -euo pipefail

# 1. git workspace ownership
git config --global --add safe.directory "${PWD}"

# 2. python environment via native uv workflow
uv sync --all-groups

# 3. oh-my-zsh plugins (defined in .zshrc and .zshrc points to ZSH_CUSTOM="$HOME/.zsh/custom")
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

# 4. dotfiles repository acquisition
DOTFILES_DIR="${HOME}/dotfiles"
if [ ! -d "${DOTFILES_DIR}" ]; then
    # Use HTTPS to avoid unauthenticated SSH key aborts inside containers
    git clone https://github.com/somagaze/muhdohts.git "${DOTFILES_DIR}"
fi

# 5. clear collision targets and link
rm -f "${HOME}/.zshrc"
stow -d "${DOTFILES_DIR}" -t "${HOME}" zsh
