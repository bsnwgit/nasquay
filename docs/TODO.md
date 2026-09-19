# TODO

Work agreed but not yet built. Anything here is a decision already taken; open questions
belong in `DESIGN.md`.

## The worker

- **Build `nasquay-worker`.** The design has a second process alongside the web service for
  jobs, routines and monitoring collection (`DESIGN.md`, "Processes"), and one of the
  monitoring rules — `collection_stale` — watches it. Collection itself is built and running,
  but inside the web service rather than in a worker of its own: `install.sh` writes the web
  unit only, and `deploy/` holds only `nasquay-web.service`. Moving it means changing where
  `scheduler.start()` is called from, not what it does. Jobs and routines will want the
  separate process for real, since neither should share a lifetime with the web service.

## Home page

- **A link to each NAS's own interface.** Record a URL, or an address and port, against each
  NAS and show it on the home page as a link that opens in a new tab. NASQuay already holds
  the address it talks MCP to, but that is the MCP port and not the administration interface,
  so the link is its own field rather than something to derive — a NAS may be behind a proxy,
  on a different port, or reached by a name NASQuay never uses.
  It is presentation only: following the link leaves NASQuay, and nothing about the target is
  checked, fetched or proxied.

## NAS settings

- **Choose which shares are shown.** Per NAS, an admin picks which shared folders appear in
  the app and which are hidden. Hidden shares are left out of the Shares page and of the
  Files page's top level, so a NAS with system or private shares is not cluttered by them.
  Hiding is presentation, not permission: it does not grant access to anything, and a role
  that may not read a share still cannot, shown or not.

- **Choose which directories show under Files.** The same idea one level down: an admin
  picks which folders the Files page lists, so the housekeeping directories a QNAP keeps in
  every share (`@Recycle`, `.@__thumb`, `@Recently-Snapshot` and the like) can be kept out
  of the way, and a folder can be hidden anywhere in the tree rather than only at a share's
  root. Presentation only, on the same terms as hiding a share.
