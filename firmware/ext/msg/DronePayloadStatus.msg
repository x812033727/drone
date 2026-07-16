# 酬載通用狀態(對齊 dialect PAYLOAD_STATUS 24150;1 Hz)
uint64 timestamp           # 系統啟動起算(microseconds)
uint32 fault_flags         # DRONE_PAYLOAD_FAULT_FLAGS bitmask;0=無故障
uint32 firmware_version    # (major<<24)|(minor<<16)|(patch<<8)|type;0=未知
int16 temperature_cdegc    # 酬載內部溫度;INT16_MAX=未知
uint8 payload_type         # DRONE_PAYLOAD_TYPE
uint8 payload_id           # 酬載實例編號(單掛點固定 0)
uint8 state                # DRONE_PAYLOAD_STATE
uint8 vendor_status        # 廠商自定子狀態;無定義時 0
