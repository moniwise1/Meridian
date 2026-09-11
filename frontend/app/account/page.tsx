"use client";

import { useEffect, useState } from "react";
import { getMe, updateDisplayName, changeOwnEmail, changeOwnPassword, type Me } from "@/lib/api";

function Field({
  label, value, onChange, placeholder, type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] text-ink-soft">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
      />
    </label>
  );
}

function Card({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="bg-panel border border-line rounded-[4px] p-4 mb-4">
      <div className="text-[14px] text-ink mb-0.5">{title}</div>
      <p className="text-[12.5px] text-ink-soft mb-3">{description}</p>
      {children}
    </div>
  );
}

export default function AccountPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [loadError, setLoadError] = useState("");

  // Display name
  const [displayName, setDisplayName] = useState("");
  const [nameSaving, setNameSaving] = useState(false);
  const [nameError, setNameError] = useState("");
  const [nameSaved, setNameSaved] = useState(false);

  // Email
  const [newEmail, setNewEmail] = useState("");
  const [emailPassword, setEmailPassword] = useState("");
  const [emailSaving, setEmailSaving] = useState(false);
  const [emailError, setEmailError] = useState("");
  const [emailSaved, setEmailSaved] = useState(false);

  // Password
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [passwordSaved, setPasswordSaved] = useState(false);

  function load() {
    getMe()
      .then((m) => {
        setMe(m);
        setDisplayName(m.display_name ?? "");
      })
      .catch((e) => setLoadError((e as Error).message));
  }

  useEffect(load, []);

  async function handleSaveName(e: React.FormEvent) {
    e.preventDefault();
    setNameSaving(true);
    setNameError("");
    setNameSaved(false);
    try {
      const updated = await updateDisplayName(displayName);
      setMe(updated);
      setNameSaved(true);
    } catch (err) {
      setNameError((err as Error).message);
    } finally {
      setNameSaving(false);
    }
  }

  async function handleSaveEmail(e: React.FormEvent) {
    e.preventDefault();
    setEmailSaving(true);
    setEmailError("");
    setEmailSaved(false);
    try {
      const updated = await changeOwnEmail(newEmail, emailPassword);
      setMe(updated);
      setNewEmail("");
      setEmailPassword("");
      setEmailSaved(true);
    } catch (err) {
      setEmailError((err as Error).message);
    } finally {
      setEmailSaving(false);
    }
  }

  async function handleSavePassword(e: React.FormEvent) {
    e.preventDefault();
    setPasswordError("");
    setPasswordSaved(false);
    if (newPassword !== confirmPassword) {
      setPasswordError("New passwords don't match.");
      return;
    }
    setPasswordSaving(true);
    try {
      await changeOwnPassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordSaved(true);
    } catch (err) {
      setPasswordError((err as Error).message);
    } finally {
      setPasswordSaving(false);
    }
  }

  return (
    <div className="max-w-xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Account</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">Your personal sign-in details for this workspace.</p>

      {loadError && <div className="mb-6 text-[13px] text-red">{loadError}</div>}

      {me && (
        <>
          <Card title="Display name" description="Shown instead of your email around the app. Purely cosmetic — never used to sign in.">
            <form onSubmit={handleSaveName} className="flex items-end gap-2">
              <div className="flex-1">
                <Field label="Name" value={displayName} onChange={setDisplayName} placeholder="e.g. Joel Umunnah" />
              </div>
              <button
                type="submit"
                disabled={nameSaving}
                className="text-[13px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
              >
                {nameSaving ? "Saving…" : "Save"}
              </button>
            </form>
            {nameError && <div className="mt-2 text-[12.5px] text-red">{nameError}</div>}
            {nameSaved && !nameError && <div className="mt-2 text-[12.5px] text-teal">Saved.</div>}
          </Card>

          <Card
            title="Email"
            description={
              me.email_change_available
                ? "Your sign-in email. It can be changed once — after that, contact support to change it again."
                : "Your sign-in email. You've already used your one change — contact support@getmeridiananalytics.com to change it again."
            }
          >
            <div className="text-[13px] text-ink mb-3 font-[family-name:var(--font-mono)]">{me.email}</div>
            {me.email_change_available && (
              <form onSubmit={handleSaveEmail} className="flex flex-col gap-3">
                <Field label="New email" value={newEmail} onChange={setNewEmail} placeholder="you@company.com" type="email" />
                <Field label="Current password (to confirm it's you)" value={emailPassword} onChange={setEmailPassword} type="password" placeholder="••••••••" />
                <button
                  type="submit"
                  disabled={emailSaving}
                  className="self-start text-[13px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
                >
                  {emailSaving ? "Saving…" : "Change email"}
                </button>
              </form>
            )}
            {emailError && <div className="mt-2 text-[12.5px] text-red">{emailError}</div>}
            {emailSaved && !emailError && <div className="mt-2 text-[12.5px] text-teal">Email updated.</div>}
          </Card>

          <Card title="Password" description="Requires your current password.">
            <form onSubmit={handleSavePassword} className="flex flex-col gap-3">
              <Field label="Current password" value={currentPassword} onChange={setCurrentPassword} type="password" placeholder="••••••••" />
              <Field label="New password" value={newPassword} onChange={setNewPassword} type="password" placeholder="At least 8 characters" />
              <Field label="Confirm new password" value={confirmPassword} onChange={setConfirmPassword} type="password" placeholder="••••••••" />
              <button
                type="submit"
                disabled={passwordSaving}
                className="self-start text-[13px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
              >
                {passwordSaving ? "Saving…" : "Change password"}
              </button>
            </form>
            {passwordError && <div className="mt-2 text-[12.5px] text-red">{passwordError}</div>}
            {passwordSaved && !passwordError && <div className="mt-2 text-[12.5px] text-teal">Password changed.</div>}
          </Card>
        </>
      )}
    </div>
  );
}
