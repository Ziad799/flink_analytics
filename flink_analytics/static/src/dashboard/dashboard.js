/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { Component, onMounted, onPatched, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";

const PALETTE = ["#1f4e79", "#2e86c1", "#76b7f0", "#f39c12", "#27ae60", "#c0392b", "#8e44ad", "#16a085"];

export class FlinkDashboard extends Component {
    static template = "flink_analytics.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.rootRef = useRef("root");
        this.analysisId =
            this.props.action?.params?.analysis_id ||
            this.props.action?.context?.active_id;
        this.state = useState({
            loading: true,
            error: null,
            data: null,
            activeTab: null,
            forecast: null,
            forecastLoading: false,
            fc: { date_col: "", value_col: "", periods: 12 },
        });
        this.charts = [];
        onWillStart(async () => {
            try {
                await loadBundle("web.chartjs_lib");
            } catch (e) {
                // charts degrade to tables if the bundle is unavailable
            }
            try {
                const data = await this.orm.call("flink.analysis", "get_dashboard_data", [
                    this.analysisId,
                ]);
                this.state.data = data;
                const keys = Object.keys(data.results || {});
                this.state.activeTab = keys[0] || null;
                this._initForecastDefaults();
            } catch (e) {
                this.state.error = e.data?.message || String(e);
            }
            this.state.loading = false;
        });
        onMounted(() => this.renderCharts());
        onPatched(() => this.renderCharts());
        onWillUnmount(() => this._destroyCharts());
    }

    get result() {
        return this.state.data?.results?.[this.state.activeTab] || null;
    }

    get datasetKeys() {
        return Object.keys(this.state.data?.results || {});
    }

    get dateColumns() {
        const cols = this.result?.profile?.columns || {};
        return Object.keys(cols).filter((c) => cols[c].semantic_type === "datetime");
    }

    get numericColumns() {
        const cols = this.result?.profile?.columns || {};
        return Object.keys(cols).filter((c) => cols[c].semantic_type === "numeric");
    }

    get hasCharts() {
        return !!window.Chart;
    }

    _initForecastDefaults() {
        const fcast = this.result?.forecastable || [];
        if (fcast.length) {
            this.state.fc.date_col = fcast[0].date_column;
            this.state.fc.value_col = fcast[0].value_column;
        } else {
            this.state.fc.date_col = this.dateColumns[0] || "";
            this.state.fc.value_col = this.numericColumns[0] || "";
        }
    }

    selectTab(key) {
        if (key === this.state.activeTab) return;
        this.state.activeTab = key;
        this.state.forecast = null;
        this._initForecastDefaults();
    }

    async runForecast() {
        const { date_col, value_col, periods } = this.state.fc;
        if (!date_col || !value_col) {
            this.notification.add("Pick a date column and a value column.", { type: "warning" });
            return;
        }
        this.state.forecastLoading = true;
        try {
            this.state.forecast = await this.orm.call("flink.analysis", "run_forecast", [
                this.analysisId,
                this.state.activeTab,
                date_col,
                value_col,
                parseInt(periods) || 12,
            ]);
        } catch (e) {
            this.notification.add(e.data?.message || String(e), { type: "danger" });
        }
        this.state.forecastLoading = false;
    }

    qualityClass(score) {
        if (score >= 85) return "text-success";
        if (score >= 60) return "text-warning";
        return "text-danger";
    }

    fmt(v) {
        if (v === null || v === undefined) return "-";
        if (typeof v === "number") {
            return Math.abs(v) >= 1000
                ? v.toLocaleString(undefined, { maximumFractionDigits: 0 })
                : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
        }
        return String(v);
    }

    // ------------------------------------------------------------------
    // Charts
    // ------------------------------------------------------------------
    _destroyCharts() {
        this.charts.forEach((c) => c.destroy());
        this.charts = [];
    }

    _sizeCanvas(el) {
        const box = el.parentElement;
        if (box) {
            el.width = box.clientWidth || 600;
            el.height = box.clientHeight || 200;
        }
    }

    renderCharts() {
        if (!window.Chart || !this.rootRef.el) return;
        this._destroyCharts();
        const r = this.result;
        if (!r) return;

        (r.time_trends || []).forEach((t, i) => {
            const el = this.rootRef.el.querySelector(`#flink-trend-${i}`);
            if (!el) return;
            this._sizeCanvas(el);
            this.charts.push(new Chart(el, {
                type: "line",
                data: {
                    labels: t.dates.map((d) => d.slice(0, 10)),
                    datasets: [{
                        label: t.value_column,
                        data: t.values,
                        borderColor: PALETTE[i % PALETTE.length],
                        backgroundColor: PALETTE[i % PALETTE.length] + "22",
                        fill: true,
                        tension: 0.25,
                        pointRadius: 2,
                    }],
                },
                options: { responsive: true, animation: false, maintainAspectRatio: false, plugins: { legend: { display: false } } },
            }));
        });

        (r.categorical_breakdowns || []).forEach((c, i) => {
            const el = this.rootRef.el.querySelector(`#flink-cat-${i}`);
            if (!el) return;
            this._sizeCanvas(el);
            const useValues = c.value_sums && c.value_sums.some((v) => v !== null);
            this.charts.push(new Chart(el, {
                type: "bar",
                data: {
                    labels: c.categories,
                    datasets: [{
                        label: useValues ? `Sum of ${c.value_column}` : "Count",
                        data: useValues ? c.value_sums : c.counts,
                        backgroundColor: PALETTE[(i + 2) % PALETTE.length],
                    }],
                },
                options: { responsive: true, animation: false, maintainAspectRatio: false, plugins: { legend: { display: false } }, indexAxis: "y" },
            }));
        });

        const f = this.state.forecast;
        const fel = this.rootRef.el.querySelector("#flink-forecast-chart");
        if (f && fel) {
            this._sizeCanvas(fel);
            const labels = [...f.history.dates, ...f.forecast.dates].map((d) => d.slice(0, 10));
            const histLen = f.history.values.length;
            const pad = (arr, before) =>
                before ? Array(histLen - 1).fill(null).concat([f.history.values[histLen - 1]], arr) : arr;
            this.charts.push(new Chart(fel, {
                type: "line",
                data: {
                    labels,
                    datasets: [
                        {
                            label: "History",
                            data: [...f.history.values, ...Array(f.forecast.values.length).fill(null)],
                            borderColor: "#1f4e79",
                            pointRadius: 2,
                            tension: 0.2,
                        },
                        {
                            label: "Forecast",
                            data: pad(f.forecast.values, true),
                            borderColor: "#f39c12",
                            borderDash: [6, 4],
                            pointRadius: 2,
                            tension: 0.2,
                        },
                        {
                            label: "Upper",
                            data: pad(f.forecast.upper, true),
                            borderColor: "rgba(243,156,18,0.25)",
                            pointRadius: 0,
                            fill: "+1",
                            backgroundColor: "rgba(243,156,18,0.12)",
                        },
                        {
                            label: "Lower",
                            data: pad(f.forecast.lower, true),
                            borderColor: "rgba(243,156,18,0.25)",
                            pointRadius: 0,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    animation: false,
                    maintainAspectRatio: false,
                    plugins: { legend: { labels: { filter: (i) => !["Upper", "Lower"].includes(i.text) } } },
                },
            }));
        }
    }
}

registry.category("actions").add("flink_analytics.dashboard", FlinkDashboard);
