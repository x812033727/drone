from setuptools import setup

package_name = "px4_mqtt_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="drone onboard",
    maintainer_email="x812033727@gmail.com",
    description="DDS→MQTT 高頻感測器橋(Phase 0 S22)",
    license="Proprietary",
    entry_points={
        "console_scripts": [
            "bridge = px4_mqtt_bridge.bridge:main",
        ],
    },
)
