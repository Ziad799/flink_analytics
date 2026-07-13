# Flink Analytics for Odoo 19 — Installation

Your setup: Odoo 19 running in Docker container `odoo19` (per `docker ps`).

## 1. Install Python dependencies inside the container

```powershell
docker exec -u root odoo19 pip3 install --break-system-packages pandas numpy scikit-learn openpyxl
```

(If `--break-system-packages` is rejected on your image, run it without that flag.
scikit-learn is optional — without it you lose segmentation and multivariate
anomaly detection; everything else still works.)

## 2. Copy the module into the container

From this folder (`odoo-addon`):

```powershell
docker cp flink_analytics odoo19:/mnt/extra-addons/
docker restart odoo19
```

## 3. Install the app in Odoo

1. Open Odoo (http://localhost:8080) and log in as admin
2. Enable developer mode: Settings → scroll down → **Activate developer mode**
3. Apps → click **Update Apps List** (menu appears in developer mode) → Update
4. Search "**Flink Analytics**" → Install

## 4. Grant access

Settings → Users → pick a user → section **Flink Analytics** → set
**User** (own analyses) or **Manager** (all analyses).

## 5. (Optional) Enable AI briefings

Settings → **Flink Analytics** section → enable **AI briefings**, paste your
Anthropic API key. Privacy: only aggregate statistics are ever sent — never
raw records.

## Using it

Flink Analytics menu → Analyses → New:

- **Odoo models**: add one or more models (e.g. Sales Order, CRM Lead,
  Invoice lines), optionally pick specific fields, a domain filter and a
  record limit → **Run Full Analysis**. Each model gets its own tab in the
  dashboard. User access rights are enforced — users can only analyze
  records they can read.
- **Uploaded file**: switch source to "Uploaded file" and attach a
  CSV / Excel / JSON / Parquet file (e.g. `test_sales_data.xlsx`).

Then: **Open Dashboard** (interactive charts + on-demand forecasting),
**Generate AI Briefing**, or Print → **Analytics Report** (PDF).

## Updating the module after changes

```powershell
docker cp flink_analytics odoo19:/mnt/extra-addons/
docker exec odoo19 odoo -d YOUR_DB_NAME -u flink_analytics --stop-after-init
docker restart odoo19
```
