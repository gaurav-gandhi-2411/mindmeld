# Secret rotation runbook

What each Warmer credential is, whether it can be rotated, and how. This file never contains
key material. Refer to keys by resource-ID prefix or secret name only.

Inventory as of 2026-11-02. Projects: `warmer-prod-260813` (live), `mindmeld-c4bba` (legacy,
scheduled for deletion). Always pass `--account=` to gcloud.

## 1. Firebase web API keys: restrict, don't regenerate

| Key (ID prefix) | Project | Restriction |
|---|---|---|
| `e2b68dfb` | warmer-prod-260813 | HTTP referrers `https://playwarmer.vercel.app/*`, `https://warmer-prod-260813.firebaseapp.com/*`, `http://localhost/*`; 27 API targets |
| `e04584a9` | mindmeld-c4bba | same referrers; 27 API targets |

**Can these keys be public?** Yes. Firebase web keys are identifiers shipped in every client bundle, and they have been in git history since July 2026. What protects the project is not the key's secrecy but these three controls:
- the referrer and API restriction above;
- Firestore rules;
- the Auth settings in section 2.

**Default action: restrict.** When the key leaks, or a new origin needs access, update the restriction. Don't create a new key:

```
gcloud services api-keys update <KEY_ID> --project=<PROJECT> --account=<OWNER> \
  --allowed-referrers=<comma-separated list> --api-target=...   # keep every existing target
```

Verify it in two ways:
- A request from a non-allowed origin returns 403 `API_KEY_HTTP_REFERRER_BLOCKED`.
- The live site still loads a puzzle and signs in anonymously.

**Regenerate only when** the key was used for abuse that the restriction can't stop. That means:
1. create a new key with the same restrictions;
2. update `app/lib/firebase_web_options.dart`;
3. merge, and deploy via the normal flow;
4. confirm the live bundle serves the new key;
5. only then delete the old key.

Deleting first breaks every cached client.

Never run `gcloud services api-keys get-key-string` in a shared session or log.

## 2. Firebase Auth password-hash parameters: NOT rotatable

The scrypt signer key and salt separator are fixed for the life of a project. They cannot be rotated.

**Mitigation:**
- Both projects are anonymous-only: the Identity Platform config enables only anonymous sign-in.
- The provider census on 2026-11-02 found 0 email/password users (warmer-prod 57 users, c4bba 55, all anonymous). So there are no password hashes that the parameters could help crack.
- **Rule:** never enable email/password sign-in on a project whose hash parameters have been exposed (c4bba's appeared in a migration runbook; PR #31 redacts the current copy, but it remains in git history, so treat it as public). If password auth is ever needed, use a fresh project.
- Never run `firebase auth:export` outside an approved migration. Treat its output as a secret, and keep it out of the repo (gitignored).

## 3. FCM / Admin SDK service-account keys

| Secret | Holds | Used by |
|---|---|---|
| GitHub repo secret `FIREBASE_SERVICE_ACCOUNT` (set 2026-07-07) | JSON key for `firebase-adminsdk-fbsvc@mindmeld-c4bba` (user-managed key created 2026-07-07, two minutes before the secret; inferred from timing) | `.github/workflows/daily-notification.yml` (currently disabled; runs failing since at least 2026-10-27) |

`warmer-prod-260813` has no user-managed SA keys.

**To restore daily notifications against warmer-prod:**
1. Create a key for `firebase-adminsdk-fbsvc@warmer-prod-260813` (owner account).
2. Run `gh secret set FIREBASE_SERVICE_ACCOUNT < key.json`.
3. Delete the local file immediately.
4. Dispatch the workflow with `dry_run: true`.
5. Re-enable the workflow.
6. Delete the c4bba key: `gcloud iam service-accounts keys delete <ID> --iam-account=... --project=mindmeld-c4bba`.

Deleting the c4bba project also invalidates that key.

**Rotation (any time):**
1. Create the new key.
2. Update the secret.
3. Do a dry run.
4. Delete the old key.

A key ID never appears in the repo; list keys with `--managed-by=user`.

## 4. Other service accounts

There are no other user-managed keys. Google-managed SA keys rotate automatically, so no action is needed.

To audit:

```
gcloud iam service-accounts keys list --iam-account=<SA> --managed-by=user --project=<P> --account=<OWNER>
```

## 5. GitHub and Hugging Face tokens

- **`HF_TOKEN` repo secret (set 2026-07-18):** no workflow references it. Generator scripts read `HF_TOKEN` from the local `.env`. To rotate:
  1. Create a new fine-grained token on huggingface.co.
  2. Update `.env` and, if still wanted, `gh secret set HF_TOKEN`.
  3. Revoke the old token on huggingface.co.
  - Consider deleting the unused repo secret.
- **GitHub:**
  - Workflows use the per-run `GITHUB_TOKEN`, which never needs rotating.
  - `mindmeld-payloads` has no secrets and no deploy keys. Neither repo has deploy keys.
  - Personal `gh` CLI auth is a per-machine token. To rotate it: `gh auth refresh` or `gh auth login`, then revoke the old token under GitHub, Settings, Applications.
- **Vercel:** there is no token in CI. Production deploys run from the owner's CLI login. If that login leaks, revoke it under Vercel, Account, Tokens.

## After any rotation

1. Confirm the live site loads, signs in, and fetches today's payload.
2. Confirm the payloads monitor is green.
3. Record the date and key-ID prefix in PLAN.md.
