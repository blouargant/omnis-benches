#!/bin/sh
. ./lib/strings.sh
echo "$(upper "$(trim_left "  hello")")"
