# 验证记录

验证日期：2026-10-02（Asia/Shanghai）。

## r2：IPK 父目录缺失修复

用户设备确认为 **Kwrt 25.12.5（07.04.2026）、x86_64、opkg**，而非使用 APK 的官方 OpenWrt 25.12 镜像。

旧版 `1.0.0-1` IPK 的 data.tar.gz 只包含普通文件，没有父目录条目。opkg 的 `pkg_extract_data_files_to_dir()` 未启用 `extract_create_leading_dirs`，因此新目录中的文件写入失败；已有目录中的菜单仍能写入，包状态也可能显示已安装。此前仅验证 IPK 归档结构不足以发现这一问题。

在全新的官方 **OpenWrt 24.10.5 x86_64** 虚拟机中使用真实 opkg 验证：

- 干净安装 `1.0.0-2`，依赖解析和安装成功。
- 清理测试插件目录后安装旧 `1.0.0-1`，复现 `wfopen: ... No such file or directory`，包括两个后台 Python 文件和四个前端文件；菜单存在、包状态为已安装。
- 将旧版直接升级到 `1.0.0-2` 后，全部文件落盘，手动设定的 `interval=7` 配置保留。
- `overview.js` 返回 HTTP 200，内容与源码逐字节一致。
- `ubus call luci.netmon status` 返回 `running=true`、`collecting=true`、`event_stream=true`，无告警。
- 新增两个回归测试：严格按照 opkg 不自动创建父目录的行为，分别将后台包和前端包解包到空目录。总计 **32 / 32** 测试通过。

修正版为两个 `1.0.0-2_all.ipk`；APK 同步更新到 `1.0.0-r2`，并通过 apk-tools 原生验证。用户实际 Kwrt 的升级操作尚需用户执行。

以下记录保留首次开发时的 APK 和功能验证范围。

## 环境

- 一次性 QEMU x86_64 虚拟机，官方 OpenWrt **25.12.5**，版本 `r33051-f5dae5ece4`，Linux `6.12.94`。
- 官方镜像：`openwrt-25.12.5-x86-64-generic-ext4-combined.img.gz`。
- 镜像 SHA-256：`23e2538e8ab0eb52dfed1c65d608ecdb71ffd432dd54885da138ae67cd9e4461`。
- 使用 APK 3.0.5 实际安装两个 APK，验证 procd、rpcd、LuCI、内核连接跟踪。
- 分别验证 ip-tiny 和 ip-full 提供 ip 命令的安装环境。升级检查使用同分支官方软件源更新后的依赖，用户配置得以保留。
- 未连接用户实际 N100 路由器；没有做 N100 满带宽、硬件分载或大规模客户端压力测试。

## 自动化检查

`python3 -m unittest discover -s tests -v`：**30 / 30 通过**。

覆盖双向增量、启动前字节排除、初始快照与 NEW 事件交错、短连接结束计数、重复 DESTROY 去重、乱序计数、延迟结束事件、DNAT 方向与端口、IPv6、MAC 合并、窗口过期、64 位计数、容量上限、缺少 accounting、offload 标记、协议解析、UCI 配置及规则验证。

`node tests/test_frontend.cjs`：格式化、CSV 总计、CSV 公式注入处理、三个 LuCI JavaScript 模块语法检查通过。

APK 原生 `verify --allow-untrusted` 通过；包内所有者为 root:root。IPK 的外层归档、`debian-binary`、control/data 归档、路径和所有者检查通过。LuCI 菜单与 ACL JSON 解析通过。

使用固定构建时间重新打包，两个 APK 的 SHA-256 均与前一次逐字节一致。未登录 HTTP JSON-RPC 请求返回 `Access denied`；停止服务后，状态快照正确变为 `running: false`。

## 真实转发测试

在虚拟机中建立隔离网络命名空间，测试客户端 `192.168.88.2` 通过 veth 与 OpenWrt 路由/NAT 访问宿主机的测试服务。

1. 等待采集服务完成首次快照并确认事件监听就绪。
2. TCP 8080 传输 **1,048,644 字节**（HTTP 响应头 + 1 MiB 正文）。
3. TCP 51413 传输 **262,144 字节**，用于测试 P2P **端口规则**，不是验证 BitTorrent DPI。
4. 快照按客户端 MAC 归并，并将两条连接归类为 HTTP / P2P；下载计数大于应用层载荷，包含 IP/TCP 头。
5. 第一轮采集数据显示 2 条连接。删除测试连接后，当前连接数变为 0，历史流量与每类 1 个新增连接保留。
6. 最终 APK 替换安装后再次传输，HTTP / P2P 下载计数分别至少达到上述有效载荷，事件监听正常，无采集告警；服务启动前已有的 conntrack 条目仍参与当前连接数，但不会当作新增连接。

无浏览器模拟数据注入，界面读数来自上述真实经过内核 conntrack 的转发流量。

## 页面验证

- 实际 LuCI 登录后打开“状态 → 客户端流量”。
- 默认近 30 分钟、按客户端筛选、流量/当前连接数切换、搜索无结果状态正常。
- 设置页正常显示采集配置与自定义规则表单。
- 在 375 px 宽度检查自适应布局，明细表通过自身容器横向滚动。
- 修复 LuCI 全局 header 样式干扰；页面遵循系统浅色/深色偏好。
- 安装/升级导致 rpcd 重启时，需要重新登录 LuCI。

## 尚未验证的边界

SDK 完整编译、高连接数长期压力、各厂商加速引擎兼容性与实际 N100 硬件性能未验证。IPv6/NAT 方向由单元测试覆盖；真实转发实验使用 IPv4。端口规则的应用识别准确率没有做数据集评估，不应将其等同于 DPI。IPK 的追加安装验证见上方 r2 记录。
