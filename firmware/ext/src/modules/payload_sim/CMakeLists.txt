px4_add_module(
	MODULE modules__payload_sim
	MAIN payload_sim
	SRCS
		PayloadSim.cpp
	EXTERNAL
)
# 刻意不列 DEPENDS px4_work_queue:v1.15 的 external modules 在主樹 lib target
# 定義前被 add_subdirectory(實測 get_target_property 會炸);ScheduledWorkItem
# 的符號由最終 px4 binary 連結解析(px4_work_queue 恆在 SITL 建置內)。
