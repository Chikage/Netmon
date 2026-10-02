'use strict';
'require baseclass';

function bytes(n) {
	n = Math.max(0, Number(n) || 0);
	var units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'], i = 0;
	while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
	return (i === 0 ? n.toFixed(0) : n.toFixed(n >= 100 ? 1 : 2)) + ' ' + units[i];
}
function number(n) { return Math.round(n || 0).toLocaleString(); }
function sum(list) { return list.reduce(function(a, b) { return a + b; }, 0); }
function totals(client, window) {
	var values = Object.values((client.windows || {})[window] || {});
	return [0, 1, 2].map(function(i) { return sum(values.map(function(v) { return v[i]; })); });
}
function connections(client) { return sum(Object.values(client.connections || {})); }
function csvCell(value) {
	var text = String(value == null ? '' : value);
	if (/^[=+@\-\t\r\n]/.test(text)) text = "'" + text;
	return '"' + text.replace(/"/g, '""') + '"';
}
function exportCSV(clients, window, categories) {
	var rows = [['客户端', 'MAC', 'IP', '时间窗口秒', '上传字节', '下载字节', '当前连接数', '窗口内新增连接']];
	clients.forEach(function(client) {
		var total = totals(client, window);
		rows.push([client.name || client.ips[0], client.mac, client.ips.join(' / '), window,
			total[0], total[1], connections(client), total[2]]);
	});
	rows.push([], ['客户端', '分类', '上传字节', '下载字节', '当前连接数']);
	clients.forEach(function(client) {
		categories.forEach(function(cat) {
			var v = ((client.windows || {})[window] || {})[cat.id] || [0, 0, 0];
			rows.push([client.name || client.ips[0], cat.label, v[0], v[1], (client.connections || {})[cat.id] || 0]);
		});
	});
	return '\uFEFF' + rows.map(function(row) { return row.map(csvCell).join(','); }).join('\r\n');
}

function create(initial) {
	var data = initial || {}, window = '1800', selected = '', mode = 'bytes', paused = false, query = '';
	var order = 'traffic', lastError = '';
	var status = E('span', { 'class': 'nm-status', role: 'status' });
	var stamp = E('span', { 'class': 'nm-muted' });
	var period = E('select', { id: 'nm-period', change: function() { window = this.value; draw(); } },
		[['300', '近 5 分钟'], ['1800', '近 30 分钟'], ['3600', '近 1 小时'], ['86400', '近 24 小时']].map(function(v) {
			return E('option', { value: v[0] }, v[1]);
		}));
	period.value = window;
	var clientSelect = E('select', { id: 'nm-client', change: function() { selected = this.value; draw(); } });
	var search = E('input', { id: 'nm-search', type: 'search', placeholder: '搜索名称、IP 或 MAC',
		input: function() { query = this.value.trim().toLowerCase(); draw(); } });
	var pause = E('button', { type: 'button', 'class': 'nm-button', 'aria-pressed': 'false', click: function() {
		paused = !paused; this.textContent = paused ? '继续刷新' : '暂停刷新';
		this.setAttribute('aria-pressed', String(paused)); draw();
	} }, '暂停刷新');
	var warning = E('div', { 'class': 'nm-notice', role: 'status' });
	var metrics = E('div', { 'class': 'nm-metrics' });
	var distribution = E('div', { 'class': 'nm-distribution' });
	var table = E('div', { 'class': 'nm-table-scroll', tabindex: '0', 'aria-label': '客户端统计表，可横向滚动' });
	var scope = E('span', { 'class': 'nm-muted' });
	var trafficButton = E('button', { type: 'button', click: function() { mode = 'bytes'; draw(); } }, '流量');
	var connectionButton = E('button', { type: 'button', click: function() { mode = 'connections'; draw(); } }, '当前连接数');
	var sort = E('select', { id: 'nm-order', change: function() { order = this.value; draw(); } }, [
		E('option', { value: 'traffic' }, '按总流量排序'), E('option', { value: 'connections' }, '按连接数排序')
	]);
	var download = E('button', { type: 'button', 'class': 'nm-button', click: function() {
		var blob = new Blob([exportCSV(filtered(), window, data.categories || [])], { type: 'text/csv;charset=utf-8' });
		var url = URL.createObjectURL(blob), link = E('a', { href: url, download: 'netmon-' + window + 's.csv' });
		document.body.appendChild(link); link.click(); link.remove();
		setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
	} }, '导出 CSV');
	var root = E('div', { 'class': 'netmon' }, [
		E('header', { 'class': 'nm-header' }, [
			E('div', {}, [E('div', { 'class': 'nm-eyebrow' }, 'NETMON / 网络观测'),
				E('h2', {}, '客户端流量'), E('p', { 'class': 'nm-muted' }, '了解流量去向，查看每台设备的连接分布。')]),
			E('div', { 'class': 'nm-live' }, [status, stamp])
		]),
		E('div', { 'class': 'nm-toolbar' }, [
			E('div', { 'class': 'nm-field' }, [E('label', { 'for': 'nm-period' }, '流量时间范围'), period]),
			E('div', { 'class': 'nm-field nm-client-field' }, [E('label', { 'for': 'nm-client' }, '统计客户端'), clientSelect]),
			E('div', { 'class': 'nm-actions' }, [pause, download])
		]), warning, metrics,
		E('section', { 'class': 'nm-card' }, [
			E('div', { 'class': 'nm-card-heading' }, [
				E('div', {}, [E('h3', {}, '流量 / 连接数分布'), E('p', { 'class': 'nm-muted' }, '按服务端口与自定义规则分类 · 规则推断')]),
				E('div', { 'class': 'nm-segment', 'aria-label': '分布统计方式' }, [trafficButton, connectionButton])
			]), distribution
		]),
		E('section', { 'class': 'nm-card' }, [
			E('div', { 'class': 'nm-card-heading nm-clients-heading' }, [
				E('div', {}, [E('h3', {}, '客户端明细'), scope]),
				E('div', { 'class': 'nm-table-tools' }, [E('label', { 'class': 'nm-sr-only', 'for': 'nm-search' }, '搜索客户端'), search,
					E('label', { 'class': 'nm-sr-only', 'for': 'nm-order' }, '排序方式'), sort])
			]), table
		]),
		E('footer', { 'class': 'nm-footnote' }, [
			E('p', {}, '统计经过本机路由的客户端流量，不含路由器自身与 LAN 内部交换流量。流量为三层字节数，包含协议头和重传。'),
			E('p', {}, '时间窗口按分钟聚合；当前连接数为连接跟踪条目数（含 TCP TIME_WAIT、UDP），不随时间范围变化。端口分类可能误判，HTTPS / QUIC 不代表已识别出具体应用。历史保存在内存中，重启服务后重新累计。')
		])
	]);

	function filtered() {
		return (data.clients || []).filter(function(c) {
			return (!selected || selected === c.id) && (!query || [c.name, c.mac].concat(c.ips).join(' ').toLowerCase().indexOf(query) >= 0);
		});
	}
	function metric(label, value, hint, accent) {
		return E('div', { 'class': 'nm-card nm-metric' + (accent ? ' nm-accent' : '') }, [
			E('div', { 'class': 'nm-metric-label' }, label), E('strong', {}, value), E('span', { 'class': 'nm-muted' }, hint)
		]);
	}
	function draw() {
		var cats = data.categories || [], clients = (data.clients || []).filter(function(c) { return !selected || c.id === selected; });
		var upload = sum(clients.map(function(c) { return totals(c, window)[0]; }));
		var down = sum(clients.map(function(c) { return totals(c, window)[1]; }));
		var count = sum(clients.map(connections)), total = upload + down;
		var healthy = data.running && data.collecting !== false && !lastError;
		status.textContent = !healthy ? '采集异常 / 已停止' : paused ? '显示已暂停' : '正在采集';
		status.className = 'nm-status' + (healthy ? '' : ' nm-status-error');
		stamp.textContent = data.generated_at ? '更新于 ' + new Date(data.generated_at * 1000).toLocaleTimeString() : '等待首个采样';
		warning.replaceChildren();
		var warnings = (lastError ? [lastError] : []).concat(data.warnings || []);
		warning.hidden = !warnings.length;
		warnings.forEach(function(w) { warning.appendChild(E('div', {}, w)); });
		metrics.replaceChildren(
			metric('所选时段总流量', bytes(total), '上传 + 下载', true),
			metric('下载流量', bytes(down), '当前 ' + bytes(sum(clients.map(function(c) { return c.download_rate; }))) + '/s'),
			metric('上传流量', bytes(upload), '当前 ' + bytes(sum(clients.map(function(c) { return c.upload_rate; }))) + '/s'),
			metric('当前连接数', number(count), number(clients.filter(function(c) { return connections(c) > 0; }).length) + ' 台客户端有连接')
		);
		trafficButton.setAttribute('aria-pressed', String(mode === 'bytes'));
		connectionButton.setAttribute('aria-pressed', String(mode === 'connections'));
		var values = cats.map(function(cat) {
			return sum(clients.map(function(c) {
				if (mode === 'connections') return (c.connections || {})[cat.id] || 0;
				var v = ((c.windows || {})[window] || {})[cat.id] || [0, 0]; return v[0] + v[1];
			}));
		});
		var denominator = sum(values), angle = 0, stops = [];
		cats.forEach(function(cat, i) {
			if (!values[i]) return;
			var end = angle + values[i] / denominator * 360;
			var color = /^#[0-9a-f]{6}$/i.test(cat.color) ? cat.color : '#8290ae';
			stops.push(color + ' ' + angle + 'deg ' + end + 'deg'); angle = end;
		});
		var chart = E('div', { 'class': 'nm-donut', role: 'img',
			'aria-label': (mode === 'bytes' ? '总流量 ' + bytes(denominator) : '当前连接数 ' + number(denominator)) + '，各分类详情见右侧列表',
			style: 'background:' + (denominator ? 'conic-gradient(' + stops.join(',') + ')' : 'var(--nm-border)') }, [
			E('div', { 'class': 'nm-donut-hole' }, [E('strong', {}, mode === 'bytes' ? bytes(denominator) : number(denominator)),
				E('span', { 'class': 'nm-muted' }, denominator ? (mode === 'bytes' ? '总流量' : '当前连接数') : '暂无数据')])
		]);
		var legend = E('ul', { 'class': 'nm-legend' }, cats.map(function(cat, i) {
			return E('li', {}, [E('span', { 'class': 'nm-swatch', style: 'background:' + (/^#[0-9a-f]{6}$/i.test(cat.color) ? cat.color : '#8290ae'), 'aria-hidden': 'true' }),
				E('span', { 'class': 'nm-category' }, cat.label), E('strong', {}, mode === 'bytes' ? bytes(values[i]) : number(values[i]) + ' 条'),
				E('span', { 'class': 'nm-percent' }, (denominator ? values[i] / denominator * 100 : 0).toFixed(1) + '%')]);
		}));
		distribution.replaceChildren(E('div', { 'class': 'nm-chart-wrap' }, chart), legend);
		var rows = filtered().sort(function(a, b) {
			return order === 'connections' ? connections(b) - connections(a) :
				sum(totals(b, window).slice(0, 2)) - sum(totals(a, window).slice(0, 2));
		});
		scope.textContent = rows.length + ' 台客户端 · ' + (data.subnets || []).join('、');
		download.disabled = rows.length === 0;
		var body = E('tbody');
		rows.forEach(function(c) {
			var v = totals(c, window), all = v[0] + v[1], counts = connections(c);
			body.appendChild(E('tr', {}, [
				E('td', {}, [E('strong', { 'class': 'nm-client-name' }, c.name || '未命名设备'),
					E('span', { 'class': 'nm-address' }, c.ips.join(' · ')), E('span', { 'class': 'nm-address' }, c.mac || 'MAC 待发现')]),
				E('td', { 'class': 'nm-numeric' }, bytes(v[1])), E('td', { 'class': 'nm-numeric' }, bytes(v[0])),
				E('td', { 'class': 'nm-numeric' }, [E('strong', {}, bytes(all)), E('div', { 'class': 'nm-bar', 'aria-hidden': 'true' },
					E('span', { style: 'width:' + Math.min(100, total ? all / total * 100 : 0) + '%' }))]),
				E('td', { 'class': 'nm-numeric' }, E('span', { 'class': 'nm-count' }, number(counts))),
				E('td', { 'class': 'nm-numeric' }, number(v[2])),
				E('td', {}, E('button', { type: 'button', 'class': 'nm-detail', 'data-client-id': c.id,
					'aria-label': '查看 ' + (c.name || c.ips[0]) + ' 的分类', click: function() {
						selected = selected === c.id ? '' : c.id; clientSelect.value = selected; draw();
					} }, selected === c.id ? '查看全部' : '查看分类'))
			]));
		});
		if (!rows.length) body.appendChild(E('tr', {}, E('td', { colspan: '7', 'class': 'nm-empty' },
			query ? '没有匹配的客户端，请调整搜索内容。' : '尚无客户端流量。请确认 LAN 网络设置，并让客户端访问网络。')));
		var focused = document.activeElement && document.activeElement.getAttribute('data-client-id');
		table.replaceChildren(E('table', {}, [E('thead', {}, E('tr', {},
			['客户端', '下载', '上传', '总流量', '当前连接', '时段新增连接', '分类详情'].map(function(t) { return E('th', { scope: 'col' }, t); }))), body]));
		if (focused) Array.from(table.querySelectorAll('[data-client-id]')).some(function(button) {
			if (button.getAttribute('data-client-id') === focused) { button.focus({ preventScroll: true }); return true; } return false;
		});
	}
	function update(next) {
		data = next || {}; lastError = '';
		if (selected && !(data.clients || []).some(function(c) { return c.id === selected; })) selected = '';
		clientSelect.replaceChildren(E('option', { value: '' }, '全部客户端'));
		(data.clients || []).forEach(function(c) {
			clientSelect.appendChild(E('option', { value: c.id }, (c.name || c.ips[0]) + (c.name ? ' · ' + c.ips[0] : '')));
		});
		clientSelect.value = selected; draw();
	}
	update(data);
	return { root: root, update: update, paused: function() { return paused; }, error: function(msg) { lastError = msg; draw(); } };
}

return baseclass.extend({ create: create, bytes: bytes, exportCSV: exportCSV });
