/**
 * The invite gate (spec M1 §9).
 *
 * The session cookie rides same-origin calls, so the client holds
 * no credential and this screen has no field to type into. What it
 * has to say is that an invite link is the way in.
 *
 * It renders on a 401 and on nothing else. A server that is down
 * is ApiError(0) and a broken server is a 500; sending either of
 * those readers to hunt for a link takes them somewhere no link
 * helps.
 */

export function InviteGate(): React.JSX.Element {
  return (
    <div style={{ padding: 28, maxWidth: 520 }}>
      <div className="card" style={{ gap: 10 }}>
        <span className="card-kicker">Invite</span>
        <p style={{ margin: 0 }}>This browser is not signed in.</p>
        <p className="text-muted" style={{ margin: 0 }}>
          Starvector is invite only. Open the invite link you were sent and this
          device stays signed in from then on — there is no password to keep,
          and nothing to type here.
        </p>
      </div>
    </div>
  );
}
