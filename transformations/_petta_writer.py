"""PeTTa writer transformation.

Deliberately a no-op scaffold: journal writes are performed ONLY via the
`petta_append` tool (explicit model action), never implicitly from a
transformation hook. This keeps the journal append-only and free of
accidental auto-writes on every context build.
"""

def transform(messages, tools):
    return messages, tools
