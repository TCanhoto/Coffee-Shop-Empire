# Player Authorization Boundary Review

**Review date:** 23 November 2026  
**Scope:** Current V2 Streamlit interface and SQLite storage. All checks used temporary test databases; no production save was opened or changed.

## Conclusion

The review did not identify a demonstrated way for a player using the current public Streamlit interface to select another player's ID or make the interface act on another player's account. After resume/join, the interface stores the authenticated player's session ID, player ID, and recovery credential in that browser connection's server-side `st.session_state`. UI handlers pass those server-held IDs to storage. There is no public HTTP/API operation that accepts a caller-supplied player ID.

Storage functions are internal Python operations, not independently authenticated API endpoints. A Python caller that already knows a player's exact session ID and player ID can use those values to read or mutate that player, because the functions validate that the pair exists but do not verify the recovery credential again. This is a defense-in-depth limitation for future server routes, plugins, or untrusted in-process callers. It is not, by itself, an externally reachable vulnerability in the current Streamlit app. Any future external endpoint must authenticate the caller and derive the player identity from the authenticated server-side principal instead of accepting IDs as authority.

## Operation and identity review

| Operation | Storage boundary | Current UI identity source |
|---|---|---|
| Purchase, price update, menu save, lease selection, trade, and event-popup acknowledgement | Scoped by both session ID and player ID; active/day/location and business rules are checked as applicable | `st.session_state["v2_player"]` or `st.session_state["solo_player"]`, populated only after join/create/resume succeeds |
| Read progress, history, final report, pending event | Queries are scoped by session ID and player ID; final report also checks completion | Same authenticated player state; UI does not accept an arbitrary player ID field |
| Host start | Requires a valid host credential checked by storage using constant-time hash comparison | Credential created or authenticated on the server and kept in server-side session state |
| Host resume | Requires game code and host credential | Password-type input; successful authentication populates server-side host state |
| Player resume | Requires game code, nickname, mode, and recovery credential | Password-type input; failed attempts return a generic error and do not resume |
| Join | Requires a valid six-character game code, an open multiplayer session, and a unique nickname; no recovery credential is needed because join creates a new player | User supplies invite code and nickname; app then issues a one-time recovery credential |

Single Player games are stored as separate sessions, and their mode prevents multiplayer join/resume. Player tables use session/player composite foreign keys, so pairing one session with a player from a different session is rejected.

## Credentials and private data

- Host and recovery credentials are random values; only their SHA-256 hashes are stored in SQLite.
- Resume checks use `hmac.compare_digest` and generic failure messages.
- New credentials are intentionally displayed once so the player can save them. They are not included in lobby lists, leaderboard rows, reports, or ordinary success/error messages.
- The reviewed application code does not log credentials. Hosting-provider and platform-level logs were outside this local code review.
- Player IDs are not included in public lobby or leaderboard data. Streamlit widget keys include the current player's ID for uniqueness; that is the current browser's own ID, not another player's ID.

## Join-code abuse

Six-character session codes use a 31-character alphabet (about 29.7 bits of search space). There is no application-level attempt throttle and no maximum player count. Someone who learns a valid waiting-room code can create multiple player records using different nicknames, and a determined online guesser can make repeated attempts. This is a confirmed abuse exposure for a publicly reachable app, though it requires guessing or obtaining an invite code and is not evidence of access to existing players' accounts.

No rate limiter was added in this review. Streamlit does not provide a stable client-IP value to this storage layer, and a naive per-IP limit can block an entire classroom sharing Wi-Fi. Before broader public use, put attempt throttling at the hosting/reverse-proxy layer (with a modest threshold and shared-network testing), and consider a configurable session player cap. Keep valid classroom joins unaffected.

## Tests added

`tests/test_authorization_boundary.py` uses temporary databases to verify:

- Purchase, price, menu, lease, trade, progress, history, and report operations reject a player ID paired with a different session ID and leave the victim unchanged.
- A pending event lookup with another session's player ID returns no event.
- Player recovery credentials cannot start host controls; host credentials cannot authenticate against a different session.
- Wrong recovery credentials are rejected without being echoed.
- Solo sessions cannot be joined or resumed in multiplayer mode and retain independent progress.

These tests verify tenant scoping and credential flows. They do not turn internal storage functions into authentication endpoints; the Streamlit server-side session remains the current caller identity boundary.

## Remaining limitation

Because storage calls do not require a credential on each operation, an unintended future caller that can choose both IDs could act as that player. Keep `v2_storage` behind the trusted application layer. If a REST API or other client is added, add an authenticated principal/capability boundary and tests for same-session cross-player access before exposing it. Also test rate limiting on the actual public host, since a local SQLite test cannot establish hosting-level protections.
