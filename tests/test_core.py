import ipaddress
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'package/netmon/files/usr/lib/netmon'))
from core import Engine, Rule, parse_conntrack
from daemon import uci_sections


def flow(upload=100, download=200, proto='tcp', port=80, src='192.168.1.20',
         dst='203.0.113.9', rsrc=None, rdst='198.51.100.1', sport=43000,
         rport=None, ident=10, event='', extra='', counters=True):
    version = 'ipv6 10' if ':' in src else 'ipv4 2'
    orig = 'packets=1 bytes=%d' % upload if counters else ''
    reply = 'packets=1 bytes=%d' % download if counters else ''
    line = '%s %s %s 6 120 ESTABLISHED src=%s dst=%s sport=%s dport=%s %s src=%s dst=%s sport=%s dport=%s %s [ASSURED] mark=0 id=%s %s' % (
        event, version, proto, src, dst, sport, port, orig, rsrc or dst,
        rdst, rport or port, sport, reply, ident, extra)
    return parse_conntrack(line)


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(1200)
        self.engine.configure_networks(['192.168.1.0/24', 'fd00::/64'], ['192.168.1.1', '198.51.100.1'], {})

    def client(self, now=1210):
        return self.engine.report(now)['clients'][0]

    def test_bidirectional_delta_excludes_prestart_traffic(self):
        self.engine.snapshot([flow(1000, 5000)], 1200, baseline=True)
        self.engine.snapshot([flow(1200, 8000)], 1205)
        c = self.client()
        self.assertEqual(c['windows']['300']['http'], [200, 3000, 0])
        self.assertEqual(c['connections'], {'http': 1})

    def test_short_connection_destroy_counts_final_bytes(self):
        self.engine.ingest(flow(0, 0, event='[NEW]', counters=False), 1201)
        self.engine.ingest(flow(120, 320, event='[DESTROY]'), 1202)
        c = self.client()
        self.assertEqual(c['windows']['300']['http'], [120, 320, 1])
        self.assertEqual(c['connections'], {})

    def test_new_event_queued_during_baseline_recovers_bytes_once(self):
        self.engine.snapshot([flow(1000, 2000)], 1202, baseline=True)
        self.engine.snapshot([flow(1200, 2200)], 1203)
        self.engine.ingest(flow(0, 0, event='[NEW]', counters=False), 1201)
        self.engine.ingest(flow(0, 0, event='[NEW]', counters=False), 1201)
        self.assertEqual(self.client()['windows']['300']['http'], [1200, 2200, 1])

    def test_preexisting_flow_destroyed_during_baseline_is_not_history(self):
        self.engine.ingest(flow(100000, 200000, event='[DESTROY]'), 1201, baseline=True)
        self.assertEqual(self.client()['windows']['300']['http'], [0, 0, 0])

    def test_short_flow_in_initial_queue_is_counted(self):
        self.engine.ingest(flow(0, 0, event='[NEW]', counters=False), 1201)
        self.engine.ingest(flow(100, 200, event='[DESTROY]'), 1202, baseline=True)
        self.assertEqual(self.client()['windows']['300']['http'], [100, 200, 1])

    def test_destroy_without_new_is_counted(self):
        self.engine.ingest(flow(120, 320, event='[DESTROY]'), 1202)
        self.assertEqual(self.client()['windows']['300']['http'], [120, 320, 1])

    def test_snapshot_and_destroy_never_double_count(self):
        self.engine.snapshot([flow(100, 200)], 1201)
        self.engine.ingest(flow(120, 320, event='[DESTROY]'), 1202)
        self.engine.ingest(flow(120, 320, event='[DESTROY]'), 1203)
        self.engine.snapshot([flow(100, 200)], 1204)
        c = self.client()
        self.assertEqual(c['windows']['300']['http'], [120, 320, 1])
        self.assertEqual(c['connections'], {})

    def test_late_destroy_after_disappearance_accounts_tail(self):
        self.engine.snapshot([flow(100, 200)], 1201)
        self.engine.snapshot([], 1202)
        self.engine.ingest(flow(150, 250, event='[DESTROY]'), 1203)
        self.assertEqual(self.client()['windows']['300']['http'], [150, 250, 1])

    def test_out_of_order_counter_does_not_regress(self):
        for up, down in [(100, 100), (200, 300), (150, 250), (220, 330)]:
            self.engine.ingest(flow(up, down), 1201)
        self.assertEqual(self.client()['windows']['300']['http'], [220, 330, 1])

    def test_dnat_upload_download_and_internal_service_port(self):
        self.engine.ingest(flow(300, 900, src='203.0.113.8', dst='198.51.100.1',
                                rsrc='192.168.1.20', rdst='203.0.113.8', port=50080, rport=80), 1201)
        c = self.client()
        self.assertEqual(c['ips'], ['192.168.1.20'])
        self.assertEqual(c['windows']['300']['http'], [900, 300, 1])

    def test_no_router_or_lan_to_lan_accounting(self):
        for rec in [flow(src='192.168.1.1'), flow(dst='192.168.1.1'),
                    flow(dst='192.168.1.21'), flow(src='198.51.100.1'),
                    flow(dst='224.0.0.1')]:
            self.engine.ingest(rec, 1201)
        self.assertEqual(self.engine.report(1205)['clients'], [])

    def test_ipv6_counters_and_category(self):
        self.engine.ingest(flow(src='fd00::20', dst='2606:4700::1111',
                                rdst='fd00::20', proto='udp', port=443), 1201)
        self.assertEqual(self.client()['windows']['300']['tls'], [100, 200, 1])

    def test_mac_merges_ipv4_and_ipv6_history(self):
        self.engine.ingest(flow(), 1201)
        self.engine.ingest(flow(src='fd00::20', dst='2606:4700::1111', rdst='fd00::20', ident=11), 1202)
        hosts = {ip: {'mac': 'aa:bb:cc:dd:ee:ff', 'name': 'Laptop'} for ip in ['192.168.1.20', 'fd00::20']}
        self.engine.configure_networks(['192.168.1.0/24', 'fd00::/64'], ['192.168.1.1'], hosts)
        c = self.client()
        self.assertEqual(len(self.engine.clients), 1)
        self.assertEqual(c['name'], 'Laptop')
        self.assertEqual(c['connections'], {'http': 2})
        self.assertEqual(c['windows']['300']['http'], [200, 400, 2])

    def test_ipv4_failed_dump_does_not_remove_ipv6(self):
        self.engine.ingest(flow(), 1201)
        self.engine.snapshot([], 1202, families=(6,))
        self.assertEqual(self.client()['connections'], {'http': 1})

    def test_windows_and_retention(self):
        self.engine.ingest(flow(), 1201)
        self.engine.ingest(flow(200, 400), 1801)
        c = self.client(1810)
        self.assertEqual(c['windows']['300']['http'], [100, 200, 0])
        self.assertEqual(c['windows']['1800']['http'], [200, 400, 1])
        c = self.client(90000)
        self.assertEqual(c['windows']['86400']['http'], [0, 0, 0])

    def test_missing_counters_preserves_connections(self):
        self.engine.ingest(flow(counters=False), 1201)
        report = self.engine.report(1210)
        self.assertEqual(report['missing_accounting'], 1)
        self.assertEqual(report['clients'][0]['connections'], {'http': 1})

    def test_offload_report(self):
        self.engine.ingest(flow(extra='[OFFLOAD]'), 1201)
        self.assertEqual(self.engine.report(1210)['offloaded_flows'], 1)

    def test_bounded_flows(self):
        self.engine.max_flows = 1
        self.engine.ingest(flow(), 1201)
        self.engine.ingest(flow(ident=11), 1201)
        self.assertEqual(len(self.engine.flows), 1)
        self.assertEqual(self.engine.report(1210)['limits_hit'], 1)

    def test_rates_use_elapsed_time_and_reset(self):
        self.engine.ingest(flow(), 1201)
        self.assertEqual(self.engine.report(1205, elapsed=5)['clients'][0]['download_rate'], 40)
        self.assertEqual(self.client()['download_rate'], 0)

    def test_reused_tuple_with_new_id_is_a_new_connection(self):
        self.engine.ingest(flow(event='[DESTROY]'), 1201)
        self.engine.ingest(flow(ident=11), 1202)
        c = self.client()
        self.assertEqual(c['windows']['300']['http'], [200, 400, 2])
        self.assertEqual(c['connections'], {'http': 1})

    def test_ephemeral_source_port_does_not_classify_p2p(self):
        self.engine.ingest(flow(sport=6881, port=44444), 1201)
        self.assertEqual(self.client()['connections'], {'unknown': 1})

    def test_custom_cidr_rule_precedes_default(self):
        self.engine.rules.insert(0, Rule('video', 'tcp', '443', '203.0.113.0/24'))
        self.engine.ingest(flow(port=443), 1201)
        self.assertEqual(self.client()['connections'], {'video': 1})

    def test_large_64bit_counters(self):
        self.engine.ingest(flow(2**40, 2**42), 1201)
        self.assertEqual(self.client()['windows']['300']['http'], [2**40, 2**42, 1])


class ParsingTests(unittest.TestCase):
    def test_non_tcp_udp_protocol_is_still_a_connection(self):
        rec = parse_conntrack('ipv4 2 esp 50 599 src=192.168.1.2 dst=1.1.1.1 packets=1 bytes=84 src=1.1.1.1 dst=198.51.100.1 packets=1 bytes=84 mark=0 id=991')
        self.assertEqual(rec['proto'], 'esp')

    def test_invalid_input(self):
        for line in ['', 'conntrack v1.4.8: 3 flow entries', 'tcp 6 10 src=bad dst=bad',
                     'tcp 6 10 src=1.1.1.1 dst=2.2.2.2 src=1.1.1.1 dst=bad']:
            self.assertIsNone(parse_conntrack(line))

    def test_icmp_id_and_conntrack_id(self):
        rec = parse_conntrack('ipv4 2 icmp 1 27 src=192.168.1.2 dst=1.1.1.1 type=8 code=0 id=4 packets=1 bytes=84 src=1.1.1.1 dst=198.51.100.1 type=0 code=0 id=4 packets=1 bytes=84 mark=0 use=1 id=991')
        self.assertEqual(rec['key'][-1], '991')
        self.assertEqual(rec['bytes'], (84, 84))

    def test_invalid_rule(self):
        for args in [('p2p', 'tcp', '65536'), ('p2p', 'tcp', '90-80'), ('p2p', 'any'),
                     ('bad', 'tcp', '80'), ('http', 'tcp', 'a'), ('p2p', 'tcp', '80', 'bad')]:
            with self.assertRaises(ValueError):
                Rule(*args)

    def test_rule_range_and_family(self):
        r = Rule('p2p', 'udp', '6881-6999,51413', '192.0.2.0/24')
        self.assertTrue(r.matches('udp', 6889, ipaddress.ip_address('192.0.2.1')))
        self.assertFalse(r.matches('tcp', 6889, ipaddress.ip_address('192.0.2.1')))
        self.assertFalse(r.matches('udp', 6889, ipaddress.ip_address('fd00::1')))

    def test_uci_quotes_and_lists(self):
        sections = uci_sections("package netmon\nconfig netmon 'main'\n list networks 'lan'\n list networks 'guest'\n option interval '5'\nconfig rule\n option name 'Phone video'\n")
        self.assertEqual(sections[0]['networks'], ['lan', 'guest'])
        self.assertEqual(sections[1]['name'], 'Phone video')

    def test_snapshot_serializable(self):
        json.dumps(Engine(0).report(1))


if __name__ == '__main__':
    unittest.main()
