"""Conntrack accounting and rule classification; no packet payloads are collected."""
import collections
import ipaddress
import re

VERSION = "1.0.0"
WINDOWS = (300, 1800, 3600, 86400)
CATEGORIES = (
    ("http", "HTTP 协议", "#9479cf"),
    ("tls", "HTTPS / QUIC", "#4f92dc"),
    ("p2p", "P2P 下载", "#0a9f9a"),
    ("video", "流媒体协议", "#ed9854"),
    ("game", "网络游戏", "#cc5ba6"),
    ("file", "文件传输", "#8290ae"),
    ("chat", "网络通讯", "#a08bc9"),
    ("dns", "DNS 解析", "#26aeb8"),
    ("common", "常用协议", "#5f89a5"),
    ("speed", "测速工具", "#c4a91b"),
    ("unknown", "未分类", "#cf737b"),
)
CATEGORY_IDS = {c[0] for c in CATEGORIES}
PAIR = re.compile(r"\b([a-z_]+)=([^\s]+)")
PROTOCOL = re.compile(r"\b([a-z][a-z0-9_-]*|\d+)\s+\d+\s+\d+")


def address(value):
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def parse_conntrack(line):
    """Parse extended output, including repeated NAT tuples and optional counters."""
    match = PROTOCOL.search(line)
    if not match:
        return None
    pairs = collections.defaultdict(list)
    for key, value in PAIR.findall(line):
        pairs[key].append(value)
    if len(pairs["src"]) != 2 or len(pairs["dst"]) != 2:
        return None
    try:
        src, reply_src = [ipaddress.ip_address(v) for v in pairs["src"]]
        dst, reply_dst = [ipaddress.ip_address(v) for v in pairs["dst"]]
        sport = int(pairs["sport"][0]) if pairs["sport"] else 0
        dport = int(pairs["dport"][0]) if pairs["dport"] else 0
        rsport = int(pairs["sport"][1]) if len(pairs["sport"]) > 1 else 0
        rdport = int(pairs["dport"][1]) if len(pairs["dport"]) > 1 else 0
        counters = tuple(int(v) for v in pairs["bytes"]) if len(pairs["bytes"]) == 2 else None
        if counters and min(counters) < 0:
            return None
    except ValueError:
        return None
    # -o id adds the conntrack ID last; ICMP may also contain per-tuple id fields.
    ident = pairs["id"][-1] if pairs["id"] else ""
    proto = match.group(1)
    key = (src.version, proto, str(src), str(dst), sport, dport,
           str(reply_src), str(reply_dst), rsport, rdport,
           pairs["zone"][-1] if pairs["zone"] else "0", ident)
    return {"key": key, "proto": proto, "src": src, "dst": dst,
            "reply_src": reply_src, "reply_dst": reply_dst,
            "sport": sport, "dport": dport, "reply_sport": rsport,
            "bytes": counters, "event": "DESTROY" if "[DESTROY]" in line else
            "NEW" if "[NEW]" in line else "SNAPSHOT", "offload": "OFFLOAD" in line}


class Rule:
    def __init__(self, category, proto="any", ports="", cidr=""):
        if category not in CATEGORY_IDS or proto not in ("any", "tcp", "udp", "icmp", "icmpv6", "sctp", "gre"):
            raise ValueError("分类或传输协议无效")
        self.category, self.proto = category, proto
        self.network = ipaddress.ip_network(cidr, strict=False) if cidr else None
        self.ports = []
        for token in ports.replace(" ", ",").split(","):
            if not token:
                continue
            parts = token.split("-")
            if len(parts) > 2:
                raise ValueError("端口范围格式无效")
            lo, hi = int(parts[0]), int(parts[-1])
            if not 1 <= lo <= hi <= 65535:
                raise ValueError("端口必须在 1–65535 之间")
            self.ports.append((lo, hi))
        if not self.ports and self.network is None and proto == "any":
            raise ValueError("规则至少需要指定协议、端口或目标网段")

    def matches(self, proto, port, peer):
        return (self.proto == "any" or self.proto == proto) and (
            not self.ports or any(lo <= port <= hi for lo, hi in self.ports)) and (
            self.network is None or peer in self.network)


def default_rules():
    return [Rule(*args) for args in (
        ("dns", "any", "53,853"),
        ("http", "tcp", "80,8080"), ("tls", "tcp", "443,8443"),
        ("tls", "udp", "443"), ("p2p", "any", "6881-6999,51413"),
        ("video", "any", "554,1935"), ("game", "any", "3074,27015-27030"),
        ("file", "tcp", "20,21,139,445"), ("file", "udp", "69"),
        ("chat", "any", "5060,5061,5222,5223"), ("speed", "any", "5201"),
        ("common", "any", "22,25,110,123,143,465,587,993,995,1194,3389,51820"),
        ("common", "icmp"), ("common", "icmpv6"), ("common", "gre"))]


class Engine:
    def __init__(self, started, rules=None, max_flows=32768, max_clients=512):
        self.started = started
        self.rules = (rules or []) + default_rules()
        self.max_flows, self.max_clients = max_flows, max_clients
        self.flows, self.clients, self.hosts = {}, {}, {}
        self.networks, self.router_ips = [], set()
        self.limits_hit = 0
        self.last_publish = started

    def configure_networks(self, networks, router_ips, hosts):
        self.networks = [ipaddress.ip_network(n, strict=False) for n in networks]
        self.router_ips = {str(ipaddress.ip_address(ip)) for ip in router_ips}
        self.hosts = hosts
        # Merge IPv4 and IPv6 history once the neighbour table supplies a MAC.
        for ip, host in hosts.items():
            old, new = "ip:" + ip, host.get("mac", "").lower()
            if old in self.clients and new:
                source = self.clients.pop(old)
                dest = self.clients.setdefault(new, source)
                if dest is not source:
                    dest["ips"].update(source["ips"])
                    for minute, cats in source["buckets"].items():
                        for cat, values in cats.items():
                            target = dest["buckets"].setdefault(minute, {}).setdefault(cat, [0, 0, 0])
                            for i in range(3):
                                target[i] += values[i]
                    for i in range(2):
                        dest["delta"][i] += source["delta"][i]
                for flow in self.flows.values():
                    if flow["client"] == old:
                        flow["client"] = new
            if new in self.clients:
                self.clients[new]["mac"] = new
                if host.get("name"):
                    self.clients[new]["name"] = host["name"]

    def is_client(self, ip):
        return str(ip) not in self.router_ips and not ip.is_multicast and any(ip in n for n in self.networks)

    def owner(self, record):
        outgoing = self.is_client(record["src"])
        incoming = self.is_client(record["reply_src"])
        # Ignore intra-LAN/hairpin flows and connections terminating on the router.
        if outgoing == incoming:
            return None
        if outgoing:
            if str(record["dst"]) in self.router_ips or record["dst"].is_multicast:
                return None
            return record["src"], record["dst"], record["dport"], False
        if str(record["src"]) in self.router_ips or record["src"].is_multicast:
            return None
        return record["reply_src"], record["src"], record["reply_sport"], True

    def classify(self, proto, port, peer):
        return next((r.category for r in self.rules if r.matches(proto, port, peer)), "unknown")

    def client_for(self, ip, now):
        ip = str(ip)
        host = self.hosts.get(ip, {})
        mac = host.get("mac", "").lower()
        key = mac or "ip:" + ip
        if key not in self.clients:
            if len(self.clients) >= self.max_clients:
                self.limits_hit += 1
                return None
            self.clients[key] = {"ips": set(), "mac": mac, "name": host.get("name", ""),
                                 "buckets": {}, "delta": [0, 0], "last_seen": now}
        client = self.clients[key]
        client["ips"].add(ip)
        client["last_seen"] = now
        if host.get("name"):
            client["name"] = host["name"]
        return key

    def ingest(self, record, now, baseline=False):
        key = record["key"]
        flow = self.flows.get(key)
        created = flow is None
        if flow and flow["destroyed"]:
            return  # delayed dump / duplicate DESTROY must not resurrect a connection
        if flow is None:
            owner = self.owner(record)
            if owner is None:
                return
            if len(self.flows) >= self.max_flows:
                self.limits_hit += 1
                return
            ip, peer, port, reverse = owner
            client = self.client_for(ip, now)
            if client is None:
                return
            flow = {"client": client, "category": self.classify(record["proto"], port, peer),
                    "reverse": reverse, "counters": (0, 0), "active": True,
                    "destroyed": False, "last_seen": now, "accounted": record["bytes"] is not None,
                    "offload": record["offload"], "counted": not baseline,
                    "baseline_bytes": (record["bytes"] or (0, 0)) if baseline else (0, 0)}
            self.flows[key] = flow
            new = 0 if baseline else 1
        else:
            new = 0
        values = record["bytes"]
        delta = [0, 0]
        if values is not None:
            # A dump and the event stream may arrive out of order. Never regress counters.
            delta = [max(0, values[i] - flow["counters"][i]) for i in range(2)]
            flow["counters"] = tuple(max(values[i], flow["counters"][i]) for i in range(2))
            flow["accounted"] = True
        if record["event"] == "NEW" and not flow["counted"]:
            # A NEW event queued during the initial dump proves that these bytes
            # were generated after startup. Recover them once, even if the dump
            # arrived before the creation event.
            delta = [delta[i] + flow["baseline_bytes"][i] for i in range(2)]
            new, flow["counted"] = 1, True
        if baseline and created:
            delta = [0, 0]  # do not assign pre-start bytes to the current minute
        if flow["reverse"]:
            delta.reverse()
        client = self.clients[flow["client"]]
        client["last_seen"] = now
        if sum(delta) or new:
            bucket = client["buckets"].setdefault(int(now // 60) * 60, {}).setdefault(flow["category"], [0, 0, 0])
            for i, value in enumerate(delta + [new]):
                bucket[i] += value
            for i in range(2):
                client["delta"][i] += delta[i]
        flow.update(active=record["event"] != "DESTROY", destroyed=record["event"] == "DESTROY",
                    last_seen=now, offload=record["offload"])

    def snapshot(self, records, now, baseline=False, families=(4, 6)):
        seen = set()
        for record in records:
            seen.add(record["key"])
            self.ingest(record, now, baseline)
        for key, flow in self.flows.items():
            if key[0] in families and key not in seen:
                flow["active"] = False

    def prune(self, now):
        cutoff = int((now - 86400) // 60) * 60
        for key, flow in list(self.flows.items()):
            if not flow["active"] and now - flow["last_seen"] > 120:
                del self.flows[key]
        active = {f["client"] for f in self.flows.values() if f["active"]}
        for key, client in list(self.clients.items()):
            for minute in list(client["buckets"]):
                if minute < cutoff:
                    del client["buckets"][minute]
            if not client["buckets"] and key not in active and now - client["last_seen"] > 120:
                del self.clients[key]

    def report(self, now, elapsed=None):
        self.prune(now)
        period = max(0.001, elapsed if elapsed is not None else now - self.last_publish)
        counts = collections.defaultdict(collections.Counter)
        missing, offloaded = 0, 0
        for flow in self.flows.values():
            if flow["active"]:
                counts[flow["client"]][flow["category"]] += 1
                missing += not flow["accounted"]
                offloaded += flow["offload"]
        clients = []
        for key, client in self.clients.items():
            windows = {}
            for seconds in WINDOWS:
                cats = {cat: [0, 0, 0] for cat, _, _ in CATEGORIES}
                cutoff = int((now - seconds) // 60) * 60
                for minute, bucket in client["buckets"].items():
                    if cutoff <= minute <= now:
                        for cat, values in bucket.items():
                            for i in range(3):
                                cats[cat][i] += values[i]
                windows[str(seconds)] = cats
            clients.append({"id": key, "name": client["name"], "mac": client["mac"],
                            "ips": sorted(client["ips"]), "last_seen": client["last_seen"],
                            "connections": dict(counts[key]), "windows": windows,
                            "upload_rate": client["delta"][0] / period,
                            "download_rate": client["delta"][1] / period})
            client["delta"] = [0, 0]
        self.last_publish = now
        return {"version": VERSION, "generated_at": now, "started_at": self.started,
                "bucket_seconds": 60, "categories": [{"id": c, "label": l, "color": color} for c, l, color in CATEGORIES],
                "clients": clients, "missing_accounting": missing, "offloaded_flows": offloaded,
                "limits_hit": self.limits_hit, "tracked_flows": len(self.flows),
                "classification": "rules", "subnets": [str(n) for n in self.networks]}
