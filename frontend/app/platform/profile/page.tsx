"use client";

import { useEffect, useState } from "react";
import { getMyProfile, saveMyProfile, type StaffProfile } from "@/lib/platformApi";

// Each staff member's own details, on their own account. Nobody can open
// anyone else's: the backend reads the account from the session token and
// ignores any id the page might send (routes_platform_leads.py).

export default function StaffProfilePage() {
  const [profile, setProfile] = useState<StaffProfile | null>(null);
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [address, setAddress] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getMyProfile()
      .then((p) => {
        setProfile(p);
        setFullName(p.full_name ?? "");
        setPhone(p.phone ?? "");
        setJobTitle(p.job_title ?? "");
        setAddress(p.address ?? "");
        setContactName(p.emergency_contact_name ?? "");
        setContactPhone(p.emergency_contact_phone ?? "");
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const next = await saveMyProfile({
        full_name: fullName,
        phone,
        job_title: jobTitle,
        address: address || null,
        emergency_contact_name: contactName || null,
        emergency_contact_phone: contactPhone || null,
      });
      setProfile(next);
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">My profile</h1>
      <p className="text-[13.5px] text-ink-soft mb-6">
        Your own details, kept on your account. Only you can edit them.
      </p>

      {!profile ? (
        <div className="text-[13px] text-ink-soft">Loading…</div>
      ) : (
        <>
          <div className="bg-panel border border-line rounded-[4px] p-4 mb-5 text-[12.5px] text-ink-soft">
            Signed in as <span className="text-ink">{profile.email}</span> · role{" "}
            <span className="text-ink capitalize">{profile.role}</span>
          </div>

          {!profile.complete && (
            <div role="status" className="mb-5 text-[13px] text-ink bg-panel border border-amber/40 rounded-[4px] px-4 py-3">
              Please complete your name, phone number and job title.
            </div>
          )}

          <form onSubmit={save} className="bg-panel border border-line rounded-[4px] p-5 flex flex-col gap-4">
            <Field label="Full name" value={fullName} onChange={setFullName} required />
            <Field label="Phone number" value={phone} onChange={setPhone} required type="tel" />
            <Field label="Job title" value={jobTitle} onChange={setJobTitle} required placeholder="Sales executive" />
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] text-ink">Home address <span className="text-ink-soft">(optional)</span></span>
              <textarea
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                rows={2}
                maxLength={500}
                className="text-[13.5px] border border-line rounded-[4px] px-3 py-2 bg-paper text-ink focus:outline-none focus:ring-1 focus:ring-teal"
              />
            </label>
            <Field label="Emergency contact name" value={contactName} onChange={setContactName} optional />
            <Field label="Emergency contact phone" value={contactPhone} onChange={setContactPhone} optional type="tel" />

            {error && <div role="alert" className="text-[13px] text-red">{error}</div>}
            {saved && <div role="status" className="text-[13px] text-teal">Saved.</div>}

            <button
              type="submit"
              disabled={busy}
              className="mt-1 text-[13px] py-2 rounded-[3px] bg-teal-deep text-white hover:bg-teal transition-colors disabled:opacity-40"
            >
              {busy ? "Saving…" : "Save my details"}
            </button>
          </form>
        </>
      )}
    </div>
  );
}

function Field({
  label, value, onChange, required = false, optional = false, type = "text", placeholder,
}: {
  label: string; value: string; onChange: (v: string) => void;
  required?: boolean; optional?: boolean; type?: string; placeholder?: string;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[13px] text-ink">
        {label} {optional && <span className="text-ink-soft">(optional)</span>}
      </span>
      <input
        type={type}
        value={value}
        required={required}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="text-[13.5px] border border-line rounded-[4px] px-3 py-2 bg-paper text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
      />
    </label>
  );
}
