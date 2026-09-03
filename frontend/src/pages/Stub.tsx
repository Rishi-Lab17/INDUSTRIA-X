/** Stage-shell placeholder. Each stub names the stage that builds it —
    no fake controls, no fake data. */
export default function Stub({ title, stage, desc }: { title: string; stage: string; desc: string }) {
  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">{title}</h1>
          <p className="page-sub">{desc}</p>
        </div>
        <span className="badge"><span className="dot dot-warn" />{stage}</span>
      </div>
      <div className="panel">
        <div className="alert alert-warn">
          This module is built in <b>{stage}</b>. The shell navigation is live;
          functionality lands with that stage — nothing here is mocked.
        </div>
      </div>
    </div>
  );
}
