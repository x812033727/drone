# 智慧電池電芯級詳情(對齊 dialect BATTERY_DETAIL 24152;0.2-1 Hz)
uint64 timestamp                  # 系統啟動起算(microseconds)
uint32 fault_flags                # DRONE_BATTERY_FAULT_FLAGS bitmask;0=無故障
uint32 capacity_full_charge_mah   # 滿充容量;0=未知
uint32 capacity_remaining_mah     # 剩餘容量;0=未知
uint16[14] cell_voltages_mv       # 各電芯電壓;未用槽位 UINT16_MAX
uint16 cycle_count                # 循環數;UINT16_MAX=未知
int16 temperature_cdegc           # 電池組溫度;INT16_MAX=未知
int16 current_ca                  # 放電正/充電負;INT16_MAX=未知
uint8 id                          # 對應 BATTERY_STATUS.id
uint8 cell_count                  # 有效電芯數;UINT8_MAX=未知
uint8 state_of_health             # SoH 0-100;UINT8_MAX=未知
uint8 state_of_charge             # SoC 0-100;UINT8_MAX=未知
