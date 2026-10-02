const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const resource = path.join(root, 'package/luci-app-netmon/files/www/luci-static/resources');
const source = fs.readFileSync(path.join(resource, 'netmon/dashboard.js'), 'utf8');
const dashboard = new Function('baseclass', source)({ extend: x => x });
assert.equal(dashboard.bytes(0), '0 B');
assert.equal(dashboard.bytes(1024), '1.00 KiB');
assert.equal(dashboard.bytes(-1), '0 B');
const clients = [{name: '=SUM(A1)', mac: 'aa:bb:cc:dd:ee:ff', ips: ['192.0.2.1'],
    windows: {'300': {http: [10, 20, 1]}}, connections: {http: 2}}];
const csv = dashboard.exportCSV(clients, '300', [{id:'http',label:'HTTP'}]);
assert.ok(csv.startsWith('\uFEFF'));
assert.ok(csv.includes('"\'=SUM(A1)"'));
assert.ok(csv.includes('"10","20","2","1"'));
for (const file of ['view/netmon/overview.js', 'view/netmon/settings.js']) {
    new Function(fs.readFileSync(path.join(resource, file), 'utf8'));
}
console.log('Frontend: formatting, CSV injection protection, CSV totals and LuCI syntax passed');
