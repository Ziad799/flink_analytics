{
    "name": "Flink Data Analytics - AI Business Intelligence",
    "version": "19.0.1.0.0",
    "category": "Productivity/Analytics",
    "summary": "One-click automated analytics on any Odoo model or uploaded file: "
               "profiling, trends, correlations, anomalies, segmentation, "
               "forecasting, AI executive briefings & PDF reports",
    "description": """
Flink Analytics for Odoo
========================
Select any Odoo model (or several at once), or upload a CSV/Excel/JSON/Parquet
file, and run a full automated analysis: data profiling with quality scoring,
correlations, time trends, category breakdowns, anomaly detection, customer
segmentation, Holt-Winters forecasting and plain-language key findings - plus
optional privacy-safe AI executive briefings (Claude, GPT, Gemini or Mistral)
and PDF export.
""",
    "author": "Elata79",
    "maintainer": "Elata79",
    "support": "ziadelata@gmail.com",
    "website": "https://github.com/Ziad799/flink_analytics",
    "license": "OPL-1",
    "price": 150,
    "currency": "USD",
    "depends": ["base", "web"],
    "external_dependencies": {"python": ["pandas", "numpy"]},
    "images": ["static/description/banner.png"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/flink_analysis_views.xml",
        "views/res_config_settings_views.xml",
        "report/analysis_report.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "flink_analytics/static/src/dashboard/dashboard.js",
            "flink_analytics/static/src/dashboard/dashboard.xml",
            "flink_analytics/static/src/dashboard/dashboard.scss",
            "flink_analytics/static/src/widgets/domain_button.js",
            "flink_analytics/static/src/widgets/domain_button.xml",
        ],
    },
    "application": True,
    "installable": True,
}
