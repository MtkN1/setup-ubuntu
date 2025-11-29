# .bash_profile

# Get the aliases and functions
if [ -f ~/.profile ]; then
    . ~/.profile
fi

# User specific aliases and functions
if [ -d ~/.bashrc.d ]; then
    for rc in ~/.bashrc.d/*; do
        if [ -f "$rc" ]; then
            . "$rc"
        fi
    done
fi
unset rc

# User specific environment and startup programs
cdtemp() {
    local dir
    if dir=$(mktemp -d); then
        cd "$dir"
        pwd
    else
        return "$?"
    fi
}

cdvtemp() {
    local dir
    if dir=$(mktemp -d -p /var/tmp); then
        cd "$dir"
        pwd
    else
        return "$?"
    fi
}
