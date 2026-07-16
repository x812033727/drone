# EXTERNAL_MODULES_LOCATION 模組清單(v1.15 機制:根 CMakeLists 位於 <ext>/src/):
#   make -C <PX4_SRC> px4_sitl_default EXTERNAL_MODULES_LOCATION=<本目錄>
# 模組鏡像 PX4 樹結構(src/modules/<name>),uORB 訊息在 msg/。
set(config_module_list_external
	modules/payload_sim
	PARENT_SCOPE
)
