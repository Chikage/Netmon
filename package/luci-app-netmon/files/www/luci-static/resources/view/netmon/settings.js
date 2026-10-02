'use strict';
'require view';
'require form';

return view.extend({
	render: function() {
		var m = new form.Map('netmon', '客户端流量设置', '保存并应用后会重启采集服务，内存历史将清空。默认仅统计经过本机路由的 LAN 客户端。');
		var s = m.section(form.NamedSection, 'main', 'netmon', '采集设置');
		var o = s.option(form.Flag, 'enabled', '启用采集'); o.default = '1'; o.rmempty = false;
		o = s.option(form.Value, 'interval', '采样间隔（秒）'); o.datatype = 'range(2,60)'; o.default = '5'; o.rmempty = false;
		o = s.option(form.DynamicList, 'networks', '客户端逻辑网络', '填写 OpenWrt 逻辑接口名称，例如 lan、guest；不是 br-lan 这样的设备名。');
		o.default = 'lan'; o.rmempty = false; o.datatype = 'uciname';
		o = s.option(form.DynamicList, 'subnets', '附加客户端网段', '可选，例如 192.168.20.0/24 或 fd00:20::/64；不要填写 WAN 网段。'); o.datatype = 'cidr';
		o = s.option(form.Value, 'max_flows', '最大跟踪连接数', '默认 32768。达到上限会显示告警；内存占用随客户端和连接数增加。');
		o.datatype = 'range(1024,262144)'; o.default = '32768'; o.rmempty = false;
		s = m.section(form.GridSection, 'rule', '自定义分类规则', '按顺序匹配，优先于内置规则。协议、服务端口、对端网段同时满足才命中；留空的端口或网段表示不限制。不会修改防火墙。');
		s.anonymous = true; s.addremove = true; s.sortable = true;
		o = s.option(form.Flag, 'enabled', '启用'); o.default = '1'; o.rmempty = false;
		s.option(form.Value, 'name', '备注');
		o = s.option(form.ListValue, 'category', '分类');
		[['http','HTTP 协议'],['tls','HTTPS / QUIC'],['p2p','P2P 下载'],['video','流媒体协议'],['game','网络游戏'],['file','文件传输'],['chat','网络通讯'],['dns','DNS 解析'],['common','常用协议'],['speed','测速工具'],['unknown','未分类']].forEach(function(v) { o.value(v[0], v[1]); });
		o.default = 'p2p'; o.rmempty = false;
		o = s.option(form.ListValue, 'proto', '传输协议');
		['any','tcp','udp','icmp','icmpv6','sctp','gre'].forEach(function(v) { o.value(v, v === 'any' ? '任意协议' : v.toUpperCase()); });
		o.default = 'any'; o.rmempty = false;
		o.validate = function(section, value) {
			return value !== 'any' || this.section.formvalue(section, 'ports') || this.section.formvalue(section, 'cidr') ? true : '请至少指定传输协议、服务端口或对端网段';
		};
		o = s.option(form.Value, 'ports', '服务端口', '例如 6881-6999,51413。客户端主动连接时匹配目的端口，外网主动连接时匹配 NAT 后客户端服务端口。');
		o.placeholder = '6881-6999,51413';
		o.validate = function(section, value) {
			if (!value) return true;
			return value.split(/[ ,]+/).filter(Boolean).every(function(v) {
				if (!/^\d+(?:-\d+)?$/.test(v)) return false;
				var p = v.split('-').map(Number); return p[0] >= 1 && p[0] <= 65535 && (p.length === 1 || (p[1] >= p[0] && p[1] <= 65535));
			}) || '请输入 1–65535 的端口或范围，用逗号分隔';
		};
		o = s.option(form.Value, 'cidr', '对端网段（可选）'); o.datatype = 'cidr';
		return m.render();
	}
});
