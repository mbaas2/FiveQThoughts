#!/bin/zsh
cd "$(dirname "$0")"
python3 -c "import app; app.ensure_macos_native_app()"
open "$PWD/FiveQThoughts.app"
