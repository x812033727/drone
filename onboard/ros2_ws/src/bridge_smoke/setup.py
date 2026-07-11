from setuptools import setup

package_name = "bridge_smoke"

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
    description="PX4 uXRCE-DDS bridge 最小煙霧驗證(Phase 0 第二批 S8)",
    license="Proprietary",
    entry_points={
        "console_scripts": [
            "listener = bridge_smoke.listener:main",
        ],
    },
)
