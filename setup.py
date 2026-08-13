from setuptools import setup, find_packages

setup(
    name="agent-swarm-framework",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pyyaml",
        "asyncio",
    ],
    entry_points={
        'console_scripts': [
            'swarm=swarm:main',
        ],
    },
)
