# Session Lifecycle

The Owner is created once per work package and its opaque session reference is stored only in ignored runtime state. Preview does not create a session. Explicit resume uses that recorded reference and returns natural-language review findings to the same Owner. The transport runner does not interpret the prose.

Every reviewer and the Final Verifier starts fresh, read-only, and is never resumed for repair work. If the original Owner cannot be resumed, the Leader records the reason, stops, and obtains explicit human approval before assigning a documented replacement Owner and starting a new accountable session.
