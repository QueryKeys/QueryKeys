"""Package setup for QueryKeys bot."""
from setuptools import setup, find_packages

setup(
    name="querykeys",
    version="1.0.0",
    description="Elite Polymarket Prediction & Automated Trading Bot",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.11",
    install_requires=[
        "py-clob-client>=0.17.0",
        "aiohttp>=3.9.0",
        "websockets>=12.0",
        "sqlalchemy>=2.0.27",
        "aiosqlite>=0.19.0",
        "pydantic>=2.6.0",
        "python-dotenv>=1.0.1",
        "pyyaml>=6.0.1",
        "structlog>=24.1.0",
        "lightgbm>=4.3.0",
        "xgboost>=2.0.3",
        "catboost>=1.2.3",
        "scikit-learn>=1.4.0",
        "numpy>=1.26.4",
        "pandas>=2.2.0",
        "scipy>=1.12.0",
        "anthropic>=0.25.0",
        "vaderSentiment>=3.3.2",
        "streamlit>=1.32.0",
        "plotly>=5.20.0",
    ],
    entry_points={
        "console_scripts": [
            "querykeys=scripts.run_bot:main",
            "querykeys-dashboard=scripts.run_dashboard:main",
            "querykeys-backtest=scripts.run_backtest:run_backtest",
        ]
    },
)
