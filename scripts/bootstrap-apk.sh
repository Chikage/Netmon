#!/bin/sh
# Build the official Alpine APKv3 packager locally (macOS or Linux).
set -eu
cd "$(dirname "$0")/.."
mkdir -p .build/tooling
curl -fL --retry 2 https://codeload.github.com/alpinelinux/apk-tools/tar.gz/refs/tags/v3.0.5 -o .build/tooling/apk-tools.tar.gz
python3 - <<'PY'
from pathlib import Path
import hashlib
assert hashlib.sha256(Path('.build/tooling/apk-tools.tar.gz').read_bytes()).hexdigest() == '8795712ce02457d29c0beb18f82851b408d1d47f98a0cbbbd33ab5ea496f665d', 'APK source checksum mismatch'
PY
tar -xzf .build/tooling/apk-tools.tar.gz -C .build/tooling
python3 -m venv .build/tooling/venv
.build/tooling/venv/bin/pip install 'meson==1.11.2'
# Equivalent to fakeroot ownership for mkpkg only. This binary is a host build
# tool; it is never shipped to routers. Do not rewrite any installed system tool.
python3 - <<'PY'
from pathlib import Path
p = Path('.build/tooling/apk-tools-3.0.5/src/app_mkpkg.c')
s = p.read_text()
assert s.count('apk_id_cache_resolve_user(idc, fi.uid)') == 2
assert s.count('apk_id_cache_resolve_group(idc, fi.gid)') == 2
s = s.replace('apk_id_cache_resolve_user(idc, fi.uid)', 'APK_BLOB_STRLIT("root")')
s = s.replace('apk_id_cache_resolve_group(idc, fi.gid)', 'APK_BLOB_STRLIT("root")')
p.write_text(s)
PY
if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null; then
	PKG_CONFIG_PATH="$(brew --prefix openssl@3)/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
	export PKG_CONFIG_PATH
fi
.build/tooling/venv/bin/meson setup --reconfigure .build/tooling/apk-build .build/tooling/apk-tools-3.0.5 \
	-Ddocs=disabled -Dhelp=disabled -Dlua=disabled -Dpython=disabled \
	-Dtests=disabled -Durl_backend=wget -Dzstd=disabled
ninja -C .build/tooling/apk-build
