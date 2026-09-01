"""The execution-plan vocabulary.

A package of its own, for the same reason ``evidence`` is one: it is a shared
vocabulary rather than a component. The orchestrator *builds* a plan and runs
it, the validator *judges* one, and neither may import the other -- so the type
they both speak has to sit below both (D-44).
"""
