include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-netmon
PKG_VERSION:=1.0.0
PKG_RELEASE:=2
PKG_LICENSE:=MIT
PKGARCH:=all

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-netmon
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=LuCI client traffic and connection dashboard
  DEPENDS:=+luci-base +netmon
endef

define Build/Compile
endef

define Package/luci-app-netmon/install
	$(CP) ./files/* $(1)/
endef

$(eval $(call BuildPackage,luci-app-netmon))
