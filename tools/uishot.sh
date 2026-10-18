#!/bin/sh
# Screenshot the GUI without touching the real desktop or keyboard:
# headless nested KWin + private D-Bus + simulated keyboard + throwaway config.
#   tools/uishot.sh PAGE WIDTH HEIGHT OUT.png [dark|light|system]
# PAGE: 0 lighting, 1 per-key, 2 music, 3 keymap, 4 settings
here=$(cd "$(dirname "$0")" && pwd)
export AJAZZCTL_FAKE=1 XDG_CONFIG_HOME=${XDG_CONFIG_HOME_TEST:-/tmp/ajazz-cfg}
dbus-run-session -- kwin_wayland --virtual --no-lockscreen --width "$2" --height "$3" \
  --socket "ajz-shot-$$" --exit-with-session \
  "sh -c 'python3 -I $here/uishot_page.py $1 $2 $3 ${5:-dark} & sleep 5; spectacle -b -n -f -o $4; sleep 1; kill %1'" \
  >/dev/null 2>&1
