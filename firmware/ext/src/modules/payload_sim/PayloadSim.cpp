/**
 * payload_sim — SITL 酬載模擬發布器(out-of-tree 機制驗證 + dialect 資料源)。
 *
 * 以 1 Hz 發布三個自訂 uORB topic(drone_payload_status / drone_spray_status /
 * drone_battery_detail),數值為確定性假值(含無效值慣例:整數型別最大值、
 * 浮點 NaN)。後續 streams patch(F4)把這些 topic 轉為 MAVLink 自訂訊息;
 * 真實酬載/BMS 驅動屬硬體階段,本模組僅供 SITL 契約驗證。
 */

#include <cmath>
#include <cstdint>

#include <drivers/drv_hrt.h>
#include <px4_platform_common/module.h>
#include <px4_platform_common/px4_work_queue/ScheduledWorkItem.hpp>
#include <uORB/Publication.hpp>
#include <uORB/topics/drone_battery_detail.h>
#include <uORB/topics/drone_payload_status.h>
#include <uORB/topics/drone_spray_status.h>

using namespace time_literals;

class PayloadSim : public ModuleBase<PayloadSim>, public px4::ScheduledWorkItem
{
public:
	PayloadSim() : ScheduledWorkItem(MODULE_NAME, px4::wq_configurations::lp_default) {}

	static int task_spawn(int argc, char *argv[]);
	static int custom_command(int argc, char *argv[]) { return print_usage("unknown command"); }
	static int print_usage(const char *reason = nullptr);

	bool init()
	{
		ScheduleOnInterval(1_s);
		return true;
	}

private:
	void Run() override;

	uORB::Publication<drone_payload_status_s> _payload_pub{ORB_ID(drone_payload_status)};
	uORB::Publication<drone_spray_status_s> _spray_pub{ORB_ID(drone_spray_status)};
	uORB::Publication<drone_battery_detail_s> _battery_pub{ORB_ID(drone_battery_detail)};

	uint32_t _tick{0};
};

void PayloadSim::Run()
{
	if (should_exit()) {
		ScheduleClear();
		exit_and_cleanup();
		return;
	}

	const hrt_abstime now = hrt_absolute_time();
	++_tick;

	drone_payload_status_s payload{};
	payload.timestamp = now;
	payload.fault_flags = 0;
	payload.firmware_version = (1u << 24) | (0u << 16) | (0u << 8) | 0u; // 1.0.0-dev
	payload.temperature_cdegc = static_cast<int16_t>(3500 + (_tick % 100)); // 35.00-35.99 degC
	payload.payload_type = 3;  // DRONE_PAYLOAD_TYPE_SPRAYER
	payload.payload_id = 0;
	payload.state = 3;         // DRONE_PAYLOAD_STATE_ACTIVE
	payload.vendor_status = 0;
	_payload_pub.publish(payload);

	drone_spray_status_s spray{};
	spray.timestamp = now;
	spray.flow_rate_ml_s = 120.0f;
	spray.flow_rate_setpoint_ml_s = 120.0f;
	spray.volume_remaining_ml = 10000.0f - 120.0f * static_cast<float>(_tick);
	if (spray.volume_remaining_ml < 0.0f) { spray.volume_remaining_ml = 0.0f; }
	spray.volume_consumed_ml = 120.0f * static_cast<float>(_tick);
	spray.application_rate_ml_m2 = NAN; // 無效值慣例:未量測
	spray.pump_pressure_bar = 2.5f;
	spray.boom_width_m = 4.0f;
	spray.spray_flags = 0;
	spray.pump_state = 2;      // DRONE_SPRAY_PUMP_ACTIVE
	spray.nozzles_active = 8;
	_spray_pub.publish(spray);

	drone_battery_detail_s battery{};
	battery.timestamp = now;
	battery.fault_flags = 0;
	battery.capacity_full_charge_mah = 16000;
	battery.capacity_remaining_mah = 12000;
	for (unsigned i = 0; i < 14; ++i) {
		// 12S 假值:前 12 槽 3.9 V,未用槽位 UINT16_MAX(無效值慣例)
		battery.cell_voltages_mv[i] = (i < 12) ? 3900 : UINT16_MAX;
	}
	battery.cycle_count = 42;
	battery.temperature_cdegc = 2800;
	battery.current_ca = 1500;
	battery.id = 0;
	battery.cell_count = 12;
	battery.state_of_health = 97;
	battery.state_of_charge = 75;
	_battery_pub.publish(battery);
}

int PayloadSim::task_spawn(int argc, char *argv[])
{
	PayloadSim *instance = new PayloadSim();

	if (instance) {
		_object.store(instance);
		_task_id = task_id_is_work_queue;

		if (instance->init()) {
			return PX4_OK;
		}

	} else {
		PX4_ERR("alloc failed");
	}

	delete instance;
	_object.store(nullptr);
	_task_id = -1;
	return PX4_ERROR;
}

int PayloadSim::print_usage(const char *reason)
{
	if (reason) {
		PX4_WARN("%s", reason);
	}

	PRINT_MODULE_DESCRIPTION(
		R"DESCR_STR(
### Description
SITL payload simulator: publishes drone_payload_status / drone_spray_status /
drone_battery_detail at 1 Hz with deterministic fake values (contract testing
for the drone_custom MAVLink dialect; real drivers are hardware-phase work).
)DESCR_STR");

	PRINT_MODULE_USAGE_NAME("payload_sim", "modules");
	PRINT_MODULE_USAGE_COMMAND("start");
	PRINT_MODULE_USAGE_DEFAULT_COMMANDS();
	return 0;
}

extern "C" __EXPORT int payload_sim_main(int argc, char *argv[])
{
	return PayloadSim::main(argc, argv);
}
