#!/usr/bin/python3
"""OpenWrt service and read-only rpcd endpoint."""
import collections
import json
import os
import queue
import re
import selectors
import shlex
import signal
import subprocess
import sys
import threading
import time

from core import Engine, Rule, parse_conntrack

STATE = "/tmp/netmon/status.json"
MAC = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


def command(args, timeout=10):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("%s: %s" % (args[0], result.stderr.strip()[:240]))
    return result.stdout


def uci_sections(text):
    sections, current = [], None
    for line in text.splitlines():
        tokens = shlex.split(line, comments=True)
        if not tokens:
            continue
        if tokens[0] == "config" and len(tokens) >= 2:
            current = {"type": tokens[1], "name": tokens[2] if len(tokens) > 2 else ""}
            sections.append(current)
        elif current is not None and len(tokens) >= 3:
            if tokens[0] == "option":
                current[tokens[1]] = tokens[2]
            elif tokens[0] == "list":
                current.setdefault(tokens[1], []).append(tokens[2])
    return sections


def read_config():
    sections = uci_sections(command(["uci", "-q", "export", "netmon"]))
    main = next((s for s in sections if s["type"] == "netmon"), {})
    rules = []
    for section in sections:
        if section["type"] == "rule" and section.get("enabled", "1") == "1":
            rules.append(Rule(section.get("category", "unknown"), section.get("proto", "any"),
                              section.get("ports", ""), section.get("cidr", "")))
    main["interval"] = max(2, min(60, int(main.get("interval", "5"))))
    main["max_flows"] = max(1024, min(262144, int(main.get("max_flows", "32768"))))
    main["networks"] = main.get("networks", ["lan"])
    main["subnets"] = main.get("subnets", [])
    if not isinstance(main["networks"], list) or not isinstance(main["subnets"], list):
        raise ValueError("networks 和 subnets 必须使用 UCI list")
    return main, rules


def discover(config):
    dump = json.loads(command(["ubus", "call", "network.interface", "dump"]))
    networks, router_ips, hosts = list(config["subnets"]), [], {}
    for iface in dump.get("interface", []):
        selected = iface.get("interface") in config["networks"]
        for key in ("ipv4-address", "ipv6-address"):
            for item in iface.get(key, []):
                router_ips.append(item["address"])
                if selected:
                    networks.append("%s/%s" % (item["address"], item["mask"]))
        for prefix in iface.get("ipv6-prefix-assignment", []):
            if selected:
                networks.append("%s/%s" % (prefix["address"], prefix["mask"]))
            local = prefix.get("local-address", {}).get("address")
            if local:
                router_ips.append(local)
    names = {}
    try:
        with open("/tmp/dhcp.leases") as stream:
            for line in stream:
                fields = line.split()
                if len(fields) >= 4 and MAC.fullmatch(fields[1]):
                    mac = fields[1].lower()
                    name = fields[3] if fields[3] != "*" else ""
                    names[mac] = name
                    hosts[fields[2]] = {"mac": mac, "name": name}
    except OSError:
        pass
    for args in (["ip", "neigh", "show"], ["ip", "-6", "neigh", "show"]):
        try:
            for line in command(args).splitlines():
                fields = line.split()
                if "lladdr" in fields:
                    mac = fields[fields.index("lladdr") + 1].lower()
                    if MAC.fullmatch(mac) and mac != "00:00:00:00:00:00":
                        hosts[fields[0]] = {"mac": mac, "name": names.get(mac, "")}
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
    return list(dict.fromkeys(networks)), router_ips, hosts


class EventReader(threading.Thread):
    """Drain both pipes continuously so slow snapshots cannot block conntrack -E."""
    def __init__(self):
        super().__init__(daemon=True)
        self.events = queue.Queue(maxsize=65536)
        self.errors = collections.deque(maxlen=8)
        self.dropped = 0
        self.process = None
        self.stopping = threading.Event()

    def run(self):
        try:
            self.process = subprocess.Popen(
                ["conntrack", "-E", "-e", "NEW,DESTROY", "-o", "extended,id", "-b", "4194304"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            with selectors.DefaultSelector() as selector:
                buffers = {"out": b"", "err": b""}
                for stream, name in ((self.process.stdout, "out"), (self.process.stderr, "err")):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                while selector.get_map() and not self.stopping.is_set():
                    for key, _ in selector.select(0.5):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        buffers[key.data] += data
                        while b"\n" in buffers[key.data]:
                            line, buffers[key.data] = buffers[key.data].split(b"\n", 1)
                            line = line.decode("utf-8", "replace")
                            if key.data == "err":
                                if not line.startswith("NOTICE: Netlink socket buffer size has been set to "):
                                    self.errors.append(line[:300])
                            else:
                                try:
                                    self.events.put_nowait((time.time(), line))
                                except queue.Full:
                                    self.dropped += 1
        except (OSError, ValueError) as exc:
            self.errors.append(str(exc)[:300])
        finally:
            if self.process:
                if self.process.poll() is None:
                    self.process.terminate()
                self.process.wait()
                self.process.stdout.close()
                self.process.stderr.close()

    def stop(self):
        self.stopping.set()
        self.join(timeout=3)


def write_state(data):
    os.makedirs(os.path.dirname(STATE), mode=0o700, exist_ok=True)
    temp = STATE + ".new"
    with open(temp, "w") as stream:
        json.dump(data, stream, separators=(",", ":"), ensure_ascii=False)
    os.chmod(temp, 0o600)
    os.replace(temp, STATE)


def status():
    try:
        with open(STATE) as stream:
            data = json.load(stream)
        if time.time() - data.get("generated_at", 0) > max(30, data.get("interval", 5) * 4):
            data["running"] = False
            data.setdefault("warnings", []).append("数据已过期，采集服务可能已停止。")
        return data
    except (OSError, ValueError):
        return {"running": False, "clients": [], "warnings": ["采集服务尚未启动或尚未生成数据。"]}


def main():
    config, rules = read_config()
    started = time.time()
    engine = Engine(started, rules, max_flows=config["max_flows"])
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    reader = EventReader()
    reader.start()
    first, last_discovery, last_publish = {4: True, 6: True}, 0, time.monotonic()
    persistent_warnings, network_warnings = [], []
    restart_at = 0
    initial_events = True
    try:
        while not stopping.is_set():
            cycle = time.monotonic()
            now = time.time()
            warnings = []
            if cycle - last_discovery >= 30 or last_discovery == 0:
                network_warnings = []
                try:
                    had_networks = bool(engine.networks)
                    engine.configure_networks(*discover(config))
                    if not had_networks and engine.networks:
                        first, initial_events = {4: True, 6: True}, True
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    network_warnings.append("客户端网段发现失败：" + str(exc))
                try:
                    fw = uci_sections(command(["uci", "-q", "export", "firewall"]))
                    if any(s.get("flow_offloading") == "1" or s.get("flow_offloading_hw") == "1" for s in fw):
                        network_warnings.append("检测到流量分载。硬件/NSS/SFE/软件加速可能绕过计数；需要完整统计时请关闭加速并重新建立连接。")
                except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError):
                    pass
                last_discovery = cycle
            # Snapshot first, then queued events: terminal counters are monotonic and
            # DESTROY tombstones prevent a stale dump from resurrecting a flow.
            successful = []
            for family, name in ((4, "ipv4"), (6, "ipv6")):
                try:
                    output = command(["conntrack", "-L", "-f", name, "-o", "extended,id"], timeout=12)
                    records = (parse_conntrack(line) for line in output.splitlines())
                    engine.snapshot((r for r in records if r is not None), time.time(), first[family], (family,))
                    first[family] = False
                    successful.append(family)
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    warnings.append("%s 连接表读取失败：%s" % (name, exc))
            while True:
                try:
                    event_time, line = reader.events.get_nowait()
                except queue.Empty:
                    break
                record = parse_conntrack(line)
                if record:
                    engine.ingest(record, max(started, event_time),
                                  baseline=initial_events and record["event"] == "DESTROY")
            initial_events = False
            if reader.dropped:
                persistent_warnings.append("事件队列曾溢出，可能漏计短连接。")
                reader.dropped = 0
            if reader.errors:
                persistent_warnings.extend("连接事件：" + msg for msg in list(reader.errors))
                reader.errors.clear()
            if not reader.is_alive():
                warnings.append("连接事件监听已断开，当前仅有轮询统计。")
                if cycle >= restart_at:
                    reader = EventReader()
                    reader.start()
                    restart_at = cycle + 10
            report = engine.report(time.time(), time.monotonic() - last_publish)
            last_publish = time.monotonic()
            if report["missing_accounting"]:
                warnings.append("部分旧连接尚无字节计数；启用统计后新建的连接才有完整流量。")
            if report["offloaded_flows"]:
                warnings.append("内核连接表含已分载连接，流量可能延迟更新或漏计。")
            if report["limits_hit"]:
                warnings.append("曾达到客户端或连接容量上限，统计可能不完整；可提高连接上限并重启服务。")
            if not engine.networks:
                warnings.append("未发现 LAN 网段；请在设置中选择客户端网络或添加网段。")
            persistent_warnings = list(dict.fromkeys(persistent_warnings))[-8:]
            report.update(running=True, collecting=bool(successful), interval=config["interval"],
                          event_stream=reader.is_alive(),
                          warnings=list(dict.fromkeys(network_warnings + warnings + persistent_warnings)))
            write_state(report)
            stopping.wait(max(0.05, config["interval"] - (time.monotonic() - cycle)))
    finally:
        reader.stop()
        result = status()
        result.update(running=False, generated_at=time.time())
        write_state(result)


def rpc():
    if sys.argv[1:] == ["list"]:
        print('{"status":{}}')
        return
    if sys.argv[1:] != ["call", "status"]:
        raise ValueError("Unknown RPC method")
    params = json.loads(sys.stdin.read(8192) or "{}")
    if not isinstance(params, dict) or set(params) - {"ubus_rpc_session"}:
        raise ValueError("Invalid parameters")
    print(json.dumps(status(), ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--daemon"]:
            main()
        else:
            rpc()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        if sys.argv[1:] == ["--daemon"]:
            write_state({"running": False, "clients": [], "generated_at": time.time(),
                         "warnings": ["服务启动失败：" + str(error)]})
            print(str(error), file=sys.stderr)
        else:
            print(json.dumps({"error": str(error)}))
        sys.exit(1)
