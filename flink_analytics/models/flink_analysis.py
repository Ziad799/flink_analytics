import base64
import io
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

MAX_ROWS = 100_000
# Field types that are meaningful for analytics
ANALYZABLE_TTYPES = (
    "char", "text", "selection", "integer", "float", "monetary",
    "boolean", "date", "datetime", "many2one",
)
SKIP_FIELDS = {"id", "write_uid", "create_uid", "write_date", "__last_update"}
# Technical/noise fields excluded from auto-selection (still selectable manually)
SKIP_PREFIXES = (
    "message_", "activity_", "access_", "website_message_", "rating_",
    "sequence", "my_activity_", "has_message",
)


class FlinkAnalysis(models.Model):
    _name = "flink.analysis"
    _description = "Flink Analytics Analysis"
    _order = "id desc"

    name = fields.Char(required=True, default=lambda self: _("New Analysis"))
    source_type = fields.Selection(
        [("model", "Odoo models"), ("file", "Uploaded file")],
        string="Data source", default="model", required=True,
    )
    file_data = fields.Binary(string="Data file", attachment=True)
    file_name = fields.Char(string="File name")
    line_ids = fields.One2many(
        "flink.analysis.model.line", "analysis_id", string="Models to analyze",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Analyzed"), ("error", "Error")],
        default="draft", copy=False,
    )
    result_json = fields.Text(copy=False)
    error_message = fields.Text(copy=False)
    ai_narrative = fields.Text(string="AI Executive Briefing", copy=False)
    analyzed_on = fields.Datetime(copy=False)
    user_id = fields.Many2one(
        "res.users", string="Owner", default=lambda self: self.env.user, index=True,
    )
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )
    findings_preview = fields.Html(compute="_compute_findings_preview", sanitize=True)

    # ------------------------------------------------------------------
    # Data acquisition
    # ------------------------------------------------------------------
    def _get_dataframes(self):
        """Return {label: pandas.DataFrame} for this analysis."""
        import pandas as pd

        self.ensure_one()
        dfs = {}
        if self.source_type == "file":
            if not self.file_data:
                raise UserError(_("Upload a data file first."))
            raw = base64.b64decode(self.file_data)
            name = (self.file_name or "").lower()
            buf = io.BytesIO(raw)
            try:
                if name.endswith((".xlsx", ".xls", ".xlsm")):
                    df = pd.read_excel(buf)
                elif name.endswith(".json"):
                    df = pd.read_json(buf)
                elif name.endswith(".parquet"):
                    df = pd.read_parquet(buf)
                else:  # csv / tsv / txt
                    df = pd.read_csv(
                        buf, sep=None, engine="python", encoding_errors="replace"
                    )
            except Exception as exc:
                raise UserError(_("Could not parse the file: %s") % exc)
            dfs[self.file_name or _("Uploaded file")] = df
        else:
            if not self.line_ids:
                raise UserError(_("Add at least one Odoo model to analyze."))
            for line in self.line_ids:
                dfs[line._label()] = line._fetch_dataframe()
        return dfs

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_run_analysis(self):
        from ..analytics.engine import run_full_analysis

        for rec in self:
            try:
                dfs = rec._get_dataframes()
                results = {}
                for label, df in dfs.items():
                    if df.empty:
                        raise UserError(_("Dataset '%s' returned no rows.") % label)
                    results[label] = run_full_analysis(df)
                rec.write({
                    "result_json": json.dumps(results, default=str),
                    "state": "done",
                    "analyzed_on": fields.Datetime.now(),
                    "error_message": False,
                })
            except UserError:
                raise
            except Exception as exc:
                _logger.exception("Flink analysis %s failed", rec.id)
                rec.write({"state": "error", "error_message": str(exc)})
        return True

    def action_open_dashboard(self):
        self.ensure_one()
        if self.state != "done":
            raise UserError(_("Run the analysis first."))
        return {
            "type": "ir.actions.client",
            "tag": "flink_analytics.dashboard",
            "name": self.name,
            "params": {"analysis_id": self.id},
        }

    def action_generate_ai(self):
        self.ensure_one()
        icp = self.env["ir.config_parameter"].sudo()
        if str(icp.get_param("flink_analytics.ai_enabled")).lower() not in ("true", "1"):
            raise UserError(_(
                "AI briefings are disabled. Enable them in Settings -> Flink Analytics. "
                "Only aggregate statistics are ever sent to the AI provider."
            ))
        if not self.result_json:
            raise UserError(_("Run the analysis first."))

        from ..analytics.ai import PROVIDER_DEFAULTS, generate_briefing

        provider = icp.get_param("flink_analytics.ai_provider") or "anthropic"
        key_param = f"flink_analytics.{provider}_api_key"
        model_param = f"flink_analytics.{provider}_model"
        api_key = icp.get_param(key_param)
        if not api_key:
            provider_labels = {
                "anthropic": "Anthropic", "openai": "OpenAI",
                "gemini": "Google Gemini", "mistral": "Mistral AI",
            }
            raise UserError(_(
                "No API key configured for %s. Go to Settings -> Flink Analytics."
            ) % provider_labels.get(provider, provider))
        ai_model = icp.get_param(model_param) or PROVIDER_DEFAULTS.get(provider, "")
        try:
            self.ai_narrative = generate_briefing(
                json.loads(self.result_json), self.name, api_key, ai_model, provider,
            )
        except Exception as exc:
            raise UserError(_("AI provider error: %s") % exc)
        return True

    # ------------------------------------------------------------------
    # Dashboard / report data
    # ------------------------------------------------------------------
    def get_dashboard_data(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "analyzed_on": self.analyzed_on and self.analyzed_on.isoformat() or False,
            "results": json.loads(self.result_json) if self.result_json else {},
            "ai_narrative": self.ai_narrative or False,
        }

    def run_forecast(self, dataset_key, date_col, value_col, periods=12):
        self.ensure_one()
        from ..analytics.forecasting import forecast_series

        dfs = self._get_dataframes()
        if dataset_key not in dfs:
            raise UserError(_("Unknown dataset '%s'.") % dataset_key)
        try:
            return forecast_series(
                dfs[dataset_key], date_col, value_col, periods=int(periods) or 12
            )
        except ValueError as exc:
            raise UserError(str(exc))

    def get_report_data(self):
        self.ensure_one()
        return json.loads(self.result_json) if self.result_json else {}

    @api.depends("result_json")
    def _compute_findings_preview(self):
        for rec in self:
            if not rec.result_json:
                rec.findings_preview = False
                continue
            try:
                results = json.loads(rec.result_json)
            except Exception:
                rec.findings_preview = False
                continue
            parts = []
            for label, analysis in results.items():
                items = "".join(
                    "<li>%s</li>" % f for f in analysis.get("key_findings", [])
                )
                parts.append("<h5>%s</h5><ul>%s</ul>" % (label, items))
            rec.findings_preview = "".join(parts)


class FlinkAnalysisModelLine(models.Model):
    _name = "flink.analysis.model.line"
    _description = "Model selected for analysis"

    analysis_id = fields.Many2one(
        "flink.analysis", required=True, ondelete="cascade",
    )
    model_id = fields.Many2one(
        "ir.model", string="Model", required=True, ondelete="cascade",
        domain=[("transient", "=", False)],
    )
    model_name = fields.Char(related="model_id.model", string="Technical name", store=True)
    field_ids = fields.Many2many(
        "ir.model.fields", string="Fields",
        domain="[('model_id', '=', model_id), ('store', '=', True),"
               " ('ttype', 'in', %s)]" % list(ANALYZABLE_TTYPES),
        help="Leave empty to auto-select all analyzable fields.",
    )
    domain = fields.Char(
        string="Filter (domain)", default="[]",
        help="Odoo domain to filter records, e.g. [('state', '=', 'sale')]",
    )
    limit = fields.Integer(default=50000, help="Maximum records to read.")

    @api.onchange("model_id")
    def _onchange_model_id(self):
        self.field_ids = [(5, 0, 0)]

    def _label(self):
        self.ensure_one()
        return "%s (%s)" % (self.model_id.name, self.model_id.model)

    def _auto_field_names(self, Model):
        fnames = []
        for name, meta in Model.fields_get().items():
            if name in SKIP_FIELDS or name.startswith(SKIP_PREFIXES):
                continue
            if not meta.get("store"):
                continue
            if meta.get("type") not in ANALYZABLE_TTYPES:
                continue
            fnames.append(name)
            if len(fnames) >= 40:
                break
        return fnames

    def _fetch_dataframe(self):
        import pandas as pd

        self.ensure_one()
        model_name = self.model_id.model
        if model_name not in self.env:
            raise UserError(_("Model '%s' is not available.") % model_name)
        Model = self.env[model_name]
        fnames = self.field_ids.mapped("name") or self._auto_field_names(Model)
        if not fnames:
            raise UserError(_("No analyzable fields found on '%s'.") % model_name)
        try:
            dom = safe_eval(self.domain or "[]")
        except Exception as exc:
            raise UserError(_("Invalid domain on '%s': %s") % (model_name, exc))
        limit = min(self.limit or 50000, MAX_ROWS)
        # search_read enforces the current user's access rights and record rules
        rows = Model.search_read(dom, fnames, limit=limit)
        for row in rows:
            row.pop("id", None)
            for key, val in row.items():
                if isinstance(val, (list, tuple)) and len(val) == 2:
                    row[key] = val[1]  # many2one -> display name
                elif val is False:
                    row[key] = None
        return pd.DataFrame(rows)
