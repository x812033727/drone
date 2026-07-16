# 噴灑作業遙測(對齊 dialect SPRAY_TELEMETRY 24151;作業中 2 Hz)
uint64 timestamp                  # 系統啟動起算(microseconds)
float32 flow_rate_ml_s            # 目前流量
float32 flow_rate_setpoint_ml_s   # 目標流量;NaN=無設定值
float32 volume_remaining_ml       # 藥箱剩餘;NaN=無液位感測
float32 volume_consumed_ml        # 本次作業累計噴出
float32 application_rate_ml_m2    # 單位面積施用量;NaN=未量測
float32 pump_pressure_bar         # 泵出口壓力;NaN=無感測
float32 boom_width_m              # 有效噴幅
uint16 spray_flags                # DRONE_SPRAY_FLAGS bitmask;0=正常
uint8 pump_state                  # DRONE_SPRAY_PUMP_STATE
uint8 nozzles_active              # 作用中噴頭數
