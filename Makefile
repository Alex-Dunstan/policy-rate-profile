.PHONY: generate offline preview themes check

generate:
	python3 scripts/policy_profile.py

offline:
	python3 scripts/policy_profile.py --offline

preview:
	python3 scripts/policy_profile.py --offline
	@printf "Open preview/policy-rates.html\n"

themes:
	python3 scripts/policy_profile.py --list-themes

check:
	python3 -B scripts/policy_profile.py --offline
	python3 -c "import pathlib, xml.etree.ElementTree as ET; paths=list(pathlib.Path('preview').glob('policy-rates-*.svg'))+[pathlib.Path('assets/policy-rates.svg')]; [ET.parse(p) for p in paths]; print('parsed', len(paths), 'svg files')"
