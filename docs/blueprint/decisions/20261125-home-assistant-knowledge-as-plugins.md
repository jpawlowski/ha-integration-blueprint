---
id: 20261125-home-assistant-knowledge-as-plugins
status: accepted
---

# Ship the Home Assistant Knowledge as Plugins, and Vendor Their Rules as Path-Scoped Files

## Context

After the workflow skills moved out ([20261123-optional-skills-as-plugins](20261123-optional-skills-as-plugins.md)),
the `ha-*` skills still mixed two things: Home Assistant knowledge that holds in any custom integration, and this
template's layout, scripts and policy. Downstream repositories could not turn the knowledge off or replace it, and
nobody outside the blueprint could use it. A plugin cannot ship the path-scoped rules that Copilot, VS Code and Claude
Code load when a file of one kind is opened.

## Decision

The Home Assistant knowledge lives in `ha-custom-integration-skills` as generic skills grouped into plugins a developer
turns off together: `haci-quality` (tests, current APIs, breaking changes and repairs, the Quality Scale audit),
`haci-build` (entities, service actions, config flow and manifest, translations, user experience, coordinator and
diagnostics) and `haci-publish` (HACS and the Marketplace). Each skill defers to the project and keeps the rules it has in
`references/rules.md` or `rules.<topic>.md`. `script/haci-vendor` copies those files at the pinned tag into
`.agents/instructions/haci.<topic>.instructions.md` with this repository's path patterns and a marker carrying the tag
and a digest, which `script/skills-check` verifies offline. Each `blueprint.*` instructions file beside one keeps only
what this repository adds. What is about this repository alone stays as `blueprint-*` skills: `blueprint-dev-instance`
for the development instance, `blueprint-release` for release-please, the ZIP asset and the catalog gates. OpenCode
loads the same plugins from per-plugin `index.json` catalogs at the pinned tag, listed in `opencode.json`.

## Considered options

**Keep the rules only inside the skills.** An agent that edits a file without loading the skill would never see them;
the path-scoped load is what reaches it.

**Let each project write its own path-scoped copy by hand.** Copies drift from the tag they claim to follow, and
nothing would notice. The digest in the marker makes a hand edit fail the gates.

**Copy the skills into `.opencode/skills/`.** A second copy to keep in step, in a directory agents may not edit.

## Consequences

- A rules change reaches a project only through a new tag, a pin bump in the four agent settings files and a
  `script/haci-vendor` run; Renovate's pull request says to run it.
- `initialize.sh` must leave every vendored file alone, since renaming the repository in the marker breaks its digest;
  a test holds every topic to that.
- OpenCode needs the network when it starts: it drops a catalog whose `index.json` cannot be fetched.
- Integration repositories delete the old `ha-*` directories by hand, because template sync does not delete; the
  manual steps say so.
