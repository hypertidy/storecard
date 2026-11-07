# AGENTS.md

Start with `BRIEF.md`: purpose, decisions, open questions and next steps.
Update it in the same change when a decision is made or a step is done.

Working rules:

- Cards are facts read from metadata. Never fetch data chunks to build a card;
  coordinate arrays are the only data a card may sample.
- Never edit someone else's store. Fixes are assertions: separate documents
  keyed to the store's URL and version, with evidence.
- Grid inference belongs to gproj (to become regula). Do not reimplement it
  here; pass it the card's coordinate sample.
- The rasterwise problem-file archive lives in rgdal-dev/rasterwise. Read it;
  do not copy its files into this repo.
- `portolan/` is self-contained: run its commands from that directory. Its
  fixtures double as this project's test suite.
- Files that may be copied into software builds stay ASCII.
- Public text names repos and issues, not people.

Reviews:

- Review rounds between sessions are expected, and they converge. Each round
  should bring something the other side could not have: a run against a real
  store, a new fixture, a different environment, or a source text (such as a
  chapter of regular-in-what). A round that brings only opinion is a sign to
  stop.
- Post reviews on the PR, not only in chat, so the next session finds them.
- When a round produces only naming or style comments, it has converged.
