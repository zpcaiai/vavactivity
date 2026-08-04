# Submission and review workflow

Submission freezes an immutable version and opens a review case. Reviewers judge what the
member wrote and never rewrite it. Every decision separates the member-visible message from the
encrypted internal note; rejection and suspension always require a reason. Field- and photo-level
decisions are recorded individually, and a blocking item prevents approval. Optimistic locking
stops two reviewers from silently overwriting each other. Approval switches the displayed version
atomically.
