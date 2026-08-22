# Selective Intelligence v1.0.4 public plugin package

This directory publishes the corrected skills-only submission package for Selective Intelligence v1.0.4.

- [Download the plugin ZIP](selective-intelligence-plugin-1.0.4.zip)
- Verify it with [SHA256SUMS](SHA256SUMS)

This release fixes the two OpenAI uploader failures reported for v1.0.3. Both declared SVG icons now use numeric 256x256 dimensions in their `viewBox`, `width`, and `height`. Every packaged `SKILL.md` frontmatter contains only `name` and `description`, while supported skill interface settings live in `agents/openai.yaml`.

The package is deterministic and passes the repository's exact-package checks for OpenAI's published ZIP, skill, agent metadata, and branding-image rules. It has not yet been reuploaded to, approved by, or published in the OpenAI Plugins Directory.
