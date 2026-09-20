import { useEffect, useState } from "react";
import { api, type Certificate } from "../api";
import Help from "../components/Help";

// The certificates NASQuay trusts when verifying a NAS, uploaded once and chosen per NAS
// in Settings → NAS.
//
// Nothing here is a credential: a certificate is the public half by definition, so unlike
// a token it goes in and comes back out. An upload carrying a private key is refused by
// the server.

const expired = (cert: Certificate) => Date.parse(cert.not_after) < Date.now();

// The date alone; the time a certificate expires at is never the point.
const day = (value: string) => (value ? value.slice(0, 10) : "");

export default function CertSettings() {
  const [certs, setCerts] = useState<Certificate[]>([]);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", pem: "" });
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    api.certificates
      .list()
      .then(setCerts)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Could not load the certificates"),
      );

  useEffect(() => {
    load();
  }, []);

  const act = async (what: () => Promise<unknown>, said: string) => {
    setError("");
    setNote("");
    try {
      await what();
      setNote(said);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That did not work");
    }
  };

  // The file is read in the browser and sent as text: there is no file upload endpoint,
  // and nothing is written to the host's disk.
  const readFile = async (file: File) => {
    setError("");
    try {
      const text = await file.text();
      setForm((was) => ({ name: was.name || file.name.replace(/\.[^.]+$/, ""), pem: text }));
    } catch {
      setError("That file could not be read");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-xs uppercase tracking-wide text-zinc-300">Certificates</h2>
        <Help>
          <p>The certificates NASQuay will verify a NAS against. Upload one here, then choose it for a NAS in Settings → NAS.</p>
          <p>This is the alternative to pinning. Pinning records the exact certificate one NAS presents and refuses anything else — simple, and right for the self-signed certificate a QNAP ships with. Uploading the authority that issued your certificates instead means the chain and the name are checked properly, and one upload covers every NAS it issued for.</p>
          <p>Because the name is checked, the address recorded for the NAS has to be one the certificate covers. A certificate issued for a hostname will not verify a NAS reached by its IP address — use the hostname, or pin instead.</p>
          <p>Upload the certificate only. A file containing a private key is refused: NASQuay never needs the private half of anything a NAS presents.</p>
          <p>A certificate a NAS still uses cannot be deleted.</p>
        </Help>
        {error && <span className="text-sm text-red-400">{error}</span>}
        {note && !error && <span className="text-sm text-emerald-400">{note}</span>}
      </div>

      <div className="card space-y-3">
        <button
          className="w-full flex items-center gap-3 text-left"
          onClick={() => setAdding((was) => !was)}
        >
          <span className="text-zinc-300 w-3">{adding ? "▾" : "▸"}</span>
          <span className="text-sm">Upload certificate</span>
          <span className="text-xs text-zinc-300">
            a .crt, .pem or .cer file, or the PEM text pasted in
          </span>
        </button>

        {adding && (
          <div className="border-t border-zinc-600 pt-3 space-y-3">
            <div className="flex items-end gap-3 flex-wrap">
              <label className="space-y-1">
                <span className="text-xs text-zinc-300">Name</span>
                <input
                  className="field w-64"
                  placeholder="Our own authority"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs text-zinc-300">Choose a file</span>
                <input
                  type="file"
                  accept=".crt,.pem,.cer,.ca-bundle,application/x-pem-file,application/x-x509-ca-cert,text/plain"
                  className="field w-72 text-xs file:mr-2 file:border-0 file:bg-zinc-700 file:text-zinc-100 file:px-2 file:py-0.5"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) readFile(file);
                  }}
                />
              </label>
            </div>

            <label className="space-y-1 block">
              <span className="text-xs text-zinc-300">Certificate (PEM)</span>
              <textarea
                className="field font-mono text-xs h-40"
                placeholder="-----BEGIN CERTIFICATE-----"
                value={form.pem}
                onChange={(e) => setForm({ ...form, pem: e.target.value })}
              />
              <span className="block text-xs text-zinc-300">
                An intermediate as well as the root can be pasted in together; both are kept.
              </span>
            </label>

            <button
              className="btn-primary"
              disabled={!form.name || !form.pem.trim()}
              onClick={() =>
                act(async () => {
                  await api.certificates.add({ name: form.name, pem: form.pem });
                  setForm({ name: "", pem: "" });
                  setAdding(false);
                }, "Certificate uploaded — choose it for a NAS in Settings → NAS")
              }
            >
              Upload certificate
            </button>
          </div>
        )}
      </div>

      {certs.map((cert) => (
        <div key={cert.id} className="card space-y-2">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm">{cert.name}</span>
            <span className="text-xs text-zinc-300">{cert.subject}</span>
            {cert.is_ca && <span className="text-xs text-amber-400">authority</span>}
            <span className={expired(cert) ? "text-xs text-red-400" : "text-xs text-zinc-300"}>
              {expired(cert) ? "expired " : "expires "}
              {day(cert.not_after)}
            </span>
            {cert.in_use > 0 && (
              <span className="text-xs text-zinc-300">
                used by {cert.in_use} {cert.in_use === 1 ? "NAS" : "NAS units"}
              </span>
            )}
            <span className="flex gap-2 ml-auto">
              <button
                className="btn"
                onClick={() => {
                  navigator.clipboard?.writeText(cert.pem);
                  setNote("Certificate copied");
                }}
              >
                Copy PEM
              </button>
              <button
                className="btn-danger"
                disabled={cert.in_use > 0}
                title={
                  cert.in_use > 0
                    ? "A certificate a NAS is verified against cannot be deleted"
                    : "Delete this certificate"
                }
                onClick={() => {
                  if (window.confirm(`Delete ${cert.name}?`))
                    act(() => api.certificates.remove(cert.id), `Deleted ${cert.name}`);
                }}
              >
                Delete
              </button>
            </span>
          </div>
          <div className="text-xs text-zinc-300">
            issued by {cert.issuer} · valid from {day(cert.not_before)}
          </div>
          <div className="text-xs text-zinc-300 font-mono break-all">{cert.fingerprint}</div>
        </div>
      ))}

      {certs.length === 0 && (
        <div className="text-xs text-zinc-300">
          No certificates uploaded. NAS units are pinned, or verified against the host's own
          trust store.
        </div>
      )}
    </div>
  );
}
