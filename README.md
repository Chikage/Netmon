# Netmon：OpenWrt 客户端流量分类与连接数

面向 **Intel N100 / x86_64** 的 OpenWrt / Kwrt LuCI 插件。安装后进入 **状态 → 客户端流量**。

提供每台客户端的上传、下载、当前连接数、时段内新增连接、分类环形图、搜索、排序、自定义规则和 CSV 导出。支持 IPv4 / IPv6，在邻居表提供 MAC 时合并同一设备的多个地址。

## 下载文件与版本

**按设备实际包管理器选择格式，不要只看固件版本号。** 官方 OpenWrt 25.12 使用 APK；已确认的 **Kwrt 25.12.5（07.04.2026）使用 opkg**，应安装下面的 IPK。

使用 APK 的设备安装这两个文件：

- `dist/netmon-1.0.0-r2.apk`：采集服务。
- `dist/luci-app-netmon-1.0.0-r2.apk`：LuCI 页面。

包的架构为 `noarch`：代码是 Python 与 JavaScript，没有需要绑定 CPU 的二进制；运行依赖由设备的 x86_64 官方软件源安装。

同时生成 `dist/netmon_1.0.0-2_all.ipk` 和 `dist/luci-app-netmon_1.0.0-2_all.ipk`，供仍使用 opkg 的 OpenWrt 系统使用。**不要把 IPK 改扩展名后安装到 25.12。** 旧版 `1.0.0-1` IPK 漏打父目录条目，会造成 opkg 显示已安装但新目录中的文件缺失；请使用已修复的 `1.0.0-2`。

## 安装或修复 Kwrt / opkg 设备

将下面两个文件上传到路由器 `/tmp/`：

- `netmon_1.0.0-2_all.ipk`
- `luci-app-netmon_1.0.0-2_all.ipk`

执行下面这一整行：

```sh
opkg install /tmp/netmon_1.0.0-2_all.ipk /tmp/luci-app-netmon_1.0.0-2_all.ipk
```

从 `1.0.0-1` 升级无需卸载或添加 `--force-depends`。两个包都要更新：旧包还可能漏掉 `/usr/lib/netmon/` 中的采集代码。现有 `/etc/config/netmon` 配置由 opkg 保留；重启采集服务会重新开始累计内存历史。

安装后可核对：

```sh
ls -l /usr/lib/netmon/ /www/luci-static/resources/view/netmon/ /www/luci-static/resources/netmon/; ubus call luci.netmon status
```

重新登录 LuCI 并强制刷新页面。使用 Nginx 且恢复资源后仍返回旧 404 时，执行 `nginx -t && /etc/init.d/nginx reload`。

## 安装到官方 OpenWrt 25.12 / APK 设备

将两个 `.apk` 上传到路由器 `/tmp/`，通过 SSH 执行：

```sh
apk update
apk add --allow-untrusted /tmp/netmon-1.0.0-r2.apk /tmp/luci-app-netmon-1.0.0-r2.apk
```

`--allow-untrusted` 用于安装本地生成的未签名包，不会修改全局 APK 信任设置。发布包的 SHA-256 在 `dist/SHA256SUMS`。

安装脚本自动启用并启动服务，重新加载 rpcd。随后重新登录 LuCI，进入 **状态 → 客户端流量 → 流量统计**。安装或升级时 rpcd 重启会结束现有 LuCI 会话。

依赖包括 `python3-light`、`conntrack`、`kmod-nf-conntrack-netlink`、`rpcd`、`uci`、`ubus`、`ip`、`luci-base`；可以使用 `ip-tiny` 或 `ip-full` 提供 `ip`。设备需要能访问与你固件版本匹配的软件源。本项目没有捆绑内核模块，避免内核版本不匹配。

## 采集设置

- **客户端逻辑网络**：默认 `lan`，这是 `/etc/config/network` 中的逻辑接口名，不是 `br-lan`。访客网络可增加 `guest`。
- **附加客户端网段**：可以手动指定 IPv4 / IPv6 CIDR；只添加客户端网段。
- **采样间隔**：默认 5 秒，可设为 2–60 秒。前台每 5 秒读取已有快照。
- **最大跟踪连接数**：默认 32768，可设为 1024–262144；服务最多保留 512 台客户端的历史，超限会提示统计不完整。
- **历史**：按 60 秒聚合，保留最近 24 小时，提供近 5 分钟、30 分钟、1 小时、24 小时视图。窗口边界按整分钟处理，最多包含边界前 59 秒。

保存并应用设置、重启服务或路由器都会清空内存历史。状态快照位于 `/tmp/netmon/status.json`，默认不持续写入闪存。IPv6 临时地址在无法获得 MAC 时暂时独立显示；获得邻居映射后合并。

## 分类规则与准确性

**这是规则分类插件，未集成 nDPI，不进行深度包检测。** 同一端口可承载不同应用，P2P 随机端口、加密视频/游戏等不能靠端口准确识别。页面明确标记“规则推断”，不会把所有 HTTPS 流量标为视频，也不会将“未分类”等同于某种应用。

| 分类 | 内置协议 / 服务端口 |
| --- | --- |
| HTTP | TCP 80、8080 |
| HTTPS / QUIC | TCP 443、8443；UDP 443 |
| P2P 下载 | TCP / UDP 6881–6999、51413 等规则匹配的传输协议 |
| 流媒体协议 | 554、1935 |
| 网络游戏 | 3074、27015–27030 |
| 文件传输 | TCP 20、21、139、445；UDP 69 |
| 网络通讯 | 5060、5061、5222、5223 |
| DNS 解析 | 53、853 |
| 常用协议 | SSH、邮件、NTP、RDP、部分 VPN 的常用端口，以及 ICMP / ICMPv6 / GRE |
| 测速工具 | 5201（iperf3 常用端口） |
| 未分类 | 其余流量 |

上述分类是服务端口的推断，DNS over HTTPS 等混合在 HTTPS 类中。视频类不是视频网站名单，测速类也不代表能识别所有测速网站。

自定义规则优先于内置规则，按页面顺序匹配；协议、服务端口与对端网段三个条件同时满足才命中。客户端主动连接时使用目的服务端口；外网主动连接、端口映射场景使用 NAT 后客户端的服务端口。不会依据客户端临时源端口误判 P2P。规则只影响统计标签，不修改防火墙。

例如，为使用 50000 端口的 BT 客户端添加：

```sh
uci add netmon rule
uci set netmon.@rule[-1].enabled='1'
uci set netmon.@rule[-1].name='BT 50000'
uci set netmon.@rule[-1].category='p2p'
uci set netmon.@rule[-1].proto='any'
uci set netmon.@rule[-1].ports='50000'
uci commit netmon
/etc/init.d/netmon restart
```

## 统计口径与限制

- 数据源为 Linux conntrack 原始方向 / 回复方向字节计数，并监听 NEW / DESTROY 事件以补齐短连接结束时的字节。采用单调增量与连接 ID 去重，防止轮询和结束事件重复计算。
- 只统计经过本机路由的客户端连接；不计路由器自身、客户端访问路由器本地服务、LAN 内部交换和同网段 hairpin 流量。使用路由器 DNS 代理的查询不会出现在 DNS 分类中。旁路由只能看到实际经过自己的流量。
- “当前连接数”是 conntrack 表条目数，包含 TCP TIME_WAIT、UDP 等状态；不是仅统计 TCP ESTABLISHED。它不随历史流量窗口变化。“时段新增连接”是服务在该窗口首次观察到的连接数；服务启动时已有连接不作为新增。
- 字节包含三层协议头与重传，不等于文件有效载荷或二层网卡计数。启动时已有连接的历史字节不会直接计入新窗口。
- 服务启动时启用 `nf_conntrack_acct` 和 `nf_conntrack_events`，不清空连接表。已存在且未开启记账的连接要等重新建立后才能得到流量；停止服务不会关闭共享的内核记账功能。
- 软件 / 硬件 flow offload、NSS、SFE、厂商加速等可能绕过 conntrack 更新。检测到常见 offload 配置或内核标记时会显示提示。需要完整计数时，在维护窗口关闭对应加速并重新建立连接；插件不会自行改动你的加速或防火墙设置。
- 事件队列丢失、连接表读取失败、容量耗尽、服务停止均有可见提示。高负载时仍可能漏计，不能用作计费依据。
- 不保存报文内容、HTTP URL 或 TLS 内容；快照由 root 读取，通过受 LuCI 登录与 ACL 保护的只读 RPC 提供。没有公开 HTTP 统计接口。

## 诊断与卸载

```sh
/etc/init.d/netmon status
ubus call luci.netmon status
logread -e netmon
cat /proc/sys/net/netfilter/nf_conntrack_acct
```

没有数据时，先核对逻辑网络、客户端是否实际通过本机路由，以及流量分载设置。安装后页面仍提示权限或加载失败时重新登录 LuCI。

### 页面脚本返回 HTTP 404

`HTTP error 404 while loading class file .../view/netmon/overview.js` 表示浏览器未能取得前端文件。先检查文件是否存在、前端包是否安装，以及 Web 服务使用的目录。下面是**一条命令**，粘贴到 SSH 时保留分号：

```sh
ls -l /www/luci-static/resources/view/netmon/ /www/luci-static/resources/netmon/; apk info -L luci-app-netmon; uci -q get uhttpd.main.home
```

正常应存在 `overview.js`、`settings.js`、`dashboard.js`、`style.css` 四个文件。`uhttpd.main.home` 只代表 uhttpd 的目录；如果 HTTP 响应来自 Nginx，还需要核对 Nginx 的 `root` / `alias`，不能仅凭该 UCI 值判断。

对于**已经确认文件缺失、LuCI 网页目录为 `/www`** 的情况，上传 `dist/netmon-luci-assets-1.0.0.tar.gz` 到路由器 `/tmp/`，执行：

```sh
tar -xzf /tmp/netmon-luci-assets-1.0.0.tar.gz -C /www
```

这个资源包只包含原版的四个前端文件，目录权限为 0755，文件权限为 0644，不含采集配置或服务脚本。它用于恢复原包文件，不是功能升级；校验值位于同目录的 `netmon-luci-assets-1.0.0.sha256`。如修改过前端文件，应先备份。

文件存在但仍返回 404 时，重点检查 Nginx 的有效 `root` / `alias`、目录权限和静态资源缓存，而不是反复重装采集服务。在确认 Nginx 配置有效后可使用 `nginx -t && /etc/init.d/nginx reload` 重新加载，再强制刷新浏览器。实际 Web 根目录不是 `/www` 时，应先确认正确目录再恢复文件。

```sh
apk del luci-app-netmon netmon
```

卸载会停止采集并取消开机自启；包管理器可能保留修改过的配置文件。依赖由包管理器自行处理。

## 源码构建与验证

```sh
python3 -m unittest discover -s tests -v
node tests/test_frontend.cjs
sh scripts/bootstrap-apk.sh
python3 scripts/build.py
```

APK 构建需要 C 编译器、Python、Meson、Ninja、pkg-config、OpenSSL 和 zlib 开发库。bootstrap 脚本校验并编译官方 apk-tools 3.0.5，仅调整本地构建工具的输出所有者为 root:root；工具不会打包到路由器。临时依赖全部放在 `.build/`。

只生成 IPK 不需要 C 编译器：`python3 scripts/build.py --ipk-only`。支持 `SOURCE_DATE_EPOCH`；归档时间、所有者、文件权限固定，可复现构建。

也可以将 `package/netmon`、`package/luci-app-netmon` 放入匹配版本 OpenWrt SDK 的 `package/` 目录，再选择并编译两个包。

`tests/vm_setup.sh`、`tests/traffic_server.py`、`tests/traffic_client.py` 是隔离虚拟机集成测试工具。**vm_setup.sh 会改动测试网络，只能在一次性测试虚拟机运行。** 不要在实际路由器执行。

实际验证记录见 [VALIDATION.md](VALIDATION.md)。

## 官方接口参考

- [OpenWrt 25.12 发布说明：APK 包管理器](https://openwrt.org/releases/25.12/notes-25.12.0)
- [OpenWrt APK 打包流程](https://github.com/openwrt/openwrt/blob/openwrt-25.12/include/package-pack.mk)
- [conntrack 官方命令手册](https://netfilter.org/projects/conntrack-tools/conntrack-manpage.html)
- [LuCI 官方应用示例](https://github.com/openwrt/luci/tree/openwrt-24.10/applications/luci-app-example)
