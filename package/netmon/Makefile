include $(TOPDIR)/rules.mk

PKG_NAME:=netmon
PKG_VERSION:=1.0.0
PKG_RELEASE:=2
PKG_LICENSE:=MIT
PKGARCH:=all

include $(INCLUDE_DIR)/package.mk

define Package/netmon
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Per-client conntrack traffic accounting
  DEPENDS:=+python3-light +conntrack +kmod-nf-conntrack-netlink +rpcd +uci +ubus +ip
endef

define Package/netmon/conffiles
/etc/config/netmon
endef

define Build/Compile
endef

define Package/netmon/install
	$(CP) ./files/* $(1)/
	chmod 0755 $(1)/etc/init.d/netmon $(1)/usr/libexec/rpcd/luci.netmon
endef

$(eval $(call BuildPackage,netmon))
