# Configuration

Main config file: `policy-profile.config.json`.

## Chart

```json
"chart": {
  "title": "Policy Rates: Selected Central Banks",
  "subtitle": "Monthly end-of-period rates, percent per year",
  "months": 48,
  "selected_theme": "editorial"
}
```

## Areas

Each area uses a BIS `REF_AREA` code and a short display label.

```json
"areas": [
  { "code": "AU", "label": "RBA" },
  { "code": "US", "label": "Fed" },
  { "code": "XM", "label": "ECB" },
  { "code": "GB", "label": "BoE" },
  { "code": "JP", "label": "BoJ" },
  { "code": "CN", "label": "China LPR" },
  { "code": "CA", "label": "BoC" }
]
```

China uses the BIS China 1-year loan prime rate series, so `China LPR` is the clearest default label.

## Themes

Themes are plain color dictionaries. Add a new theme under `themes`, then set `selected_theme` to that name.

```json
"selected_theme": "terminal"
```

Command-line override:

```sh
python3 scripts/policy_profile.py --theme terminal
```

## Attribution Footer

The SVG can include a small footer attribution:

```json
"credit": {
  "name": "Alex Dunstan",
  "profile": "github.com/Alex-Dunstan/policy-rate-profile",
  "url": "https://github.com/Alex-Dunstan/policy-rate-profile"
}
```

Forks can replace these values or remove the `credit` block.

## Data Source

The default source is BIS central bank policy rates bulk CSV:

```json
"url": "https://data.bis.org/static/bulk/WS_CBPOL_csv_col.zip"
```

The generator uses monthly rows by default.
