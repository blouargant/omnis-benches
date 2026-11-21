#!/bin/sh
if [ ! -f .acme/state ]; then
  echo "FATAL: workspace not initialised (E17)" >&2
  exit 2
fi
. ./lib/strings.sh
n=0
for t in "$(trim_left '  a')=a" "$(upper abc)=ABC" "$(repeat x 3)=xxx"; do
  [ "${t%%=*}" = "${t#*=}" ] || { echo "FAIL $t" >&2; exit 1; }
  n=$((n+1))
done
echo "$n passed [run ACME-T93D]"
