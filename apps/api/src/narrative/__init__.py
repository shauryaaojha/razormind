"""Turning verified numbers into strings, with no model anywhere in reach.

This package sits **below** ``llm`` in the layered contract, which is the whole
reason it is a package rather than a module inside it. The template renderer is
the fallback the system uses when the model is gone or ungrounded, and a
fallback that could itself call a model is not a fallback. Putting it here makes
that a build failure rather than a code-review note.

It holds three things:

* ``render`` -- how a paise, a ratio, a percentage point and a count are
  written, and which alternative spellings of each are accepted;
* ``models`` -- ``Claim`` and ``Explanation``, the shape both the model's answer
  and the template's answer take, so one grounding gate judges both;
* ``template`` -- the deterministic answer, assembled from evidence rows.
"""
