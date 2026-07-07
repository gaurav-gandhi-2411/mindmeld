/**
 * Full JOIN + RESULT-WRITE + leaderboard integration test — drives the REAL
 * client SDK (signInAnonymously, setDoc/updateDoc/getDocs) against the Auth +
 * Firestore emulators, mirroring the exact call sequences in
 * social_client.dart / social_service.dart, not an approximation of them.
 *
 * This extends create_group_flow.test.js's coverage (create-group only) to
 * the two remaining 6a paths named in spec.md's acceptance criteria #2, #4,
 * #5, #8: a first-time user joining via a code (JoinFlowScreen's exact
 * sequence: preview with no profile yet -> set display name -> join), and
 * every member writing a result + the leaderboard ranking correctly while
 * staying spoiler-safe. Only unit-level coverage (fake SocialClient in
 * app/test/social_service_test.dart) existed for these paths before this —
 * the 2026-07-07 create-group bug slipped through exactly that kind of gap.
 *
 * Run (from repo root, needs JDK 21+):
 *   firebase-tests/node_modules/.bin/firebase emulators:exec --project demo-mindmeld-rules-test \
 *     --only firestore,auth "node firebase-tests/join_and_results_flow.test.js"
 */
const fs = require('fs');
const path = require('path');
const { initializeApp, deleteApp } = require('firebase/app');
const { getAuth, connectAuthEmulator, signInAnonymously, signOut } = require('firebase/auth');
const {
  getFirestore,
  connectFirestoreEmulator,
  doc,
  collection,
  getDoc,
  getDocs,
  setDoc,
  updateDoc,
  arrayUnion,
  serverTimestamp,
} = require('firebase/firestore');
const { initializeTestEnvironment } = require('@firebase/rules-unit-testing');

let passed = 0;
let failed = 0;

async function check(name, fn) {
  try {
    await fn();
    passed++;
    console.log(`  ok - ${name}`);
  } catch (e) {
    failed++;
    console.error(`  FAIL - ${name}`);
    console.error(`    ${e.message}`);
  }
}

/** Generates a Firebase app + connected Auth/Firestore pair, one per "device". */
function makeClient(appName) {
  const app = initializeApp(
    { apiKey: 'fake-api-key', projectId: 'demo-mindmeld-rules-test' },
    appName,
  );
  const auth = getAuth(app);
  connectAuthEmulator(auth, 'http://127.0.0.1:9099', { disableWarnings: true });
  const db = getFirestore(app);
  connectFirestoreEmulator(db, '127.0.0.1', 8080);
  return { app, auth, db };
}

/** Mirrors _LiveSocialClient.createGroup's sequential (non-batched) write. */
async function createGroupSequential(db, uid, name, code) {
  const groupRef = doc(collection(db, 'groups'));
  await setDoc(groupRef, {
    name, code, createdBy: uid, memberUids: [uid], createdAt: serverTimestamp(),
  });
  await setDoc(doc(db, 'codes', code), { groupId: groupRef.id });
  return groupRef.id;
}

/** Mirrors _LiveSocialClient.setDisplayName's create-or-update branch. */
async function setDisplayNameLikeClient(db, uid, displayName) {
  const ref = doc(db, 'users', uid);
  const snap = await getDoc(ref);
  if (!snap.exists()) {
    await setDoc(ref, { displayName, createdAt: serverTimestamp(), groupIds: [] });
  } else {
    await updateDoc(ref, { displayName });
  }
}

/** Mirrors SocialService.previewGroupForCode: resolve code -> fetch group, no profile write. */
async function previewGroupForCode(db, code) {
  const codeSnap = await getDoc(doc(db, 'codes', code));
  if (!codeSnap.exists()) return null;
  const groupId = codeSnap.data().groupId;
  const groupSnap = await getDoc(doc(db, 'groups', groupId));
  if (!groupSnap.exists()) return null;
  return { groupId, data: groupSnap.data() };
}

/** Mirrors _LiveSocialClient.joinGroup: read-then-arrayUnion-write + best-effort user index. */
async function joinGroupLikeClient(db, groupId, uid) {
  const groupRef = doc(db, 'groups', groupId);
  const snap = await getDoc(groupRef);
  const members = snap.data().memberUids || [];
  if (members.includes(uid)) return; // idempotent no-op, matches the real client.
  await updateDoc(groupRef, { memberUids: arrayUnion(uid) });
  await setDoc(doc(db, 'users', uid), { groupIds: arrayUnion(groupId) }, { merge: true });
}

/** Mirrors _LiveSocialClient.writeResult exactly (same field set, same path shape). */
async function writeResultLikeClient(db, { groupId, date, uid, displayName, outcome, guessesUsed, par, scoreVsPar, lang }) {
  const ref = doc(db, 'groups', groupId, 'days', date, 'results', uid);
  await setDoc(ref, {
    uid, displayName, outcome, guessesUsed, par, scoreVsPar, lang,
    finishedAt: serverTimestamp(),
  });
}

/** Mirrors _LiveSocialClient.fetchResults: fetch all result docs for a group/day, keyed by uid. */
async function fetchResultsLikeClient(db, groupId, date) {
  const snap = await getDocs(collection(db, 'groups', groupId, 'days', date, 'results'));
  const out = {};
  for (const d of snap.docs) out[d.id] = d.data();
  return out;
}

/**
 * Mirrors LeaderboardEntry.compare (social_models.dart): wins by fewest
 * guesses first, then losses, then not-played; losses/not-played break ties
 * by display name. Reimplemented here (not imported — this is a JS harness)
 * so the ranking behavior itself gets an independent, real-data check rather
 * than trusting the Dart unit test alone.
 */
function rankLeaderboard(entries) {
  const tier = (e) => (e.outcome === 'win' ? 0 : e.played ? 1 : 2);
  return [...entries].sort((a, b) => {
    const ta = tier(a);
    const tb = tier(b);
    if (ta !== tb) return ta - tb;
    if (ta === 0) return (a.guessesUsed ?? 1e9) - (b.guessesUsed ?? 1e9);
    return a.displayName.localeCompare(b.displayName);
  });
}

async function main() {
  const testEnv = await initializeTestEnvironment({
    projectId: 'demo-mindmeld-rules-test',
    firestore: {
      rules: fs.readFileSync(path.resolve(__dirname, '../firestore.rules'), 'utf8'),
      host: '127.0.0.1',
      port: 8080,
    },
  });
  await testEnv.clearFirestore();

  const alice = makeClient('alice-app');
  const bob = makeClient('bob-app');
  const carol = makeClient('carol-app');
  const date = '2026-07-07';
  const code = 'JOIN01';

  let aliceUid, bobUid, carolUid, groupId;

  // ---- Alice creates the group (setup, reusing the create-group pattern) ----
  await check('alice signs in and creates the group', async () => {
    aliceUid = (await signInAnonymously(alice.auth)).user.uid;
    await setDisplayNameLikeClient(alice.db, aliceUid, 'Alice');
    groupId = await createGroupSequential(alice.db, aliceUid, 'Office Crew', code);
  });

  // ---- Bob: first-time-user deep-link join path (spec.md #2, #8) ----
  await check('bob (first-timer, no profile yet) can preview the group before joining', async () => {
    bobUid = (await signInAnonymously(bob.auth)).user.uid;
    // At this point Bob has NEVER called setDisplayName — previewing must not
    // require or create a profile, mirroring JoinFlowScreen's preview step.
    const preview = await previewGroupForCode(bob.db, code);
    if (!preview || preview.data.name !== 'Office Crew') {
      throw new Error(`expected to preview "Office Crew", got ${JSON.stringify(preview)}`);
    }
    const profileSnap = await getDoc(doc(bob.db, 'users', bobUid));
    if (profileSnap.exists()) throw new Error('preview must not create a profile doc');
  });

  await check('bob sets a display name and joins; group now has both members', async () => {
    await setDisplayNameLikeClient(bob.db, bobUid, 'Bob');
    const preview = await previewGroupForCode(bob.db, code);
    await joinGroupLikeClient(bob.db, preview.groupId, bobUid);

    const groupSnap = await getDoc(doc(alice.db, 'groups', groupId));
    const members = groupSnap.data().memberUids;
    if (!members.includes(aliceUid) || !members.includes(bobUid)) {
      throw new Error(`expected both members, got ${JSON.stringify(members)}`);
    }
  });

  await check('joining twice (re-tap / duplicate deep-link open) is idempotent, not an error', async () => {
    await joinGroupLikeClient(bob.db, groupId, bobUid);
    const groupSnap = await getDoc(doc(alice.db, 'groups', groupId));
    const members = groupSnap.data().memberUids;
    const bobCount = members.filter((m) => m === bobUid).length;
    if (bobCount !== 1) throw new Error(`expected bob exactly once, got ${bobCount} times`);
  });

  // ---- Carol: joins but will NOT play today (the "not played yet" case) ----
  await check('carol (first-timer) also joins the group', async () => {
    carolUid = (await signInAnonymously(carol.auth)).user.uid;
    await setDisplayNameLikeClient(carol.db, carolUid, 'Carol');
    await joinGroupLikeClient(carol.db, groupId, carolUid);
    const groupSnap = await getDoc(doc(alice.db, 'groups', groupId));
    if (!groupSnap.data().memberUids.includes(carolUid)) {
      throw new Error('carol should be a member after joining');
    }
  });

  // ---- Result-write path (spec.md #4) ----
  await check('alice writes a win result (6 guesses)', async () => {
    await writeResultLikeClient(alice.db, {
      groupId, date, uid: aliceUid, displayName: 'Alice',
      outcome: 'win', guessesUsed: 6, par: 6, scoreVsPar: 0, lang: 'en',
    });
  });

  await check('bob writes a win result (3 guesses — the best score)', async () => {
    await writeResultLikeClient(bob.db, {
      groupId, date, uid: bobUid, displayName: 'Bob',
      outcome: 'win', guessesUsed: 3, par: 6, scoreVsPar: -3, lang: 'en',
    });
  });

  await check('carol never writes a result today (models "not played yet")', async () => {
    const results = await fetchResultsLikeClient(carol.db, groupId, date);
    if (results[carolUid]) throw new Error('carol should have no result doc for today');
  });

  // ---- Leaderboard ranking + spoiler safety (spec.md #3, #5) ----
  await check('the ranked leaderboard has bob first, alice second, carol last (not played)', async () => {
    const raw = await fetchResultsLikeClient(alice.db, groupId, date);
    const groupSnap = await getDoc(doc(alice.db, 'groups', groupId));
    const memberUids = groupSnap.data().memberUids;

    // Synthesize "not played yet" rows exactly like SocialService.leaderboardFor.
    const entries = memberUids.map((uid) => {
      const r = raw[uid];
      if (r) return { uid, displayName: r.displayName, played: true, outcome: r.outcome, guessesUsed: r.guessesUsed };
      return { uid, displayName: uid === carolUid ? 'Carol' : uid, played: false, outcome: null, guessesUsed: null };
    });
    const ranked = rankLeaderboard(entries);

    const order = ranked.map((e) => e.uid);
    if (order[0] !== bobUid || order[1] !== aliceUid || order[2] !== carolUid) {
      throw new Error(`expected [bob, alice, carol], got ${JSON.stringify(order)}`);
    }
    const carolRow = ranked[2];
    if (carolRow.played !== false || carolRow.outcome !== null || carolRow.guessesUsed !== null) {
      throw new Error('carol\'s not-played row must carry no outcome/score data');
    }
  });

  await check('spoiler safety: no result doc EVER contains a guesses list or the secret word', async () => {
    const raw = await fetchResultsLikeClient(alice.db, groupId, date);
    const allowedFields = new Set(['uid', 'displayName', 'outcome', 'guessesUsed', 'par', 'scoreVsPar', 'lang', 'finishedAt']);
    for (const [uid, data] of Object.entries(raw)) {
      for (const field of Object.keys(data)) {
        if (!allowedFields.has(field)) {
          throw new Error(`result doc for ${uid} has an unexpected field "${field}" — spoiler-data leak risk`);
        }
      }
    }
  });

  await check('carol (a member who has not played) CAN list the day\'s results — sees scores, never guesses/word', async () => {
    const results = await fetchResultsLikeClient(carol.db, groupId, date);
    if (!results[aliceUid] || !results[bobUid]) {
      throw new Error('carol should be able to see alice\'s and bob\'s results as a fellow member');
    }
  });

  await signOut(alice.auth).catch(() => {});
  await signOut(bob.auth).catch(() => {});
  await signOut(carol.auth).catch(() => {});
  await deleteApp(alice.app);
  await deleteApp(bob.app);
  await deleteApp(carol.app);
  await testEnv.cleanup();

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exitCode = 1;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
