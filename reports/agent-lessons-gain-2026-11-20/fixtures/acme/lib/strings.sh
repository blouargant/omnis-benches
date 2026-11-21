# string helpers
trim_left() { printf '%s' "$1" | sed 's/^ *//'; }
upper() { printf '%s' "$1" | tr 'a-z' 'A-Z'; }
repeat() { i=0; while [ $i -lt "$2" ]; do printf '%s' "$1"; i=$((i+1)); done; }
