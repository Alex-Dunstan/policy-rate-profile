# GitHub Profile Embed

Use this repo as the source of the generated SVG, then embed the SVG in a profile README or another project README.

## Same Repo

If the SVG is inside the same repository as the README:

```md
<p align="center">
  <img src="./assets/policy-rates.svg" alt="Selected central bank policy rates" width="940">
</p>
```

## Separate Repo

If this repo is public on GitHub, use the raw SVG URL:

```md
<p align="center">
  <a href="https://github.com/OWNER/policy-rate-profile">
    <img src="https://raw.githubusercontent.com/OWNER/policy-rate-profile/main/assets/policy-rates.svg" alt="Selected central bank policy rates" width="940">
  </a>
</p>
```

Replace `OWNER` with the GitHub account or organization that owns the repo.

## Update Flow

1. Keep `.github/workflows/update-policy-profile.yml` enabled.
2. Edit `policy-profile.config.json` for countries, title, window, and theme.
3. Run the workflow manually once from GitHub Actions.
4. Use the raw SVG URL in any README.

## Local Preview

```sh
make preview
open preview/policy-rates.html
```
