from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    flink_ai_enabled = fields.Boolean(
        string="Enable AI Executive Briefings",
        config_parameter="flink_analytics.ai_enabled",
        help="Only aggregate statistics are sent to the AI provider - never raw records.",
    )
    flink_ai_provider = fields.Selection(
        [
            ("anthropic", "Anthropic (Claude)"),
            ("openai",    "OpenAI (GPT)"),
            ("gemini",    "Google (Gemini)"),
            ("mistral",   "Mistral AI"),
        ],
        string="AI Provider",
        config_parameter="flink_analytics.ai_provider",
        default="anthropic",
    )
    # One key field per provider - stored separately so switching providers
    # doesn't wipe the other keys.
    flink_anthropic_api_key = fields.Char(
        string="Anthropic API Key",
        config_parameter="flink_analytics.anthropic_api_key",
    )
    flink_anthropic_model = fields.Char(
        string="Model",
        config_parameter="flink_analytics.anthropic_model",
        default="claude-sonnet-5",
    )
    flink_openai_api_key = fields.Char(
        string="OpenAI API Key",
        config_parameter="flink_analytics.openai_api_key",
    )
    flink_openai_model = fields.Char(
        string="Model",
        config_parameter="flink_analytics.openai_model",
        default="gpt-4o",
    )
    flink_gemini_api_key = fields.Char(
        string="Google API Key",
        config_parameter="flink_analytics.gemini_api_key",
    )
    flink_gemini_model = fields.Char(
        string="Model",
        config_parameter="flink_analytics.gemini_model",
        default="gemini-2.0-flash",
    )
    flink_mistral_api_key = fields.Char(
        string="Mistral API Key",
        config_parameter="flink_analytics.mistral_api_key",
    )
    flink_mistral_model = fields.Char(
        string="Model",
        config_parameter="flink_analytics.mistral_model",
        default="mistral-large-latest",
    )
