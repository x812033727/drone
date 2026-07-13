from setuptools import setup

package_name = "precision_land"

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
    description="視覺標靶精準降落 node(P1):標靶偏移→已測 P0 降落狀態機→速度/下降指令",
    license="Proprietary",
    entry_points={
        "console_scripts": [
            "precision_land = precision_land.node:main",
        ],
    },
)
