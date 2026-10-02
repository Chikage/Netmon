#!/usr/bin/env python3
"""Deterministic IPK + native APKv3 packaging for the architecture-neutral plugins."""
import argparse
import gzip
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"
RELEASE = 2
EPOCH = int(os.environ.get("SOURCE_DATE_EPOCH", "1790899200"))
DEPENDENCIES = {
    "netmon": ["python3-light", "conntrack", "kmod-nf-conntrack-netlink", "rpcd", "uci", "ubus", "ip"],
    "luci-app-netmon": ["luci-base", "netmon"],
}
DESCRIPTIONS = {
    "netmon": "Per-client traffic classification and conntrack accounting",
    "luci-app-netmon": "LuCI client traffic classification and connection dashboard",
}
POST_CORE = '''#!/bin/sh
[ -z "$IPKG_INSTROOT" ] || exit 0
for file in /usr/lib/netmon/core.py /usr/lib/netmon/daemon.py /usr/libexec/rpcd/luci.netmon; do
    [ -s "$file" ] || { echo "Netmon installation incomplete: $file is missing" >&2; exit 1; }
done
/etc/init.d/netmon enable
if /etc/init.d/netmon running; then
    /etc/init.d/netmon restart
else
    /etc/init.d/netmon start
fi
/etc/init.d/rpcd restart
exit 0
'''
POST_UI = '''#!/bin/sh
[ -z "$IPKG_INSTROOT" ] || exit 0
for file in view/netmon/overview.js view/netmon/settings.js netmon/dashboard.js netmon/style.css; do
    [ -s "/www/luci-static/resources/$file" ] || { echo "Netmon UI installation incomplete: $file is missing" >&2; exit 1; }
done
rm -f /tmp/luci-indexcache /tmp/luci-indexcache.*
/etc/init.d/rpcd restart
exit 0
'''
PRE_CORE = '''#!/bin/sh
[ -z "$IPKG_INSTROOT" ] || exit 0
/etc/init.d/netmon stop
/etc/init.d/netmon disable
exit 0
'''


def archive(entries):
    """Return GNU tar bytes with predictable permissions, root ownership and time."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        # Unlike tar(1), opkg's libbb extractor does not create parent directories
        # when extracting regular files. Every parent must precede its children.
        directories = {str(parent) for name, _, _ in entries for parent in Path(name).parents
                       if str(parent) != "."}
        for name in sorted(directories, key=lambda value: (value.count("/"), value)):
            item = tarfile.TarInfo("./" + name)
            item.type, item.mode, item.mtime = tarfile.DIRTYPE, 0o755, EPOCH
            item.uid = item.gid = 0
            item.uname = item.gname = "root"
            tar.addfile(item)
        for name, content, mode in sorted(entries):
            item = tarfile.TarInfo("./" + name)
            item.size, item.mode, item.mtime = len(content), mode, EPOCH
            item.uid = item.gid = 0
            item.uname = item.gname = "root"
            tar.addfile(item, io.BytesIO(content))
    return buf.getvalue()


def compressed(data):
    return gzip.compress(data, compresslevel=9, mtime=0)


def files_for(name):
    base = ROOT / "package" / name / "files"
    entries = []
    for path in sorted(base.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            rel = path.relative_to(base).as_posix()
            mode = 0o755 if rel.startswith(("etc/init.d/", "usr/libexec/")) else 0o644
            entries.append((rel, path.read_bytes(), mode))
    return entries


def build_ipk(name, out):
    data = archive(files_for(name))
    control = "\n".join([
        "Package: " + name, "Version: %s-%s" % (VERSION, RELEASE), "Architecture: all",
        "Maintainer: Netmon contributors", "Section: net" if name == "netmon" else "Section: luci",
        "Priority: optional", "License: MIT", "Installed-Size: " + str(len(data)),
        "Depends: " + ", ".join(DEPENDENCIES[name]), "Description: " + DESCRIPTIONS[name], ""])
    metadata = [("control", control.encode(), 0o644),
                ("postinst", (POST_CORE if name == "netmon" else POST_UI).encode(), 0o755)]
    if name == "netmon":
        metadata += [("conffiles", b"/etc/config/netmon\n", 0o644), ("prerm", PRE_CORE.encode(), 0o755)]
    package = archive([("debian-binary", b"2.0\n", 0o644),
                       ("control.tar.gz", compressed(archive(metadata)), 0o644),
                       ("data.tar.gz", compressed(data), 0o644)])
    result = out / ("%s_%s-%s_all.ipk" % (name, VERSION, RELEASE))
    result.write_bytes(compressed(package))
    return result


def build_apk(name, tool, out):
    stage = ROOT / ".build" / "packages" / name
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    entries = files_for(name)
    installed = ["/" + rel for rel, _, _ in entries]
    if name == "netmon":
        checksum = hashlib.sha256(next(c for n, c, _ in entries if n == "etc/config/netmon")).hexdigest()
        entries.extend([
            ("lib/apk/packages/netmon.conffiles", b"/etc/config/netmon\n", 0o644),
            ("lib/apk/packages/netmon.conffiles_static", ("/etc/config/netmon " + checksum + "\n").encode(), 0o644)])
    entries.append(("lib/apk/packages/" + name + ".list", ("\n".join(sorted(installed)) + "\n").encode(), 0o644))
    for rel, content, mode in entries:
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)
    for path in [stage] + list(stage.rglob("*")):
        os.utime(path, (EPOCH, EPOCH))
        if path.is_dir():
            path.chmod(0o755)
    scripts = ROOT / ".build" / "scripts" / name
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "post").write_text(POST_CORE if name == "netmon" else POST_UI)
    (scripts / "pre").write_text(PRE_CORE)
    result = out / ("%s-%s-r%s.apk" % (name, VERSION, RELEASE))
    args = [str(tool), "mkpkg", "--info", "name:" + name,
            "--info", "version:%s-r%s" % (VERSION, RELEASE), "--info", "arch:noarch", "--info", "license:MIT",
            "--info", "description:" + DESCRIPTIONS[name],
            "--info", "depends:" + " ".join(DEPENDENCIES[name]),
            "--info", "build-time:" + str(EPOCH), "--files", str(stage), "--output", str(result),
            "--script", "post-install:" + str(scripts / "post"),
            "--script", "post-upgrade:" + str(scripts / "post"), "--xattrs=no"]
    if name == "netmon":
        args += ["--script", "pre-deinstall:" + str(scripts / "pre")]
    subprocess.run(args, check=True)
    # A local host's uid/gid must never leak into a router package.
    metadata = subprocess.check_output([str(tool), "adbdump", str(result)], text=True)
    for line in metadata.splitlines():
        if line.strip().startswith(("user:", "group:")) and line.split(":", 1)[1].strip() != "root":
            result.unlink()
            raise RuntimeError("APK ownership must be root:root; use fakeroot or scripts/bootstrap-apk.sh")
    subprocess.run([str(tool), "verify", "--allow-untrusted", str(result)], check=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ipk-only", action="store_true")
    parser.add_argument("--apk-tool", type=Path, default=ROOT / ".build/tooling/apk-build/src/apk")
    args = parser.parse_args()
    if not args.ipk_only and not args.apk_tool.is_file():
        parser.error("APK tool not found. Run scripts/bootstrap-apk.sh or pass --apk-tool PATH (under fakeroot).")
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    products = []
    for name in DEPENDENCIES:
        products.append(build_ipk(name, out))
        if not args.ipk_only:
            products.append(build_apk(name, args.apk_tool.resolve(), out))
    (out / "SHA256SUMS").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in sorted(products)))
    for product in products:
        print("%s (%s bytes)" % (product.relative_to(ROOT), product.stat().st_size))


if __name__ == "__main__":
    main()
