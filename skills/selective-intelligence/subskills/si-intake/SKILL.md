---
name: si-intake
description: Start a run in simple words, capture the real outcome, and send a clean packet to the planner.
license: CC0-1.0
metadata:
  version: "0.1.0"
  parent: selective-intelligence
  audience: "plain-language"
---

# SI Sub-Skill: Intake

## What this skill does (plain language)
It inspects what the person has already said or connected, reconstructs the active goal, and turns it into a short packet for the next agent.

## Inputs
- A user message that starts a project
- Optional seed: idea, URL, repo note, image, or short brief

## How it works
1. Read the seed and infer the biggest real goal.
2. If the goal is not in the current message, inspect the available conversation, project/workspace, repository, connected sources, and tools before asking anything.
3. If discovery finds no goal or project at all, return the bounded active-but-empty status from the parent skill. Do not ask a generic outcome question.
4. Save any plain, reversible assumption used to continue.
5. Return a one-screen Intake Packet:
   - Project name (or temporary name if not given)
   - Seed summary
   - What is definitely true vs what is still guessed
   - One next step for the planner

## Output
Return:
- `outcome` (plain sentence)
- `assumptions` (very short list)
- `constraints` (hard limits like safety, money, permissions)
- `next_skill`: `si-planner`
- `next_step_id`

## Non-negotiable rules
- Ask only when a material product, safety, money, or permission decision cannot be recovered from evidence.
- Never ask for keys, tokens, CLI commands, or auth setup in this phase.
- Keep language simple and easy for non-developers.
