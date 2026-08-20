from setuptools import setup, find_packages

setup(
    name="agent-swarm-framework",
    version="0.1.0",
    packages=find_packages(),
    py_modules=["swarm"],
    python_requires=">=3.10",
    install_requires=[
        "pydantic>=2.5",
        "pyyaml>=6",
    ],
    entry_points={
        'console_scripts': [
            'swarm=swarm:main',
        ],
    },
)
