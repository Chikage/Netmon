#!/bin/sh
# Integration lab only: run in a disposable OpenWrt VM, never a production router.
set -eu
ip netns add nmtest
ip link add nm-router type veth peer name nm-client
ip link set nm-client netns nmtest
ip link set nm-router up
ip netns exec nmtest ip link set lo up
ip netns exec nmtest ip addr add 192.168.88.2/24 dev nm-client
ip netns exec nmtest ip -6 addr add fd88::2/64 dev nm-client
ip netns exec nmtest ip link set nm-client up
ip netns exec nmtest ip route add default via 192.168.88.1
uci set network.nmtest=interface
uci set network.nmtest.proto=static
uci set network.nmtest.device=nm-router
uci set network.nmtest.ipaddr=192.168.88.1
uci set network.nmtest.netmask=255.255.255.0
uci set network.nmtest.ip6addr=fd88::1/64
uci commit network
ifup nmtest
uci delete netmon.main.networks
uci add_list netmon.main.networks=nmtest
uci commit netmon
# Test VM-only forwarding and source NAT to the QEMU user network.
nft insert rule inet fw4 forward iifname nm-router accept
nft insert rule inet fw4 forward oifname nm-router accept
nft add table ip nmtest
nft 'add chain ip nmtest postrouting { type nat hook postrouting priority 99; policy accept; }'
nft add rule ip nmtest postrouting ip saddr 192.168.88.0/24 oifname br-lan masquerade
/etc/init.d/netmon restart
