'use strict';
'require view';
'require rpc';
'require poll';
'require netmon.dashboard as dashboard';

var getStatus = rpc.declare({ object: 'luci.netmon', method: 'status', expect: {} });

return view.extend({
	load: function() { return getStatus(); },
	render: function(data) {
		var panel = dashboard.create(data);
		poll.add(function() {
			if (document.hidden || panel.paused()) return Promise.resolve();
			return getStatus().then(panel.update).catch(function() {
				panel.error('无法读取统计数据，请检查采集服务和登录状态。');
			});
		}, 5);
		return E('div', {}, [
			E('link', { rel: 'stylesheet', href: L.resource('netmon/style.css') }), panel.root
		]);
	},
	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
