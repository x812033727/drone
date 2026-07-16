/**
 * drone_spray — 農噴控制模組骨架(PB-1;SITL 邏輯驗證)。
 *
 * 流量-地速閉環(施用量 = 流量 / 地速 / 幅寬)、斷點記錄(座標 + 已噴量)、
 * 藥箱放電模擬,tank empty → 發 VEHICLE_CMD_NAV_RETURN_TO_LAUNCH（走標準
 * vehicle_command 介面,**不碰 commander 狀態機**）。發布 drone_spray_status
 * 供 SPRAY_TELEMETRY stream(取代 payload_sim 對該 topic 的假值)。
 *
 * SITL 邏輯驗證:真實泵/流量計/藥箱由硬體提供,本模組驗閉環算式與斷藥觸發。
 * 參數:SPRAY_RATE_SET(目標流量 ml/s)、SPRAY_TANK_ML(藥箱容量)、
 *       SPRAY_BOOM_M(噴幅)。
 */

#include <cmath>
#include <cstdint>

#include <drivers/drv_hrt.h>
#include <px4_platform_common/module.h>
#include <px4_platform_common/module_params.h>
#include <px4_platform_common/px4_work_queue/ScheduledWorkItem.hpp>
#include <uORB/Publication.hpp>
#include <uORB/Subscription.hpp>
#include <uORB/topics/drone_spray_status.h>
#include <uORB/topics/vehicle_command.h>
#include <uORB/topics/vehicle_local_position.h>
#include <uORB/topics/vehicle_status.h>

using namespace time_literals;

// DRONE_SPRAY_PUMP_STATE
static constexpr uint8_t PUMP_OFF = 0;
static constexpr uint8_t PUMP_ACTIVE = 2;
// DRONE_SPRAY_FLAGS(bitmask)
static constexpr uint16_t FLAG_TANK_LOW = 1;
static constexpr uint16_t FLAG_TANK_EMPTY = 2;

class DroneSpray : public ModuleBase<DroneSpray>, public ModuleParams,
	public px4::ScheduledWorkItem
{
public:
	DroneSpray() :
		ModuleParams(nullptr),
		ScheduledWorkItem(MODULE_NAME, px4::wq_configurations::lp_default) {}

	static int task_spawn(int argc, char *argv[]);
	static int custom_command(int argc, char *argv[]);
	static int print_usage(const char *reason = nullptr);

	bool init()
	{
		ScheduleOnInterval(500_ms); // 2 Hz(作業中回報頻率)
		return true;
	}

private:
	void Run() override;

	uORB::Subscription _lpos_sub{ORB_ID(vehicle_local_position)};
	uORB::Subscription _status_sub{ORB_ID(vehicle_status)};
	uORB::Publication<drone_spray_status_s> _spray_pub{ORB_ID(drone_spray_status)};
	uORB::Publication<vehicle_command_s> _vcmd_pub{ORB_ID(vehicle_command)};

	DEFINE_PARAMETERS(
		(ParamFloat<px4::params::SPRAY_RATE_SET>) _rate_set,
		(ParamFloat<px4::params::SPRAY_TANK_ML>) _tank_ml,
		(ParamFloat<px4::params::SPRAY_BOOM_M>) _boom_m
	)

	float _volume_remaining{NAN};
	float _volume_consumed{0.0f};
	bool _rtl_sent{false};
	hrt_abstime _last{0};

	// 斷點記錄(座標 + 已噴量)
	double _breakpoint_x{static_cast<double>(NAN)};
	double _breakpoint_y{static_cast<double>(NAN)};

	void send_rtl();
};

void DroneSpray::Run()
{
	if (should_exit()) {
		ScheduleClear();
		exit_and_cleanup();
		return;
	}

	updateParams(); // 拉最新參數(SITL `empty` 鉤以 param_set 改 SPRAY_TANK_ML)

	const hrt_abstime now = hrt_absolute_time();
	if (_last == 0) {
		_last = now;
		_volume_remaining = _tank_ml.get();
	}
	const float dt = static_cast<float>(now - _last) * 1e-6f;
	_last = now;

	// 藥箱容量參數可被下修(SITL `empty` 測試鉤設 0):餘量不得超過當前容量,
	// 故參數降到 0 時餘量即刻歸零(物理上合理)。
	_volume_remaining = fminf(_volume_remaining, _tank_ml.get());

	vehicle_local_position_s lpos{};
	_lpos_sub.copy(&lpos);
	const float ground_speed = sqrtf(lpos.vx * lpos.vx + lpos.vy * lpos.vy);

	vehicle_status_s status{};
	_status_sub.copy(&status);
	const bool armed = status.arming_state == vehicle_status_s::ARMING_STATE_ARMED;

	drone_spray_status_s msg{};
	msg.timestamp = now;
	msg.flow_rate_setpoint_ml_s = _rate_set.get();
	msg.boom_width_m = _boom_m.get();
	msg.pump_pressure_bar = 2.5f;
	msg.nozzles_active = 8;

	// 放電:作業中(armed 且有餘量)以設定流量消耗藥箱
	const bool spraying = armed && _volume_remaining > 0.0f;
	if (spraying) {
		const float used = _rate_set.get() * dt;
		_volume_remaining = fmaxf(0.0f, _volume_remaining - used);
		_volume_consumed += used;
		msg.flow_rate_ml_s = _rate_set.get();
		msg.pump_state = PUMP_ACTIVE;
		// 流量-地速閉環:施用量 = 流量 /(地速 × 幅寬);地速為 0 時無定義
		msg.application_rate_ml_m2 = (ground_speed > 0.1f && _boom_m.get() > 0.0f)
			? _rate_set.get() / (ground_speed * _boom_m.get())
			: NAN;
	} else {
		msg.flow_rate_ml_s = 0.0f;
		msg.pump_state = PUMP_OFF;
		msg.application_rate_ml_m2 = NAN;
	}

	msg.volume_remaining_ml = _volume_remaining;
	msg.volume_consumed_ml = _volume_consumed;

	uint16_t flags = 0;
	if (_volume_remaining <= _tank_ml.get() * 0.1f) { flags |= FLAG_TANK_LOW; }
	if (_volume_remaining <= 0.0f) { flags |= FLAG_TANK_EMPTY; }
	msg.spray_flags = flags;
	_spray_pub.publish(msg);

	// 斷藥返航:tank empty 且在飛(armed)→ 記斷點 + 發 RTL(一次)
	if ((flags & FLAG_TANK_EMPTY) && armed && !_rtl_sent) {
		_breakpoint_x = static_cast<double>(lpos.x);
		_breakpoint_y = static_cast<double>(lpos.y);
		send_rtl();
		_rtl_sent = true;
		PX4_INFO("tank empty at breakpoint (%.1f, %.1f), consumed %.0f ml → RTL",
			 _breakpoint_x, _breakpoint_y, static_cast<double>(_volume_consumed));
	}
}

void DroneSpray::send_rtl()
{
	vehicle_command_s vcmd{};
	vcmd.command = vehicle_command_s::VEHICLE_CMD_NAV_RETURN_TO_LAUNCH;
	vehicle_status_s status{};
	_status_sub.copy(&status);
	vcmd.source_system = status.system_id;
	vcmd.target_system = status.system_id;
	vcmd.source_component = status.component_id;
	vcmd.target_component = status.component_id;
	vcmd.timestamp = hrt_absolute_time();
	_vcmd_pub.publish(vcmd);
}

int DroneSpray::custom_command(int argc, char *argv[])
{
	// SITL 測試鉤:`drone_spray empty` 立即把藥箱清空(觸發 RTL)
	if (argc > 0 && strcmp(argv[0], "empty") == 0) {
		if (!is_running()) {
			PX4_WARN("not running");
			return 1;
		}
		// 透過參數把容量設 0 讓 Run() 下一輪判定 empty(避免直接動私有狀態)
		float zero = 0.0f;
		param_set(param_find("SPRAY_TANK_ML"), &zero);
		PX4_INFO("SPRAY_TANK_ML set 0 (will trigger tank empty)");
		return 0;
	}
	return print_usage("unknown command");
}

int DroneSpray::task_spawn(int argc, char *argv[])
{
	DroneSpray *instance = new DroneSpray();

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

int DroneSpray::print_usage(const char *reason)
{
	if (reason) {
		PX4_WARN("%s", reason);
	}

	PRINT_MODULE_DESCRIPTION(
		R"DESCR_STR(
### Description
Agricultural spray control skeleton (PB-1): flow/ground-speed closed loop,
breakpoint logging, tank discharge simulation; tank empty publishes
VEHICLE_CMD_NAV_RETURN_TO_LAUNCH via the standard vehicle_command interface
(does not touch the commander state machine). SITL logic verification only.
)DESCR_STR");

	PRINT_MODULE_USAGE_NAME("drone_spray", "modules");
	PRINT_MODULE_USAGE_COMMAND("start");
	PRINT_MODULE_USAGE_COMMAND_DESCR("empty", "Force tank empty (SITL test hook)");
	PRINT_MODULE_USAGE_DEFAULT_COMMANDS();
	return 0;
}

extern "C" __EXPORT int drone_spray_main(int argc, char *argv[])
{
	return DroneSpray::main(argc, argv);
}
