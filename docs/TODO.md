# TODO

Work agreed but not yet built. Anything here is a decision already taken; open questions
belong in `DESIGN.md`.

## Embedded assistant

- **The panel is not working on NASQuay's pages.** Earlier, questions got "I could not
  reach the assistant just then" while resonance logged the same question answered in
  41 s against 3.8 s before — the reply arrived after the panel had given up. Next step:
  read the `backend:` note the panel shows when it fails, then find the panel's own
  timeout and what made the answer slow (turns of history plus five tools on a small
  model).
- **Names read as the wider world.** Asked for the shares on a NAS named after an
  organisation, a small model explained the organisation and called no tool. Every
  assistant operation now carries the rule that names are this installation's labels,
  and the measurements operation says it lists shares. Untested: press READ SPEC in
  resonance after deploying, then ask again. If the model still calls nothing, it is
  too small for tool use.

## Next

`DESIGN.md`'s sections 7 (routines) to 10 — routines, the MCP endpoint, packaging, and
the website. AI providers, the first half of section 7, are built.
