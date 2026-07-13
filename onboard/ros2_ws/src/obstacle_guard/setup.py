from setuptools import setup

package_name = "obstacle_guard"

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
    description="避障保守限速 node(P1):感知距離→已測 P0 安全邏輯→速度上限",
    license="Proprietary",
    entry_points={
        "console_scripts": [
            "obstacle_guard = obstacle_guard.node:main",
        ],
    },
)
