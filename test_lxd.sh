#!/bin/sh

script_dir=$(cd "$(dirname "$0")" && pwd)
script_base=$(basename "$script_dir")

lxc delete -f "$script_base" || true

lxc launch ubuntu:24.04 "$script_base" \
    --config "cloud-init.user-data=$(cat "$script_dir/cloud-init.yml")" \
    --ephemeral

lxc exec "$script_base" -- cloud-init status --wait

lxc file push "$script_dir" "$script_base/home/ubuntu" \
    --create-dirs \
    --recursive

lxc exec "$script_base" -- \
    su - ubuntu -c "/usr/bin/python3 '/home/ubuntu/$script_base/main.py'"

lxc exec "$script_base" -- \
    su - ubuntu
