# Selective Intelligence v1.0.6 public plugin update

This directory contains the skills-only update package that stops website work from being silently rerouted into ChatGPT Sites.

- [Download the plugin ZIP](selective-intelligence-plugin-1.0.6.zip)
- Verify it with [SHA256SUMS](SHA256SUMS)

Version 1.0.6 keeps the user's existing repository, application, host, and normal preview path as the canonical owner of website work. ChatGPT Sites may be used only when the user explicitly requests Sites for that task. The same boundary is present in the discovery description, core runtime instructions, strict text guide, non-developer reference, and website regression cases.

The deterministic 49-file ZIP passes the repository's archive, manifest, prompt-budget, runtime-file, skill-interface, icon, and no-unrequested-Sites checks. Version 1.0.5 remains the verified public-directory version until OpenAI completes review and publication of this update.
