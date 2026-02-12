from setuptools import setup, find_packages

setup(
    name="jarvis-agent",
    version="0.1.0",
    description="Jarvis-like CLI+Voice agent with tools (macOS) and GPT-5 Codex backend",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "python-dotenv>=1.0.1",
        "pydantic>=2.7.0",
        "pydantic-settings>=2.3.0",
        "platformdirs>=4.2.0",
        "rich>=13.7.1",
        "openai>=1.40.0",
        "sounddevice>=0.4.7",
        "numpy>=1.26.4",
        "pvporcupine>=3.0.4",
        "pvrecorder>=1.2.2",
        "requests>=2.32.3",
    ],
    extras_require={
        "dev": [
            "pytest>=8.2.2",
            "ruff>=0.5.5",
            "mypy>=1.10.0",
        ],
        "browser": ["playwright>=1.46.0"],
        "rag": ["chromadb>=0.5.5"],
    },
    entry_points={
        "console_scripts": [
            "jarvis=jarvis.main:main",
        ]
    },
)