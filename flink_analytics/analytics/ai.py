"""Multi-provider AI narrative layer for Flink Analytics.

Supported providers:
  - anthropic  -> Claude (claude-sonnet-5, claude-opus-4-8, ...)
  - openai     -> GPT  (gpt-4o, gpt-4-turbo, gpt-3.5-turbo, ...)
  - gemini     -> Google Gemini (gemini-2.0-flash, gemini-1.5-pro, ...)
  - mistral    -> Mistral AI (mistral-large-latest, mistral-small-latest, ...)

Privacy guarantees:
  Only aggregate statistics are sent - never raw rows or cell values.
"""
import json
import requests

# -- Default models per provider -----------------------------------------------
PROVIDER_DEFAULTS = {
    "anthropic": "claude-sonnet-5",
    "openai":    "gpt-4o",
    "gemini":    "gemini-2.0-flash",
    "mistral":   "mistral-large-latest",
}

PROVIDER_LABELS = {
    "anthropic": "Anthropic (Claude)",
    "openai":    "OpenAI (GPT)",
    "gemini":    "Google (Gemini)",
    "mistral":   "Mistral AI",
}


def _aggregate_only_summary(analysis: dict) -> dict:
    """Strip anything row-level; keep only aggregates."""
    profile = analysis.get("profile", {})
    cols = {}
    for name, meta in profile.get("columns", {}).items():
        cols[name] = {
            k: v for k, v in meta.items()
            if k in ("semantic_type", "null_pct", "unique", "min", "max",
                     "mean", "median", "std", "skew")
        }
    return {
        "shape": {"rows": profile.get("rows"), "cols": profile.get("cols")},
        "quality_score": profile.get("quality_score"),
        "warnings": profile.get("warnings", []),
        "columns": cols,
        "correlations": analysis.get("correlations", {}).get("pairs", [])[:10],
        "trends": [
            {k: t[k] for k in ("date_column", "value_column",
                                "trend_pct_per_period", "direction")}
            for t in analysis.get("time_trends", [])
        ],
        "anomalies": analysis.get("anomalies", {}).get("by_column", []),
        "segments": analysis.get("segments"),
        "statistical_findings": analysis.get("key_findings", []),
    }


def _build_prompt(analysis_name: str, summaries: dict) -> str:
    return (
        "You are a senior business/data analyst. Below are AGGREGATE statistics "
        f"from an analysis named '{analysis_name}' covering {len(summaries)} dataset(s) "
        "(no raw records are included). Write an executive briefing with: "
        "1) a 3-sentence overview, 2) the 5 most decision-relevant insights, "
        "3) risks/data-quality caveats, 4) 3 concrete recommended actions, "
        "5) suggested next analyses. If several datasets are present, call out "
        "cross-dataset observations. Be specific, quantitative, and avoid "
        "restating raw stats without interpretation.\n\n"
        f"STATISTICS:\n{json.dumps(summaries, default=str)[:24000]}"
    )


# -- Provider implementations --------------------------------------------------

def _call_anthropic(prompt: str, api_key: str, model: str) -> str:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []))


def _call_openai(prompt: str, api_key: str, model: str) -> str:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, api_key: str, model: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models"
        f"/{model}:generateContent?key={api_key}"
    )
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_mistral(prompt: str, api_key: str, model: str) -> str:
    resp = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


_CALLERS = {
    "anthropic": _call_anthropic,
    "openai":    _call_openai,
    "gemini":    _call_gemini,
    "mistral":   _call_mistral,
}


# -- Public API ----------------------------------------------------------------

def generate_briefing(
    results: dict,
    analysis_name: str,
    api_key: str,
    model: str,
    provider: str = "anthropic",
) -> str:
    summaries = {label: _aggregate_only_summary(a) for label, a in results.items()}
    prompt = _build_prompt(analysis_name, summaries)
    caller = _CALLERS.get(provider)
    if not caller:
        raise ValueError(f"Unknown AI provider: {provider!r}")
    return caller(prompt, api_key, model)
